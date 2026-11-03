"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { API_URL, type Dashboard, count, reads, shortAddress, timeAgo, txUrl, xrp } from "@/lib/api";

const POLL_MS = 3000;

export default function DashboardView() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [failed, setFailed] = useState(false);
  const [now, setNow] = useState(0);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();

    // Each poll schedules the next, so a slow backend can never stack up requests.
    async function poll() {
      try {
        const response = await fetch(`${API_URL}/me/dashboard`, { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const next: Dashboard = await response.json();
        if (stopped) return;
        setData(next);
        setFailed(false);
      } catch {
        if (!stopped) setFailed(true);
      }
      if (!stopped) {
        setNow(Date.now());
        timer = setTimeout(poll, POLL_MS);
      }
    }

    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, []);

  if (!data) {
    return (
      <main className="page">
        {failed ? <p className="error" role="alert">The backend can't be reached. Start it with make server.</p> : <p className="muted">Loading…</p>}
      </main>
    );
  }

  const topAgent = data.by_agent[0]?.earned_drops ?? 0;

  return (
    <main className="page page-dashboard">
      {failed && <p className="error" role="alert">Connection lost. Showing the last data received.</p>}

      <section aria-label="Earnings" className="earnings">
        <span className="muted">Total earned</span>
        <span className="total">{xrp(data.totals.earned_drops)}</span>
        <div className="earnings-meta">
          {data.latest && (
            <a key={data.latest.tx_hash} className="latest" href={txUrl(data.latest.tx_hash)} target="_blank" rel="noreferrer">
              <span className="latest-dot" aria-hidden="true" />
              +{xrp(data.latest.price_drops)} {now ? timeAgo(data.latest.created_at, now) : ""}
            </a>
          )}
          <span>{xrp(data.totals.month_drops)} this month</span>
          <span>{reads(data.totals.reads)}</span>
          <Link href="/onboarding/payout">
            {data.payout.xrpl_address
              ? <>Payout: XRPL <span className="mono">{shortAddress(data.payout.xrpl_address)}</span></>
              : "Add a payout method"}
          </Link>
        </div>
      </section>

      <div className="dashboard-columns">
        <section aria-labelledby="pieces-h" className="pieces">
          <h2 id="pieces-h" className="section-title">Your pieces</h2>
          {data.pieces.length === 0 ? (
            <p className="muted">No pieces yet. <Link href="/upload">Upload one</Link></p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Piece</th>
                    <th scope="col">Agents</th>
                    <th scope="col" className="number">Per read</th>
                    <th scope="col" className="number">Reads</th>
                    <th scope="col" className="number">Earned</th>
                  </tr>
                </thead>
                <tbody>
                  {data.pieces.map((piece) => (
                    <tr key={piece.id}>
                      <td className="piece-title"><Link href={`/articles/${encodeURIComponent(piece.id)}`}>{piece.title}</Link></td>
                      <td>
                        <span className="chips">
                          {piece.agents.map((agent) => <span key={agent} className="chip">{agent}</span>)}
                        </span>
                      </td>
                      <td className="number muted">{xrp(piece.price_drops)}</td>
                      <td className="number">{count(piece.reads)}</td>
                      <td className="number strong">{xrp(piece.earned_drops)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section aria-labelledby="agents-h" className="agents">
          <h2 id="agents-h" className="section-title">By agent</h2>
          {data.by_agent.length === 0 && <p className="muted">No agent has bought a read yet.</p>}
          {data.by_agent.map((agent) => (
            <div key={agent.name} className="agent">
              <div className="agent-row">
                <span>{agent.name}</span>
                <span className="strong">{xrp(agent.earned_drops)}</span>
              </div>
              <div className="bar" role="img" aria-label={`${agent.name} paid ${xrp(agent.earned_drops)}`}>
                <div style={{ width: `${Math.round((agent.earned_drops / topAgent) * 100)}%` }} />
              </div>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
