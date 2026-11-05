"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Tile from "@/components/tile";
import { API_URL, type Article, reads, usd } from "@/lib/api";

const SEARCH_DELAY_MS = 250;

export default function CatalogView() {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("reads");
  const [articles, setArticles] = useState<Article[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const params = new URLSearchParams({ sort });
        if (query.trim()) params.set("q", query.trim());
        const response = await fetch(`${API_URL}/catalog?${params}`, { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        setArticles(data.articles);
        setFailed(false);
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    }, SEARCH_DELAY_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, sort]);

  return (
    <main className="page">
      <div className="catalog-head">
        <h1>Catalog</h1>
        <div className="catalog-controls">
          <label htmlFor="q" className="visually-hidden">Search</label>
          <input id="q" className="input input-pill" type="search" placeholder="Search" value={query} onChange={(e) => setQuery(e.target.value)} />
          <label htmlFor="sort" className="visually-hidden">Sort</label>
          <select id="sort" className="input input-pill" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="reads">Most read</option>
            <option value="earned">Most earned</option>
            <option value="new">Newest</option>
          </select>
        </div>
      </div>

      {failed && <p className="error" role="alert">The catalog can't be reached. Start the backend with make server.</p>}
      {articles?.length === 0 && <p className="muted">{query.trim() ? "No articles match that search." : "No articles yet."}</p>}

      <div className="tiles">
        {articles?.map((article) => (
          <Link key={article.id} href={`/articles/${encodeURIComponent(article.id)}`} className="tile">
            <Tile title={article.title} clear={article.preview || article.abstract}>
              <span className="strong">{article.author}</span>
              <span className="tile-row muted">
                <span>{usd(article.earned_usd_micros)} earned</span>
                <span>{reads(article.reads)}</span>
              </span>
            </Tile>
          </Link>
        ))}
      </div>
    </main>
  );
}
