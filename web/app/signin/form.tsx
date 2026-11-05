"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { writerFetch } from "@/lib/api-client";
import { landingPath } from "@/lib/landing";
import { browserSupabase } from "@/lib/supabase-browser";
import { AUTH_MODE } from "@/lib/supabase-config";

const DEMO_NEXT = "/onboarding/payout";
const LINK_FAILED = "That sign-in link didn't work. Enter your email to get a new code.";

function friendly(message: string): string {
  if (/rate limit/i.test(message)) return "Too many emails were sent. Wait a while, or use a code from make demo-otp.";
  if (/expired|invalid/i.test(message)) return "That code is wrong or has expired. Check it, or send a new one.";
  return message;
}

export default function SignInForm() {
  const router = useRouter();
  const linkFailed = useSearchParams().get("error") === "link";
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState(linkFailed ? LINK_FAILED : "");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function sendCode() {
    setBusy(true);
    setError("");
    setNotice("");
    const { error: failure } = await browserSupabase().auth.signInWithOtp({
      email: email.trim(),
      options: { shouldCreateUser: true, emailRedirectTo: `${window.location.origin}/auth/callback` },
    });
    if (failure) setError(friendly(failure.message));
    else {
      setSent(true);
      setNotice(`We sent a code to ${email.trim()}.`);
    }
    setBusy(false);
  }

  async function verifyCode() {
    setBusy(true);
    setError("");
    setNotice("");
    const { error: failure } = await browserSupabase().auth.verifyOtp({ email: email.trim(), token: code.trim(), type: "email" });
    if (failure) {
      setError(friendly(failure.message));
      setBusy(false);
      return;
    }
    const response = await writerFetch("/me/payout").catch(() => null);
    const payout = response?.ok ? await response.json() : null;
    router.push(landingPath(payout));
    router.refresh();
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (AUTH_MODE === "demo") router.push(DEMO_NEXT);
    else if (sent) verifyCode();
    else sendCode();
  }

  return (
    <>
      <form className="field-group" onSubmit={submit}>
        {!sent ? (
          <>
            <label htmlFor="email" className="label-muted">Email</label>
            <input
              id="email"
              className="input input-large"
              type="email"
              required={AUTH_MODE === "supabase"}
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            <button type="submit" className="button button-large" disabled={busy}>{busy ? "Sending…" : "Continue"}</button>
          </>
        ) : (
          <>
            <label htmlFor="code" className="label-muted">Code</label>
            <input
              id="code"
              className="input input-large mono"
              type="text"
              inputMode="numeric"
              required
              autoComplete="one-time-code"
              autoFocus
              placeholder="123456"
              value={code}
              onChange={(event) => setCode(event.target.value)}
            />
            <button type="submit" className="button button-large" disabled={busy}>{busy ? "Checking…" : "Sign in"}</button>
          </>
        )}
      </form>
      {notice && <p className="muted small" role="status">{notice}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {sent ? (
        <p className="muted small">
          <button type="button" className="text-button" disabled={busy} onClick={sendCode}>Send a new code</button>
          {" · "}
          <button type="button" className="text-button" disabled={busy} onClick={() => { setSent(false); setCode(""); setError(""); setNotice(""); }}>Use another email</button>
        </p>
      ) : (
        <>
          <div className="divider">or</div>
          <button type="button" className="button button-outline button-large" disabled title="Coming soon">
            Sign in with an XRPL wallet (coming soon)
          </button>
        </>
      )}
    </>
  );
}
