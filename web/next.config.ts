import path from "node:path";
import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// One .env for the whole repo. Only the values named here reach the browser.
// Forced, because Next has already loaded web/ by now and would otherwise return that cached result.
loadEnvConfig(path.resolve(process.cwd(), ".."), undefined, undefined, true);

const config: NextConfig = {
  devIndicators: false, // The floating badge would cover content on the demo screen.
  agentRules: false, // Agent guidance lives in the repo's CLAUDE.md.
  env: {
    NEXT_PUBLIC_XRP_USD_RATE: process.env.XRP_USD_RATE ?? "2",
    NEXT_PUBLIC_PAYMENT_RAIL: process.env.PAYMENT_RAIL || "base",
    NEXT_PUBLIC_AUTH_MODE: process.env.AUTH_MODE ?? "demo",
    NEXT_PUBLIC_SUPABASE_URL: process.env.SUPABASE_URL ?? "",
    NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: process.env.SUPABASE_PUBLISHABLE_KEY ?? "",
  },
};

export default config;
