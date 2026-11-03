import { API_URL, type Payout } from "./api";

export type Session = { writer: { name: string } };

/**
 * Who is signed in. Placeholder until Supabase Auth replaces it: the sign-in screens are
 * UI only and everything runs as the backend's one demo writer, so this is the only
 * frontend code that changes when real auth arrives.
 */
export async function getSession(): Promise<Session | null> {
  try {
    const response = await fetch(`${API_URL}/me/payout`, { cache: "no-store" });
    if (!response.ok) return null;
    const payout: Payout = await response.json();
    return { writer: { name: payout.name } };
  } catch {
    return null;
  }
}
