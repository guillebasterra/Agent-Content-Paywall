import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import Logo from "@/components/logo";
import { API_URL, type Article, BLURRED_FILLER, reads, xrp } from "@/lib/api";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

/** GET /articles/{id} is the paywalled text, so the free view comes from the catalog. */
async function loadArticle(id: string): Promise<Article | null | "unavailable"> {
  try {
    const response = await fetch(`${API_URL}/catalog`, { cache: "no-store" });
    if (!response.ok) return "unavailable";
    const { articles }: { articles: Article[] } = await response.json();
    return articles.find((article) => article.id === id) ?? null;
  } catch {
    return "unavailable";
  }
}

function terms(article: Article): string {
  const parts = ["Agents only"];
  parts.push(article.license === "ai-train" ? `read, cite and train · training ${article.train_price_xrp} XRP flat` : "read and cite · not for training");
  if (!article.allowed_agents.includes("*")) parts.push(`sold to ${article.allowed_agents.join(", ")}`);
  return parts.join(" · ");
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const article = await loadArticle((await params).id);
  return { title: article && article !== "unavailable" ? article.title : "Article" };
}

export default async function ArticlePage({ params }: Props) {
  const article = await loadArticle((await params).id);
  if (article === null) notFound();

  return (
    <div className="screen">
      <header className="header">
        <Link href="/catalog" className="back">← Catalog</Link>
        <Logo />
      </header>
      {article === "unavailable" ? (
        <main className="page article">
          <p className="error" role="alert">The catalog can't be reached. Start the backend with make server.</p>
        </main>
      ) : (
        <main className="page article">
          <span className="muted">{article.author} · {reads(article.reads)} · {xrp(article.earned_drops)} earned</span>
          <h1 className="article-title">{article.title}</h1>
          <p className="article-clear">{article.preview || article.abstract}</p>
          <p className="article-clear article-blurred" aria-hidden="true">{BLURRED_FILLER}</p>
          <p className="article-clear article-blurred" aria-hidden="true">{BLURRED_FILLER}</p>
          <section aria-label="Access" className="access">
            <span className="access-terms">
              <span className="access-price">{xrp(article.price_drops)} per read</span>
              <span className="muted small">{terms(article)}</span>
            </span>
            <code className="access-code">GET /articles/{article.id}</code>
          </section>
        </main>
      )}
    </div>
  );
}
