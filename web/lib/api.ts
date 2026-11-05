export const API_URL = (process.env.NEXT_PUBLIC_TOLLGATE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type Article = {
  id: string;
  title: string;
  author: string;
  abstract: string;
  preview: string;
  word_count: number;
  price_usd: string;
  price_usd_micros: number;
  price_xrp: string;
  license: "ai-input" | "ai-train";
  train_price_usd: string | null;
  allowed_agents: string[];
  reads: number;
  earned_usd_micros: number;
};

export type Read = { tx_hash: string; rail: string; amount_usd_micros: number; agent: string; created_at: string; title: string };

export type StripeStatus = { available: boolean; connected: boolean; payouts_enabled: boolean };

export type Dashboard = {
  payout: { method: string | null; xrpl_address: string | null; stripe: StripeStatus };
  xrp_usd_rate: string;
  balance_usd_micros: number;
  totals: { reads: number; earned_usd_micros: number; month_usd_micros: number };
  latest: Read | null;
  recent: Read[];
  pieces: { id: string; title: string; price_usd_micros: number; reads: number; earned_usd_micros: number; agents: string[] }[];
  by_agent: { name: string; reads: number; earned_usd_micros: number }[];
};

export type Payout = { name: string; email: string | null; payout_method: string | null; xrpl_address: string | null; stripe: StripeStatus };

/** Stands in for the paid text, which never reaches the browser. It is only ever shown blurred. */
export const BLURRED_FILLER =
  "The part that matters starts here, with the specifics an agent came for: names, numbers, the steps in order, " +
  "and what went wrong on the way. The rest of the piece follows from there, source by source, with each detail " +
  "in the place a reader would expect to find it.";

/** The placeholder rate behind every XRP amount shown. Prices are USD; only XRPL invoices use XRP. */
export const XRP_USD_RATE = Number(process.env.NEXT_PUBLIC_XRP_USD_RATE ?? "2");

/** Shows cents, with up to 6 decimals below $1 so a tiny price never displays as $0.00. */
export function usd(micros: number): string {
  const dollars = micros / 1_000_000;
  return dollars.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: dollars < 1 ? 6 : 2 });
}

export const count = (n: number) => n.toLocaleString("en-US");

export const reads = (n: number) => `${count(n)} ${n === 1 ? "read" : "reads"}`;

export const shortAddress = (address: string) =>
  address.length > 12 ? `${address.slice(0, 5)}…${address.slice(-4)}` : address;

/** The link is built from the hash, so server data can never supply the URL scheme. */
export const txUrl = (hash: string) => `https://testnet.xrpl.org/transactions/${encodeURIComponent(hash)}`;

export function timeAgo(iso: string, now: number): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

/** FastAPI sends a string for our own errors and a list for validation errors. */
export async function errorMessage(response: Response): Promise<string> {
  try {
    const { detail } = await response.json();
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]) return `${detail[0].loc?.at(-1) ?? "Input"}: ${detail[0].msg}`;
  } catch {
    // Not JSON. Fall through to the generic message.
  }
  return `The request failed (HTTP ${response.status}).`;
}
