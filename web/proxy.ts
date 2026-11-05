import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";
import { AUTH_MODE, SUPABASE_KEY, SUPABASE_URL } from "@/lib/supabase-config";

const WRITER_ONLY = ["/dashboard", "/upload", "/onboarding"];

/** Keeps the Supabase session fresh and sends visitors to the right side of sign-in. */
export async function proxy(request: NextRequest) {
  if (AUTH_MODE !== "supabase") return NextResponse.next();

  let response = NextResponse.next({ request });
  const supabase = createServerClient(SUPABASE_URL, SUPABASE_KEY, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll(items) {
        items.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        items.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });
  const { data } = await supabase.auth.getClaims();
  const signedIn = Boolean(data?.claims);
  const path = request.nextUrl.pathname;

  if (!signedIn && WRITER_ONLY.some((p) => path === p || path.startsWith(`${p}/`))) {
    return NextResponse.redirect(new URL("/signin", request.url));
  }
  if (signedIn && (path === "/" || path === "/signin")) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|auth/callback).*)"],
};
