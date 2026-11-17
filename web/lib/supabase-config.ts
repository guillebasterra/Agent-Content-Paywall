/** Filled in next.config.ts from the repo's .env. Only public values ever reach these. */
export const AUTH_MODE = process.env.NEXT_PUBLIC_AUTH_MODE === "supabase" ? "supabase" : "demo";
export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
export const SUPABASE_KEY = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? "";
