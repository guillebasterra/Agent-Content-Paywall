"use client";

import { useState } from "react";
import { browserSupabase } from "@/lib/supabase-browser";
import { AUTH_MODE } from "@/lib/supabase-config";

/** Explicit credential export; never render or log the credential. */
export default function PublisherToken() {
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  if (AUTH_MODE !== "supabase") return null;

  async function copyToken() {
    setBusy(true);
    try {
      const client = browserSupabase();
      const { data: user, error: userError } = await client.auth.getUser();
      if (userError || !user.user) throw new Error();
      const { data, error } = await client.auth.getSession();
      if (error || !data.session) throw new Error();
      await navigator.clipboard.writeText(data.session.access_token);
      const expiry = data.session.expires_at;
      setStatus(`Copied. Paste into TOLLGATE_WRITER_TOKEN in your local .env.${expiry ? ` Expires ${new Date(expiry * 1000).toLocaleString()}.` : ""}`);
    } catch {
      setStatus("Could not copy. Check that you are signed in and clipboard access is allowed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section style={{ maxWidth: 1080, margin: "0 auto", padding: "24px 32px 48px" }}>
      <h2>Publisher Bot</h2>
      <p className="muted small">Connect your local bot with a temporary writer token. This grants your account’s writer API access, not only access to one Discord channel. Keep it private; copy a new token when it expires.</p>
      <button className="button button-outline" onClick={copyToken} disabled={busy}>
        {busy ? "Copying…" : "Copy temporary writer token"}
      </button>
      <p className="muted small" role="status">{status}</p>
    </section>
  );
}
