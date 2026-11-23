import { randomBytes } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { API_URL } from "@/lib/api";

const cookiePath = "/api/discord-review";
const sourcePattern = /^\d{17,20}\/\d{17,20}\/\d{17,20}$/;
type Context = { params: Promise<{ action: string }> };

function cookieOptions(req: NextRequest, maxAge: number) {
  return {
    path: cookiePath,
    httpOnly: true,
    secure: req.nextUrl.protocol === "https:",
    sameSite: "lax" as const,
    maxAge,
  };
}

export async function GET(req: NextRequest, ctx: Context) {
  const { action } = await ctx.params;
  const source = req.nextUrl.searchParams.get("source") ?? "";
  const clientId = process.env.DISCORD_PUBLISHER_APPLICATION_ID;
  const secret = process.env.DISCORD_OAUTH_CLIENT_SECRET;
  const callback = process.env.DISCORD_REVIEW_CALLBACK_URL;
  if (action === "start" || action === "callback") {
    if (!clientId || !secret || !callback)
      return new Response("Discord reviewer sign-in is not configured.", {
        status: 503,
      });
    if (action === "start") {
      if (!sourcePattern.test(source))
        return new Response("Invalid source", { status: 400 });
      const nonce = randomBytes(32).toString("hex");
      const params = new URLSearchParams({
        client_id: clientId,
        response_type: "code",
        scope: "identify guilds.members.read",
        redirect_uri: callback,
        state: nonce,
      });
      const result = NextResponse.redirect(
        "https://discord.com/oauth2/authorize?" + params,
      );
      result.cookies.set("ama_state", nonce, cookieOptions(req, 600));
      result.cookies.set("ama_source", source, cookieOptions(req, 600));
      return result;
    }
    const state = req.cookies.get("ama_state")?.value;
    const target = req.cookies.get("ama_source")?.value ?? "";
    const code = req.nextUrl.searchParams.get("code");
    if (
      !state ||
      state !== req.nextUrl.searchParams.get("state") ||
      !code ||
      !sourcePattern.test(target)
    )
      return new Response(
        "Sign-in expired or cancelled. Reopen the review link.",
        { status: 400 },
      );
    const exchange = await fetch("https://discord.com/api/v10/oauth2/token", {
      method: "POST",
      cache: "no-store",
      body: new URLSearchParams({
        client_id: clientId,
        client_secret: secret,
        grant_type: "authorization_code",
        code,
        redirect_uri: callback,
      }),
    });
    if (!exchange.ok)
      return new Response("Discord sign-in failed. Reopen the review link.", {
        status: 401,
      });
    const token = await exchange.json();
    const result = NextResponse.redirect(
      new URL("/community/review/" + target, callback),
    );
    result.cookies.set(
      "ama_token",
      token.access_token,
      cookieOptions(req, Math.min(900, token.expires_in)),
    );
    for (const key of ["ama_state", "ama_source"])
      result.cookies.set(key, "", cookieOptions(req, 0));
    return result;
  }
  return forward(req, action, source);
}

export async function POST(req: NextRequest, ctx: Context) {
  if (req.headers.get("origin") !== req.nextUrl.origin)
    return new Response("Invalid origin", { status: 403 });
  return forward(
    req,
    (await ctx.params).action,
    req.nextUrl.searchParams.get("source") ?? "",
  );
}

async function forward(req: NextRequest, action: string, source: string) {
  if (action !== "draft" || !sourcePattern.test(source))
    return new Response("Invalid source", { status: 400 });
  const token = req.cookies.get("ama_token")?.value;
  if (!token)
    return NextResponse.json({ detail: "Sign in to review." }, { status: 401 });
  const result = await fetch(API_URL + "/discord/review/" + source, {
    method: req.method,
    cache: "no-store",
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
    },
    body: req.method === "POST" ? await req.text() : undefined,
  });
  return new Response(result.body, {
    status: result.status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
    },
  });
}
