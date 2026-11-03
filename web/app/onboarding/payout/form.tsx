"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { API_URL, errorMessage } from "@/lib/api";

export default function PayoutForm() {
  const router = useRouter();
  const [method, setMethod] = useState<"stripe" | "xrpl">("xrpl");
  const [address, setAddress] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_URL}/me/payout`, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then((payout) => {
        // Keep anything typed while this was loading.
        if (payout?.xrpl_address) setAddress((typed) => typed || payout.xrpl_address);
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (method !== "xrpl") return;
    setSaving(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/me/payout`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payout_method: "xrpl", xrpl_address: address }),
      });
      if (response.ok) {
        router.push("/dashboard");
        return;
      }
      setError(await errorMessage(response));
    } catch {
      setError("The backend can't be reached. Start it with make server.");
    }
    setSaving(false);
  }

  return (
    <form className="stack" onSubmit={save}>
      <fieldset className="field-group">
        <legend className="visually-hidden">Payout method</legend>

        <label className={method === "stripe" ? "option option-on" : "option"}>
          <input type="radio" name="payout" checked={method === "stripe"} onChange={() => setMethod("stripe")} />
          <span className="option-text">
            <span className="option-name">Stripe</span>
            <span className="muted small">Bank account · USD · paid out daily</span>
          </span>
        </label>
        {method === "stripe" && (
          <button type="button" className="button button-large" disabled title="Coming soon">Connect with Stripe</button>
        )}

        <label className={method === "xrpl" ? "option option-on" : "option"}>
          <input type="radio" name="payout" checked={method === "xrpl"} onChange={() => setMethod("xrpl")} />
          <span className="option-text">
            <span className="option-name">XRP Ledger</span>
            <span className="muted small">Wallet address · XRP · paid on every read</span>
          </span>
        </label>
        {method === "xrpl" && (
          <div className="field-group">
            <label htmlFor="addr" className="label-muted">Wallet address</label>
            <input
              id="addr"
              className="input input-large mono"
              type="text"
              placeholder="r…"
              spellCheck={false}
              autoComplete="off"
              value={address}
              onChange={(event) => setAddress(event.target.value)}
            />
            <button type="button" className="button button-outline button-large" disabled title="Coming soon">
              Connect Xaman instead
            </button>
          </div>
        )}
      </fieldset>

      {error && <p className="error" role="alert">{error}</p>}

      <button type="submit" className="button button-large" disabled={saving || method !== "xrpl"}>
        {saving ? "Saving…" : "Continue"}
      </button>
      <Link href="/dashboard" className="skip">Skip for now</Link>
    </form>
  );
}
