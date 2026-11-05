"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { type Dashboard, USD_PER_XRP, count, reads, shortAddress, timeAgo, txUrl, usd } from "@/lib/api";
import { writerFetch } from "@/lib/api-client";
import { setPendingUpload } from "@/lib/pending-upload";

const POLL_MS = 3000;

function UploadDrop() {
  const router = useRouter();
  const [dragging, setDragging] = useState(false);

  function upload(file: File | null | undefined) {
    if (!file) return;
    setPendingUpload(file);
    router.push("/upload");
  }

  return (
    <section aria-label="Upload a new piece" className="upload-drop">
      <input
        id="new-piece"
        className="visually-hidden"
        type="file"
        accept=".md,.txt"
        onChange={(event) => upload(event.target.files?.[0])}
      />
      <label
        htmlFor="new-piece"
        className={dragging ? "dropzone dropzone-large dropzone-active" : "dropzone dropzone-large"}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          upload(event.dataTransfer.files[0]);
        }}
      >
        <span className="dropzone-title">Upload a new piece</span>
        <span className="muted">Drop a file here, or</span>
        <span className="button">Choose a file</span>
        <span className="muted small">.md · .txt</span>
      </label>
    </section>
  );
}

export default function DashboardView() {
  const router = useRouter();
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
        const response = await writerFetch("/me/dashboard", { cache: "no-store", signal: controller.signal });
        if (response.status === 401) {
          router.replace("/signin");
          return;
        }
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
  }, [router]);

  if (!data) {
    return (
      <main className="page">
        {failed ? <p className="error" role="alert">The backend can't be reached. Start it with make server.</p> : <p className="muted">Loading…</p>}
      </main>
    );
  }

  return (
    <main className="page page-dashboard">
      {failed && <p className="error" role="alert">Connection lost. Showing the last data received.</p>}

      <div className="overview">
        <div className="stats">
          <section aria-label="Pieces on the site" className="stat">
            <span className="muted">Pieces on the site</span>
            <span className="stat-value">{count(data.pieces.length)}</span>
            <span className="muted small">{reads(data.totals.reads)}</span>
          </section>
          <section aria-label="Earned" className="stat">
            <span className="muted">Earned</span>
            <span className="stat-value">{usd(data.totals.earned_drops)}</span>
            {data.latest && (
              <a key={data.latest.tx_hash} className="latest" href={txUrl(data.latest.tx_hash)} target="_blank" rel="noreferrer">
                <span className="latest-dot" aria-hidden="true" />
                +{usd(data.latest.price_drops)} {now ? timeAgo(data.latest.created_at, now) : ""}
              </a>
            )}
          </section>
        </div>
        <UploadDrop />
      </div>

      <section aria-labelledby="pieces-h" className="pieces">
        <h2 id="pieces-h" className="section-title">Your pieces</h2>
        {data.pieces.length === 0 ? (
          <p className="muted">Nothing here yet. Pieces you upload will show up here.</p>
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
                    <td className="number muted">{usd(piece.price_drops)}</td>
                    <td className="number">{count(piece.reads)}</td>
                    <td className="number strong">{usd(piece.earned_drops)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="dashboard-note muted small">
        <Link href="/onboarding/payout">
          {data.payout.xrpl_address
            ? <>Payout: XRPL <span className="mono">{shortAddress(data.payout.xrpl_address)}</span></>
            : "Add a payout method"}
        </Link>
        <span>Dollar amounts are estimates at 1 XRP = ${USD_PER_XRP}</span>
      </p>
    </main>
  );
}
