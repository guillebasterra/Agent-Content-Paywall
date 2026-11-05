"""Article text helpers: seeding from content/*.md, uploads, free previews and money conversions.

Money is integer micro-dollars and integer drops. Floats never touch it.
"""

import hashlib
import re
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path

import frontmatter

DROPS_PER_XRP = 1_000_000
DEFAULT_PREVIEW = "w50"
MICROS_PER_USD = 1_000_000
MAX_MICROS = 1_000_000 * MICROS_PER_USD


def to_xrp(drops: int) -> str:
    return format((Decimal(drops) / DROPS_PER_XRP).normalize(), "f")


def to_micros(usd: object) -> int:
    """Whole, positive micro-dollars, or ValueError. Nothing is rounded, so prices stay exact."""
    try:
        micros = Decimal(str(usd).strip()) * MICROS_PER_USD
    except InvalidOperation:
        raise ValueError("not a number") from None
    if not micros.is_finite() or micros <= 0 or micros > MAX_MICROS or micros != micros.to_integral_value():
        raise ValueError("must be a positive dollar amount with at most 6 decimals")
    return int(micros)


def format_usd(micros: int) -> str:
    """Dollars as text, with cents always shown and sub-cent digits only when they exist."""
    value = Decimal(micros) / MICROS_PER_USD
    text = format(value.quantize(Decimal("0.000001")), "f").rstrip("0")
    whole, _, decimals = text.partition(".")
    return f"{whole}.{decimals.ljust(2, '0')}"


def usd_to_drops(micros: int, rate: Decimal) -> int:
    """Drops to invoice for a USD price. Rounded up, so a writer is never paid under the price."""
    return max(1, int((Decimal(micros) / rate).to_integral_value(rounding=ROUND_CEILING)))


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


def _seed_price(meta: dict, usd_key: str, xrp_key: str, rate: Decimal, default: str | None = None) -> int | None:
    if meta.get(usd_key):
        return to_micros(meta[usd_key])
    if meta.get(xrp_key):
        return to_micros(Decimal(str(meta[xrp_key])) * rate)  # Files written when prices were in XRP.
    return to_micros(default) if default else None


def seed_articles(content_dir: Path, writer_id: str, rate: Decimal) -> list[dict]:
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
            "price_usd_micros": _seed_price(meta, "price_usd", "price_xrp", rate, default="0.40"),
            "license": str(meta.get("license", "ai-input")),
            "train_price_usd_micros": _seed_price(meta, "train_price_usd", "train_price_xrp", rate),
            "allowed_agents": [str(a) for a in meta.get("allowed_agents", ["*"])],
        })
    return rows
