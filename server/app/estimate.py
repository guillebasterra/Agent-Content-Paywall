"""What a writer could earn per month once agents read and pay, at their price and audience size.

Toll Gate has almost no traffic yet, so this does not forecast from its own sales. It scales the
writer's human readership by how much AI agents read the web, today and in two published
outlooks, and assumes every agent read goes through Toll Gate and pays. The UI says so.

Ratios are exact fractions and money stays in integer micro-dollars, rounded down.
Sources are returned with the numbers so the page can cite them (checked Nov 28, 2026).
"""

from dataclasses import dataclass
from fractions import Fraction

BPS = 10_000
MAX_READERS = 100_000_000


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    basis: str
    agent_reads_per_human_read: Fraction
    source: str


SCENARIOS = (
    Scenario(
        id="today",
        label="At today's AI traffic",
        basis="1 AI bot visit per 31 human visits, 49% of them reading to answer a question",
        # TollBit, State of the Bots Q4 2025 (1:31); RAG share of AI scrapes, H1 2026 (49%)
        agent_reads_per_human_read=Fraction(1, 31) * Fraction(49, 100),
        source="TollBit State of the Bots, Q4 2025 and H1 2026, via The Register and BlazeHive",
    ),
    Scenario(
        id="parity",
        label="When agents read as much as people",
        basis="Bots already make 57.5% of requests for web pages; Cloudflare expects bot traffic to pass human traffic in 2027",
        agent_reads_per_human_read=Fraction(1),
        source="Cloudflare, via TechCrunch (Mar 2026) and SiliconANGLE (Jun 2026)",
    ),
    Scenario(
        id="agent_first",
        label="Agent-first web",
        basis="Agents read 10× what people do. Cloudflare's CEO expects 1,000× within five years",
        agent_reads_per_human_read=Fraction(10),
        source="Matthew Prince, Cloudflare, via The Verge and The Next Web (2026)",
    ),
)

# What paid agent reads cost today, so a writer can place their price.
PRICE_GUIDANCE = {
    "bazaar_content_median_usd": "0.005",
    "bazaar_content_p75_usd": "0.02",
    "publisher_range_usd": "0.001–0.10",
    "premium_usd": "0.20",
    "source": (
        "x402 Bazaar content listings on Base, 30 days to Nov 28, 2026 (6,118 listings); "
        "publisher per-fetch rates on TollBit and Cloudflare Pay Per Crawl, via Presenc AI (Apr 2026)"
    ),
}


def monthly(price_usd_micros: int, monthly_readers: int, fee_bps: int) -> list[dict]:
    """One row per scenario: agent reads a month, and the writer's share after the platform fee."""
    if price_usd_micros <= 0:
        raise ValueError("price must be positive")
    if not 0 <= monthly_readers <= MAX_READERS:
        raise ValueError(f"monthly readers must be between 0 and {MAX_READERS:,}")
    # The fee per read, rounded down, exactly as the ledger takes it on each sale.
    net_per_read = price_usd_micros - price_usd_micros * fee_bps // BPS
    rows = []
    for s in SCENARIOS:
        reads = int(monthly_readers * s.agent_reads_per_human_read)  # whole reads, rounded down
        gross = reads * price_usd_micros
        net = reads * net_per_read
        rows.append({
            "id": s.id,
            "label": s.label,
            "basis": s.basis,
            "source": s.source,
            "agent_reads": reads,
            "gross_usd_micros": gross,
            "earned_usd_micros": net,
        })
    return rows
