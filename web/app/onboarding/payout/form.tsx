"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { PAYMENT_RAIL, type Payout, type StripeStatus, errorMessage, usd } from "@/lib/api";
import { writerFetch } from "@/lib/api-client";

const JSON_HEADERS = { "Content-Type": "application/json" };
const UNREACHABLE = "The backend can't be reached. Start it with make server.";

export default function PayoutForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [stripe, setStripe] = useState<StripeStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"" | "saving" | "stripe">("");
  const [rail, setRail] = useState<"base" | "xrpl">(PAYMENT_RAIL);
  const [balance, setBalance] = useState(0);
  const onBase = rail === "base";

  useEffect(() => {
    const controller = new AbortController();
    const returned = new URLSearchParams(window.location.search).has("stripe");
    (async () => {
      try {
        const response = await writerFetch("/me/payout", { signal: controller.signal });
        if (!response.ok) return;
        const payout: Payout = await response.json();
        setRail(payout.payment.rail);
        setBalance(payout.balance_usd_micros);
        // Keep anything typed while this was loading.
        const saved = payout.xrpl_address;
        if (saved) setAddress((typed) => typed || saved);
        if (payout.name) setName((typed) => typed || payout.name);
        setStripe(payout.stripe);
        if (returned && payout.stripe.available) {
          const refreshed = await writerFetch("/me/stripe/refresh", { method: "POST", signal: controller.signal });
          if (refreshed.ok) setStripe(await refreshed.json());
        }
      } catch {
        // Saving reports the problem if the backend is still unreachable then.
      }
    })();
    return () => controller.abort();
  }, []);

  /** Saves what's typed, so leaving for Stripe doesn't lose it. Returns false and shows why on failure. */
  async function saveDetails(): Promise<boolean> {
    const profile = await writerFetch("/me/profile", { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify({ name }) });
    if (!profile.ok) {
      setError(await errorMessage(profile));
      return false;
    }
    // On Base, Toll Gate holds earnings, so there is no address to save.
    if (onBase || !address.trim()) return true;
    const payout = await writerFetch("/me/payout", {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ payout_method: "xrpl", xrpl_address: address }),
    });
    if (!payout.ok) setError(await errorMessage(payout));
    return payout.ok;
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy("saving");
    setError("");
    try {
      if (await saveDetails()) {
        router.push("/dashboard");
        return;
      }
    } catch {
      setError(UNREACHABLE);
    }
    setBusy("");
  }

  async function connectStripe() {
    setBusy("stripe");
    setError("");
    try {
      if (await saveDetails()) {
        const response = await writerFetch("/me/stripe/onboarding", { method: "POST" });
        if (response.ok) {
          window.location.assign((await response.json()).url);
          return;
        }
        setError(await errorMessage(response));
      }
    } catch {
      setError(UNREACHABLE);
    }
    setBusy("");
  }

  return (
    <form className="stack" onSubmit={save}>
      <div className="field-group">
        <label htmlFor="name" className="label-muted">Your name, as agents will cite it</label>
        <input
          id="name"
          className="input input-large"
          type="text"
          maxLength={100}
          autoComplete="name"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </div>

      {onBase ? (
        <div className="field-group">
          <span className="label-muted">How you get paid</span>
          <div className="option option-card option-on">
            <span className="option-text">
              <span className="option-name">Toll Gate balance · {usd(balance)}</span>
              <span className="muted small">
                Agents pay in USDC on Base. Toll Gate holds it and credits you on every read. No wallet needed.
              </span>
            </span>
            <button type="button" className="button button-outline" disabled title="Withdrawals are coming soon">
              Withdraw · coming soon
            </button>
          </div>
        </div>
      ) : (
      <div className="field-group">
        <span className="label-muted">How you get paid · set up one or both</span>

        <div className={address.trim() ? "option option-card option-on" : "option option-card"}>
          <span className="option-text">
            <span className="option-name">XRP Ledger</span>
            <span className="muted small">Paid in XRP on every read</span>
          </span>
          <input
            id="addr"
            aria-label="XRP Ledger wallet address"
            className="input mono"
            type="text"
            placeholder="Wallet address (r…)"
            spellCheck={false}
            autoComplete="off"
            value={address}
            onChange={(event) => setAddress(event.target.value)}
          />
        </div>

        <div className={stripe?.connected ? "option option-card option-on" : "option option-card"}>
          <span className="option-text">
            <span className="option-name">Stripe</span>
            <span className="muted small">
              {stripe?.connected ? "Connected · paid in USD · test mode" : "Paid in USD to your bank · test mode"}
            </span>
          </span>
          {!stripe?.connected && (
            <button
              type="button"
              className="button button-outline"
              disabled={busy !== "" || !stripe?.available}
              title={stripe && !stripe.available ? "Stripe is not configured on this server" : undefined}
              onClick={connectStripe}
            >
              {busy === "stripe" ? "Opening Stripe…" : "Connect with Stripe"}
            </button>
          )}
        </div>
      </div>
      )}

      {error && <p className="error" role="alert">{error}</p>}

      <button type="submit" className="button button-large" disabled={busy !== ""}>
        {busy === "saving" ? "Saving…" : "Continue"}
      </button>
      <Link href="/dashboard" className="skip">Skip for now</Link>
    </form>
  );
}
