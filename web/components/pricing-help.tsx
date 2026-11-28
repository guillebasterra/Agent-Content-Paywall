"use client";

import { useEffect, useState } from "react";
import { API_URL, count } from "@/lib/api";

type Estimate = {
  monthly_readers: number;
  price_usd: string;
  agent_reads: number;
  earned_usd_micros: number;
  suggested: { price_usd: string; earned_usd_micros: number };
  how: string[];
};

const PRICE = /^\d+(\.\d{1,6})?$/;
const MAX_READERS = 100_000_000;
const MARKET_TOP_USD = 0.1; // the top of what publishers charge AI per page

/** Whole dollars from $10 up, cents below. */
function perMonth(micros: number): string {
  const dollars = micros / 1_000_000;
  return dollars.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: dollars >= 10 ? 0 : 2 });
}

/**
 * Sits under the price field: what this price brings in a month for an audience this size,
 * and a suggested price the writer can apply. Numbers come from GET /estimate.
 */
export default function PricingHelp({ price, onUsePrice }: { price: string; onUsePrice: (price: string) => void }) {
  const [readers, setReaders] = useState("10,000");
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [failed, setFailed] = useState(false);

  const monthly = Number(readers.replace(/[,\s]/g, ""));
  const readersOk = readers.trim() !== "" && Number.isInteger(monthly) && monthly >= 0 && monthly <= MAX_READERS;
  const priceOk = PRICE.test(price.trim()) && Number(price) > 0;

  useEffect(() => {
    if (!readersOk || !priceOk) return;
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
  }, [price, monthly, readersOk, priceOk]);

  const current = readersOk && priceOk && estimate ? estimate : null;
  const onSuggested = current && Number(current.suggested.price_usd) === Number(price);

  return (
    <section className="pricing-help" aria-label="Monthly earnings at this price">
      <div className="pricing-help-title">
        <label htmlFor="readers">If</label>
        <input
          id="readers"
          className="pricing-help-readers mono"
          type="text"
          inputMode="numeric"
          value={readers}
          onChange={(e) => setReaders(e.target.value)}
          aria-invalid={!readersOk}
        />
        <span>people read your work each month</span>
      </div>

      {!readersOk && <p className="muted small">Enter how many people read your work each month, as a whole number.</p>}
      {readersOk && !priceOk && <p className="muted small">Enter a price to see what it brings in.</p>}
      {failed && readersOk && priceOk && <p className="muted small">The estimate isn&apos;t available right now.</p>}

      {current && (
        <>
          <p className="pricing-help-line">
            and AI agents read it as often, that&apos;s {count(current.agent_reads)} paid AI{" "}
            {current.agent_reads === 1 ? "read" : "reads"}. At ${current.price_usd} each, you&apos;d make about{" "}
            <strong className="pricing-help-amount">{perMonth(current.earned_usd_micros)}</strong> a month.
          </p>
          {Number(price) > MARKET_TOP_USD && (
            <p className="muted small">
              That&apos;s above what publishers usually charge AI ($0.001–$0.10 a page), so fewer agents may buy.
            </p>
          )}
          {onSuggested ? (
            <p className="muted small">This is the suggested price for an audience this size.</p>
          ) : (
            <p className="pricing-help-line">
              Suggested for this audience: <strong>${current.suggested.price_usd}</strong> a read, about{" "}
              {perMonth(current.suggested.earned_usd_micros)} a month.{" "}
              <button type="button" className="link-button" onClick={() => onUsePrice(current.suggested.price_usd)}>
                Use ${current.suggested.price_usd}
              </button>
            </p>
          )}
          <details className="pricing-help-how">
            <summary>How this is estimated</summary>
            <ul>
              {current.how.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </details>
        </>
      )}
    </section>
  );
}
