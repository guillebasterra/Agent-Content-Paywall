"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import Tile from "@/components/tile";
import { XRP_USD_RATE, count, errorMessage } from "@/lib/api";
import { writerFetch } from "@/lib/api-client";
import { takePendingUpload } from "@/lib/pending-upload";

const PREVIEWS = [
  { id: "none", name: "Abstract only" },
  { id: "w50", name: "First 50 words" },
  { id: "w100", name: "First 100 words" },
  { id: "p10", name: "First 10%" },
] as const;
type PreviewMode = (typeof PREVIEWS)[number]["id"];

const AGENTS = ["ChatGPT", "Claude", "Muse", "Perplexity"];
const TRAINING_PRICE_USD = "50";
const READABLE = /\.(md|txt)$/i;
const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/;

/** Same rule as preview_text in server/app/content.py, so this tile matches the catalog. */
function previewOf(body: string, mode: PreviewMode): string {
  if (mode === "none") return "";
  const ends = [...body.matchAll(/\S+/g)].map((match) => match.index + match[0].length);
  const wanted = mode === "w50" ? 50 : mode === "w100" ? 100 : Math.max(1, Math.floor(ends.length / 10));
  const words = Math.min(wanted, Math.floor(ends.length / 2));
  return words ? body.slice(0, ends[words - 1]) : "";
}

/** One frontmatter value, without quotes. Lists may be inline ([a, b]) or one "- item" per line. */
function metaValue(meta: string, key: string): string {
  return meta.match(new RegExp(`^${key}:[ \\t]*["']?(.*?)["']?[ \\t]*$`, "m"))?.[1] ?? "";
}

