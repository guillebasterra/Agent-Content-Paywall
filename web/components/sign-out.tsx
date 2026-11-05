"use client";

import { useRouter } from "next/navigation";
import { browserSupabase } from "@/lib/supabase-browser";

export default function SignOut() {
  const router = useRouter();
  return (
    <button
      type="button"
      className="text-button muted"
      onClick={async () => {
        await browserSupabase().auth.signOut();
        router.push("/signin");
        router.refresh();
      }}
    >
      Sign out
    </button>
  );
}
