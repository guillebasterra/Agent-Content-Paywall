"use client";

import { useEffect, useState } from "react";
import { API_URL, count } from "@/lib/api";

type Scenario = {
  id: string;
  label: string;
  basis: string;
  source: string;
  agent_reads: number;
  earned_usd_micros: number;
};

type Estimate = {
  scenarios: Scenario[];
  assumes: string;
  price_guidance: {
    bazaar_content_median_usd: string;
    publisher_range_usd: string;
    premium_usd: string;
    catalog_median_usd: string | null;
    source: string;
  };
};

const PRICE = /^\d+(\.\d{1,6})?$/;
const MAX_READERS = 100_000_000;

/** Whole dollars from $10 up, cents below, so "$2,000" and "$3.16" both read at a glance. */
function perMonth(micros: number): string {
  const dollars = micros / 1_000_000;
  return dollars.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: dollars >= 10 ? 0 : 2,
  });
}

/** Earnings at this price for a writer with this many human readers, if agents read and pay. Numbers come from GET /estimate. */
export default function EarningsEstimate({ price }: { price: string }) {
  const [readers, setReaders] = useState("10000");
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [failed, setFailed] = useState(false);

  const monthly = Number(readers.replace(/[,\s]/g, ""));
  const valid = PRICE.test(price.trim()) && Number(price) > 0 && Number.isInteger(monthly) && monthly >= 0 && monthly <= MAX_READERS;

  useEffect(() => {
    if (!valid) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const query = new URLSearchParams({ price_usd: price.trim(), monthly_readers: String(monthly) });
        const response = await fetch(`${API_URL}/estimate?${query}`, { signal: controller.signal });
        if (!response.ok) throw new Error(String(response.status));
        setEstimate(await response.json());
        setFailed(false);
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [price, monthly, valid]);

  const guidance = estimate?.price_guidance;

  return (
    <section aria-labelledby="estimate-h" className="estimate">
      <h2 id="estimate-h" className="section-title">What this could earn</h2>

      <label className="estimate-readers">
        <span className="label-muted">People who read your work each month</span>
        <input
          className="input mono"
          type="text"
          inputMode="numeric"
          value={readers}
          onChange={(e) => setReaders(e.target.value)}
          aria-invalid={!Number.isInteger(monthly) || monthly < 0 || monthly > MAX_READERS}
        />
      </label>

      {!valid && <p className="muted small">Enter a price and a whole number of readers.</p>}
      {valid && failed && <p className="muted small">The estimate isn&apos;t available right now.</p>}

      {valid && estimate && (
        <>
          <ol className="estimate-rows">
            {estimate.scenarios.map((s) => (
              <li key={s.id} className={s.id === "parity" ? "estimate-row estimate-row-main" : "estimate-row"}>
                <span className="estimate-label">{s.label}</span>
                <span className="estimate-value">
                  {perMonth(s.earned_usd_micros)}
                  <span className="estimate-unit"> / month</span>
                </span>
                <span className="estimate-basis mono">
                  {count(s.agent_reads)} paid agent {s.agent_reads === 1 ? "read" : "reads"} a month
                </span>
              </li>
            ))}
          </ol>

          {guidance && (
            <p className="estimate-note mono">
              Publishers charge AI ${guidance.publisher_range_usd} a page. Paid content on the x402 Bazaar sells at a
              median ${guidance.bazaar_content_median_usd}.
              {guidance.catalog_median_usd && ` Toll Gate's median is $${guidance.catalog_median_usd}.`}
            </p>
          )}

          <details className="estimate-how">
            <summary className="estimate-note mono">How this is estimated</summary>
            <ul className="estimate-sources">
              <li className="estimate-note mono">{estimate.assumes}</li>
              {estimate.scenarios.map((s) => (
                <li key={s.id} className="estimate-note mono">
                  <span className="estimate-source-label">{s.label}.</span> {s.basis}. {s.source}.
                </li>
              ))}
              {guidance && <li className="estimate-note mono">Prices: {guidance.source}.</li>}
            </ul>
          </details>
        </>
      )}
    </section>
  );
}
