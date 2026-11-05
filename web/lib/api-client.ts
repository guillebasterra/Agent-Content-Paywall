import { API_URL } from "./api";
import { browserSupabase } from "./supabase-browser";
import { AUTH_MODE } from "./supabase-config";

/** Calls a writer route from the browser, as whoever is signed in. */
export async function writerFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (AUTH_MODE === "supabase") {
    const { data } = await browserSupabase().auth.getSession();
    if (data.session) headers.set("Authorization", `Bearer ${data.session.access_token}`);
  }
  return fetch(`${API_URL}${path}`, { ...init, headers });
}