function metaList(meta: string, ...keys: string[]): string[] {
  for (const key of keys) {
    const inline = metaValue(meta, key).replace(/^\[|\]$/g, "");
    if (inline) return inline.split(",").map((k) => k.trim().replace(/^["']|["']$/g, "")).filter(Boolean);
    const block = meta.match(new RegExp(`^${key}:\\s*\\n((?:\\s*-\\s*.+\\n?)+)`, "m"))?.[1];
    if (block) return [...block.matchAll(/-\s*(.+)/g)].map((m) => m[1].trim());
  }
  return [];
}

/** A starting abstract when the file has none: the opening sentence, without markdown headings. */
function firstSentence(body: string): string {
  const text = body.replace(/^#.*$/gm, "").trim().split(/\n\s*\n/)[0] ?? "";
  const sentence = text.match(/^.+?[.!?](?=\s|$)/s)?.[0] ?? text;
  return sentence.replace(/\s+/g, " ").slice(0, 240);
}

const titleFromFilename = (name: string) => name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").trim();

export default function UploadForm({ author }: { author: string }) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [body, setBody] = useState("");
  const [title, setTitle] = useState("");
  const [abstract, setAbstract] = useState("");
  const [preview, setPreview] = useState<PreviewMode>("w50");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [keyword, setKeyword] = useState("");
  const [price, setPrice] = useState("0.40");
  const [license, setLicense] = useState<"ai-input" | "ai-train">("ai-input");
  const [allAgents, setAllAgents] = useState(true);
  const [agents, setAgents] = useState<string[]>(AGENTS);
  const [error, setError] = useState("");
  const [publishing, setPublishing] = useState(false);

  async function chooseFile(chosen: File | null | undefined) {
    if (!chosen) return;
    setFile(chosen);
    setError("");
    const readable = READABLE.test(chosen.name);
    let text = readable ? await chosen.text() : "";
    const meta = text.match(FRONTMATTER)?.[1] ?? "";
    text = text.replace(FRONTMATTER, "").trim();
    setBody(text);
    if (!title) setTitle(metaValue(meta, "title") || text.match(/^#\s+(.+)$/m)?.[1] || titleFromFilename(chosen.name));
    if (!abstract) setAbstract(metaValue(meta, "abstract") || firstSentence(text));
    if (keywords.length === 0) setKeywords(metaList(meta, "keywords", "tags"));
    const metaPrice = metaValue(meta, "price_usd");
    if (metaPrice) setPrice(metaPrice);
    if (!readable) setError("Only .md and .txt files can be uploaded for now.");
  }

  useEffect(() => {
    chooseFile(takePendingUpload());
    // Runs once, for a file dropped on the dashboard.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function addKeywords(raw: string) {
    const added = raw.split(",").map((k) => k.trim()).filter(Boolean);
    setKeywords((current) => [...new Set([...current, ...added])]);
    setKeyword("");
  }

  function toggleAgent(agent: string, checked: boolean) {
    const next = checked ? [...agents, agent] : agents.filter((a) => a !== agent);
    setAgents(next);
    setAllAgents(next.length === AGENTS.length);
  }

  async function publish(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Choose a file to upload.");
      return;
    }
    setPublishing(true);
    setError("");
    const form = new FormData();
    form.set("file", file);
    form.set("title", title);
    form.set("abstract", abstract);
    form.set("preview_mode", preview);
    form.set("keywords", [...keywords, keyword].map((k) => k.trim()).filter(Boolean).join(","));
    form.set("price_usd", price);
    form.set("license", license);
    if (license === "ai-train") form.set("train_price_usd", TRAINING_PRICE_USD);
    form.set("allowed_agents", allAgents ? "*" : agents.join(","));
    try {
      const response = await writerFetch("/articles", { method: "POST", body: form });
      if (response.ok) {
        router.push("/dashboard");
        return;
      }
      setError(await errorMessage(response));
    } catch {
      setError("The backend can't be reached. Start it with make server.");
    }
    setPublishing(false);
  }

  const words = body ? body.split(/\s+/).length : 0;
  const priceXrp = Number(price) > 0 ? (Number(price) / XRP_USD_RATE).toLocaleString("en-US", { maximumFractionDigits: 6 }) : "";

  return (
    <div className="screen">
      <header className="header">
        <Link href="/dashboard" className="back">← Dashboard</Link>
        <button type="submit" form="upload" className="button" disabled={publishing}>
          {publishing ? "Publishing…" : "Publish"}
        </button>
      </header>

      <main className="page upload">
        <form id="upload" className="upload-form" onSubmit={publish}>
          <h1>Upload</h1>
          {error && <p className="error" role="alert">{error}</p>}

          <div className="field">
            <span className="label" id="file-label">File</span>
            <input
              ref={input}
              id="file"
              className="visually-hidden"
              type="file"
              accept=".md,.txt"
              aria-labelledby="file-label"
              onChange={(event) => chooseFile(event.target.files?.[0])}
            />
            <label
              htmlFor="file"
              className="dropzone"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                chooseFile(event.dataTransfer.files[0]);
              }}
            >
              <span>Drop a file or <span className="underline">browse</span></span>
              <span className="muted small">.md · .txt</span>
            </label>
            {file && (
              <div className="file-chip">
                <span className="mono">{file.name}</span>
                {words > 0 && <span className="muted">{count(words)} words</span>}
              </div>
            )}
          </div>

          <div className="field">
            <label htmlFor="title" className="label">Title</label>
            <input id="title" className="input" type="text" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>

          <div className="field">
            <label htmlFor="abstract" className="label">Abstract</label>
            <textarea
              id="abstract"
              className="input textarea"
              placeholder="One or two sentences. Always free."
              value={abstract}
              onChange={(e) => setAbstract(e.target.value)}
            />
          </div>

          <fieldset className="field">
            <legend className="label legend">Free preview</legend>
            <div className="pills">
              {PREVIEWS.map((option) => (
                <label key={option.id} className={preview === option.id ? "pill pill-on" : "pill"}>
                  <input
                    className="visually-hidden"
                    type="radio"
                    name="preview"
                    checked={preview === option.id}
                    onChange={() => setPreview(option.id)}
                  />
                  {option.name}
                </label>
              ))}
            </div>
          </fieldset>

          <div className="field">
            <label htmlFor="kw" className="label">Keywords</label>
            <div className="keywords">
              {keywords.map((k) => (
                <span key={k} className="keyword">
                  {k}
                  <button
                    type="button"
                    aria-label={`Remove keyword ${k}`}
                    onClick={() => setKeywords(keywords.filter((other) => other !== k))}
                  >×</button>
                </span>
              ))}
              <input
                id="kw"
                type="text"
                placeholder="Add keyword"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onBlur={() => keyword.trim() && addKeywords(keyword)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === ",") {
                    e.preventDefault();
                    if (keyword.trim()) addKeywords(keyword);
                  }
                }}
              />
            </div>
          </div>

          <div className="field-row">
            <div className="field">
              <label htmlFor="price" className="label">Price per read</label>
              <div className="input input-affix">
                <span className="muted">$</span>
                <input id="price" type="text" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
              </div>
              {priceXrp && <span className="muted small">≈ {priceXrp} XRP on the XRP Ledger</span>}
            </div>
            <div className="field">
              <label htmlFor="train" className="label">Training license</label>
              <select
                id="train"
                className="input"
                value={license}
                onChange={(e) => setLicense(e.target.value as "ai-input" | "ai-train")}
              >
                <option value="ai-input">Not for training</option>
                <option value="ai-train">Allow training · ${TRAINING_PRICE_USD} flat</option>
              </select>
            </div>
          </div>

          <fieldset className="field">
            <legend className="label legend">Agents that can buy</legend>
            <div className="checks">
              <label className="check">
                <input
                  type="checkbox"
                  checked={allAgents}
                  onChange={(e) => {
                    setAllAgents(e.target.checked);
                    setAgents(e.target.checked ? AGENTS : []);
                  }}
                />
                All agents
              </label>
              {AGENTS.map((agent) => (
                <label key={agent} className="check">
                  <input type="checkbox" checked={agents.includes(agent)} onChange={(e) => toggleAgent(agent, e.target.checked)} />
                  {agent}
                </label>
              ))}
            </div>
          </fieldset>
        </form>

        <aside aria-labelledby="pv-h" className="upload-preview">
          <h2 id="pv-h" className="section-title">In the catalog</h2>
          <div className="tile">
            <Tile title={title || "Title"} clear={previewOf(body, preview) || abstract}>
              <span className="tile-row">
                <span className="strong">{author}</span>
                <span className="muted">${price} / read</span>
              </span>
            </Tile>
          </div>
        </aside>
      </main>
    </div>
  );
}
