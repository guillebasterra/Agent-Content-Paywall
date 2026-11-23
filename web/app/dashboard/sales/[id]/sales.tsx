"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { type Read, usd, txUrl } from "@/lib/api";
import { writerFetch } from "@/lib/api-client";

type Data = {
  title: string;
  reads: number;
  earned_usd_micros: number;
  recent: (Read & { receipt: string })[];
};

export default function Sales({ id }: { id: string }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const res = await writerFetch(
          "/me/discord/sales/" + encodeURIComponent(id),
          { signal: controller.signal },
        );
        if (!res.ok)
          throw new Error(
            "Sales unavailable. Sign in with the publishing writer account.",
          );
        setData(await res.json());
      } catch (cause) {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error ? cause.message : "Could not load sales.",
          );
      }
    }
    setData(null);
    setError("");
    void load();
    return () => controller.abort();
  }, [id]);
  return (
    <section className="pieces">
      <Link href="/dashboard">Back to dashboard</Link>
      <h1>{data?.title ?? "Article sales"}</h1>
      {error && <p role="alert">{error}</p>}
      {!error && !data && <p>Loading sales…</p>}
      {data && (
        <>
          <p>
            {data.reads} paid reads · {usd(data.earned_usd_micros)} net earned
          </p>
          {!data.recent.length ? (
            <p>No sales yet.</p>
          ) : (
            <>
              <h2>Latest 50 transactions</h2>
              <ul>
                {data.recent.map((row) => {
                  const url = txUrl(row);
                  return (
                    <li key={row.tx_hash}>
                      <time>{row.created_at}</time> ·{" "}
                      {usd(row.amount_usd_micros)} paid ·{" "}
                      {usd(row.amount_usd_micros - row.fee_usd_micros)} net
                      {url && (
                        <>
                          {" "}
                          · <a href={url}>Transaction</a>
                        </>
                      )}
                      <details>
                        <summary>Signed receipt</summary>
                        <code style={{ overflowWrap: "anywhere" }}>
                          {row.receipt}
                        </code>
                      </details>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}
