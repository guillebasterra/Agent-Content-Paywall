"""Article text helpers: seeding from content/*.md, uploads and free previews."""

import hashlib
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import frontmatter

DROPS_PER_XRP = 1_000_000
MAX_DROPS = 100_000_000_000 * DROPS_PER_XRP  # All the XRP there is.
DEFAULT_PREVIEW = "w50"


def to_drops(xrp: object) -> int:
    """Whole, positive drops, or ValueError. Nothing is rounded, so prices stay exact."""
    try:
        drops = Decimal(str(xrp).strip()) * DROPS_PER_XRP
    except InvalidOperation:
        raise ValueError("not a number") from None
    if not drops.is_finite() or drops <= 0 or drops > MAX_DROPS or drops != drops.to_integral_value():
        raise ValueError("must be a positive XRP amount with at most 6 decimals")
    return int(drops)


def to_xrp(drops: int) -> str:
    return format((Decimal(drops) / DROPS_PER_XRP).normalize(), "f")


def content_hash(body: str) -> str:
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80].strip("-") or "article"


def preview_text(body: str, mode: str) -> str:
    """The free part of an article. It is never more than half, so short pieces stay paid."""
    if mode == "none":
        return ""
    # Cut at a word's end within the original text, so paragraph breaks survive.
    ends = [m.end() for m in re.finditer(r"\S+", body)]
    wanted = {"w50": 50, "w100": 100, "p10": max(1, len(ends) // 10)}[mode]
    count = min(wanted, len(ends) // 2)
    return body[: ends[count - 1]] if count else ""


def seed_articles(content_dir: Path, writer_id: str) -> list[dict]:
    """Rows for content/*.md. Every seeded article belongs to the given writer."""
    rows = []
    for path in sorted(content_dir.glob("*.md")):
        if path.name.startswith("_") or path.name == "README.md":
            continue
        post = frontmatter.load(path)
        meta = post.metadata
        rows.append({
            "id": str(meta.get("id") or path.stem),
            "writer_id": writer_id,
            "title": str(meta["title"]),
            "abstract": str(meta.get("abstract", "")),
            "body": post.content.strip(),
            "preview_mode": str(meta.get("preview_mode", DEFAULT_PREVIEW)),
            "keywords": [str(k) for k in meta.get("keywords", meta.get("tags", []))],
            "price_drops": to_drops(meta.get("price_xrp", "0.5")),
            "license": str(meta.get("license", "ai-input")),
            "train_price_drops": to_drops(meta["train_price_xrp"]) if meta.get("train_price_xrp") else None,
            "allowed_agents": [str(a) for a in meta.get("allowed_agents", ["*"])],
        })
    return rows
