"""Load articles from content/*.md (YAML frontmatter + Markdown body)."""

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import frontmatter

DROPS_PER_XRP = 1_000_000


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    author: str
    abstract: str
    price_xrp: Decimal
    license: str
    pay_to: str
    body: str
    tags: list[str] = field(default_factory=list)

    @property
    def price_drops(self) -> int:
        return int(self.price_xrp * DROPS_PER_XRP)

    @property
    def content_hash(self) -> str:
        return "sha256:" + hashlib.sha256(self.body.encode()).hexdigest()

    @property
    def word_count(self) -> int:
        return len(self.body.split())

    def listing(self, base_url: str) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "abstract": self.abstract,
            "tags": self.tags,
            "word_count": self.word_count,
            "price_xrp": str(self.price_xrp),
            "price_drops": self.price_drops,
            "license": self.license,
            "pay_to": self.pay_to,
            "url": f"{base_url}/articles/{self.id}",
        }


def load_articles(content_dir: Path, default_pay_to: str) -> dict[str, Article]:
    articles: dict[str, Article] = {}
    for path in sorted(content_dir.glob("*.md")):
        if path.name.startswith("_") or path.name == "README.md":
            continue
        post = frontmatter.load(path)
        meta = post.metadata
        article = Article(
            id=str(meta.get("id") or path.stem),
            title=str(meta["title"]),
            author=str(meta.get("author", "unknown")),
            abstract=str(meta.get("abstract", "")),
            price_xrp=Decimal(str(meta.get("price_xrp", "0.5"))),
            license=str(meta.get("license", "ai-input")),
            pay_to=str(meta.get("pay_to") or default_pay_to),
            body=post.content.strip(),
            tags=list(meta.get("tags", [])),
        )
        if article.id in articles:
            raise ValueError(f"duplicate article id: {article.id}")
        articles[article.id] = article
    return articles
