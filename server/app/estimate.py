"""Pricing help for writers: a suggested price for their audience, and what a price brings in a month.

Toll Gate has almost no traffic yet, so this doesn't forecast from its own sales. It assumes about
one paid agent read for every person who reads the writer's work, which is where web traffic is
heading, and says so on the page. Money stays in integer micro-dollars, rounded down.
Figures checked Nov 28, 2026.
"""

from fractions import Fraction
from math import isqrt

BPS = 10_000
MAX_READERS = 100_000_000

# One paid agent read per human read. Bots already make 57.5% of requests for web pages
# (Cloudflare, 2026). Today about 1 in 31 visits to publisher sites is an AI agent (TollBit, Q4 2025).
AGENT_READS_PER_HUMAN_READ = Fraction(1)

# A suggested price falls as the audience grows, since a small audience usually means more specialized
# work: $0.10 a read (the top of what publishers charge AI per page) up to 1,000 readers, then with the
# square root of the audience down to $0.01 (x402 Bazaar paid content) at 100,000. Earnings still rise
# with the audience. Rounded to a tenth of a cent.
TOP_PRICE, FLOOR_PRICE, NICHE_READERS, STEP = 100_000, 10_000, 1_000, 1_000

HOW = (
    "We assume about one paid agent read for every person who reads your work each month. "
    "Bots already make 57.5% of requests for web pages (Cloudflare, 2026); today about 1 in 31 visits "
    "to publisher sites is an AI agent (TollBit, Q4 2025).",
    "Monthly earnings = readers × your price, minus Toll Gate's fee.",
    "Suggested price: publishers charge AI $0.001–$0.10 a page, and paid content on the x402 Bazaar sells for "
    "$0.005–$0.02 (Nov 2026). Specialized work for a small audience is worth more per read, so the suggestion is "
    "$0.10 up to 1,000 readers and falls to $0.01 at 100,000.",
)


def suggested_price(monthly_readers: int) -> int:
    if monthly_readers <= NICHE_READERS:
        return TOP_PRICE
    # TOP_PRICE × sqrt(NICHE_READERS / readers), in integers: isqrt works on micro-units squared.
    raw = TOP_PRICE * isqrt(NICHE_READERS * 10**12 // monthly_readers) // 10**6
    rounded = (raw + STEP // 2) // STEP * STEP
    return max(FLOOR_PRICE, min(TOP_PRICE, rounded))


def monthly_earnings(price_usd_micros: int, monthly_readers: int, fee_bps: int) -> tuple[int, int]:
    """(paid agent reads, writer's earnings after the fee) for one month. The fee is taken per read, like the ledger."""
    if price_usd_micros <= 0:
        raise ValueError("price must be positive")
    if not 0 <= monthly_readers <= MAX_READERS:
        raise ValueError(f"monthly readers must be between 0 and {MAX_READERS:,}")
    reads = int(monthly_readers * AGENT_READS_PER_HUMAN_READ)
    net_per_read = price_usd_micros - price_usd_micros * fee_bps // BPS
    return reads, reads * net_per_read
