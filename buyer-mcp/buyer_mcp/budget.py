"""Local spend log for the buyer agent: what it paid, what is unresolved, what is left.

The file is the source of truth for the budget, shared by every MCP process on the
machine, so all spending decisions happen under an exclusive file lock. An entry is
written *before* money can move, so a crash or lost response leaves the budget held
rather than silently refunded.

Entry status: pending (payment in flight), unknown (may have settled), paid.
"""

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

PAID = "paid"
PENDING = "pending"
UNKNOWN = "unknown"
HELD = (PENDING, UNKNOWN)


class BudgetBook:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(f"{self.path}.lock", "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def load(self) -> list[dict]:
        """Raises on a corrupt file, so no purchase can proceed on unknown spend."""
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text())["entries"]

    def save(self, entries: list[dict]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"entries": entries}, indent=2))
        os.replace(tmp, self.path)


def total(entries: list[dict], statuses: tuple[str, ...]) -> int:
    """Micro-dollars. Amounts are USD on every rail, so one budget covers them all."""
    return sum(e["price_usd_micros"] for e in entries if e["status"] in statuses)


def find(entries: list[dict], article_id: str) -> dict | None:
    return next((e for e in entries if e["article_id"] == article_id), None)
