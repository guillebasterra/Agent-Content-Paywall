import { createBrowserClient } from "@supabase/ssr";
import { SUPABASE_KEY, SUPABASE_URL } from "./supabase-config";

export const browserSupabase = () => createBrowserClient(SUPABASE_URL, SUPABASE_KEY);
