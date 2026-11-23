"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";

type Draft = {
  title: string;
  body: string;
  summary: string;
  price_usd: string;
  article_id: string | null;
};

export default function Review({ source }: { source: string }) {
  const query = "?source=" + encodeURIComponent(source);
  const url = "/api/discord-review/draft" + query;
  const [draft, setDraft] = useState<Draft | null>(null);
  const [login, setLogin] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    async function load() {
      const res = await fetch(url, { cache: "no-store" });
      const data = await res.json();
      if (!active) return;
      if (res.status === 401) setLogin(true);
      else if (res.ok) setDraft(data);
      else
        setError(
          typeof data.detail === "string" ? data.detail : "Cannot open draft.",
        );
    }
    load().catch(() => {
      if (active) setError("Cannot load draft.");
    });
    return () => {
      active = false;
    };
  }, [url]);
  async function publish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft) return;
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          summary: form.get("summary"),
          price_usd: form.get("price"),
          confirm_rights: form.has("rights"),
        }),
      });
      const data = await res.json();
      if (res.status === 401) setLogin(true);
      if (!res.ok)
        throw new Error(
          typeof data.detail === "string" ? data.detail : "Publication failed.",
        );
      setDraft({ ...draft, article_id: data.article_id });
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Check the draft before retrying.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="screen">
      <section className="pieces">
        <h1>{draft?.title ?? "Review AMA"}</h1>
        {login && (
          <a href={"/api/discord-review/start" + query}>
            Sign in with Discord to review
          </a>
        )}
        {error && <p role="alert">{error}</p>}
        {!draft && !login && !error && <p>Loading draft…</p>}
        {draft?.article_id ? (
          <p>
            Published.{" "}
            <Link href={"/dashboard/sales/" + draft.article_id}>
              View writer sales
            </Link>
          </p>
        ) : (
          draft && (
            <form onSubmit={publish}>
              <label>
                Public abstract
                <textarea
                  name="summary"
                  defaultValue={draft.summary}
                  maxLength={2000}
                  required
                />
              </label>
              <h2>Paid text</h2>
              <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                {draft.body}
              </pre>
              <label>
                USD per read{" "}
                <input
                  type="number"
                  name="price"
                  min="0.000001"
                  step="0.000001"
                  defaultValue={draft.price_usd}
                  required
                />
              </label>
              <p>Abstract only · AI input · No training</p>
              <label>
                <input type="checkbox" name="rights" required /> I have
                permission to publish this version.
              </label>
              <button disabled={busy || login}>Confirm publication</button>
            </form>
          )
        )}
      </section>
    </main>
  );
}
