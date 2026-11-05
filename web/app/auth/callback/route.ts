import type { EmailOtpType } from "@supabase/supabase-js";
import { type NextRequest, NextResponse } from "next/server";
import { API_URL } from "@/lib/api";
import { landingPath } from "@/lib/landing";
import { serverSupabase } from "@/lib/supabase-server";

/** For a link clicked in the sign-in email. Entering the code on /signin doesn't come through here. */
export async function GET(request: NextRequest) {
  const url = request.nextUrl;
  const code = url.searchParams.get("code");
  const tokenHash = url.searchParams.get("token_hash");
  const type = url.searchParams.get("type") as EmailOtpType | null;
  const supabase = await serverSupabase();

  const { error } = code
    ? await supabase.auth.exchangeCodeForSession(code)
    : tokenHash && type
      ? await supabase.auth.verifyOtp({ token_hash: tokenHash, type })
      : { error: new Error("no sign-in details") };
  if (error) return NextResponse.redirect(new URL("/signin?error=link", request.url));

  const { data } = await supabase.auth.getSession();
  const payout = await fetch(`${API_URL}/me/payout`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${data.session?.access_token}` },
  })
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null);
  return NextResponse.redirect(new URL(landingPath(payout), request.url));
}
