import { API_URL, type Payout } from "./api";
import { serverSupabase } from "./supabase-server";
import { AUTH_MODE } from "./supabase-config";

export type Session = { writer: { name: string } };

/**
 * Who is signed in. Demo mode is the backend's one demo writer. In Supabase mode the backend
 * verifies the token and returns the writer, so the cookie alone is never trusted here.
 */
export async function getSession(): Promise<Session | null> {
  try {
    const headers: Record<string, string> = {};
    if (AUTH_MODE === "supabase") {
      const { data } = await (await serverSupabase()).auth.getSession();
      if (!data.session) return null;
      headers.Authorization = `Bearer ${data.session.access_token}`;
    }
    const response = await fetch(`${API_URL}/me/payout`, { cache: "no-store", headers });
    if (!response.ok) return null;
    const payout: Payout = await response.json();
    return { writer: { name: payout.name } };
  } catch {
    return null;
  }
}
