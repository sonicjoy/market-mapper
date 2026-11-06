"""Shared WHERE fragments for console / harvest reads of ``reporting_us.rfq_latest``.

rfq_latest is day-partitioned on ``first_publish_time`` and clustered on
``(platform, status, external_rfq_id)``; ``metadata`` (~130 GB / 48h) and
``legs.platform_mapping`` (~48 GB / 48h) are JSON and billed whole whatever
path is read. So cost is set by how many partitions and clustered blocks a
query touches, not by which JSON keys it extracts:

- Bound ``first_publish_time`` to the ``last_updated`` window plus
  ``PUBLISH_LAG_HOURS``. Measured 2026-09-26: all 6.0M rows updated in the
  last 3h were first published < 6h ago, so a 48h bound only added two idle
  daily partitions.
- Filter ``status`` and an exact ``platform`` list (never ``like``/``lower``)
  so clustering prunes. Every MAPPING_FAILED / UNMAPPED row has
  ``status = 'failed'`` (all venues, 48h, same date) -- except DraftKings,
  whose MAPPING_FAILED is ``skipped`` (``dkex_mapping_failed``, 2026-10-16).
"""

from __future__ import annotations

from mappers.control_plane.rfq_platforms import (
    BOOK_CRYPTO,
    BOOK_DKEX,
    BOOK_HUDDLE,
    BOOK_KALSHI,
    BOOK_NOVIG,
    BOOK_PX,
    BOOK_SXBET,
    BOOK_UNDERDOG,
    PLATFORMS_BY_BOOK,
)

# Slack between an RFQ's first publish and its latest update inside the window.
PUBLISH_LAG_HOURS = 3

KALSHI_PLATFORMS = PLATFORMS_BY_BOOK[BOOK_KALSHI]
CRYPTO_PLATFORMS = PLATFORMS_BY_BOOK[BOOK_CRYPTO]
NOVIG_PLATFORMS = PLATFORMS_BY_BOOK[BOOK_NOVIG]
PX_PLATFORMS = PLATFORMS_BY_BOOK[BOOK_PX]
UNDERDOG_PLATFORMS = PLATFORMS_BY_BOOK[BOOK_UNDERDOG]
DKEX_PLATFORMS = PLATFORMS_BY_BOOK[BOOK_DKEX]
HUDDLE_PLATFORMS = PLATFORMS_BY_BOOK[BOOK_HUDDLE]
SXBET_PLATFORMS = PLATFORMS_BY_BOOK[BOOK_SXBET]
POLY_PLATFORMS = (
    "polymarket",
    "polymarket-cashout",
    "polymarketus",
    "polymarketus-inplay",
    "polymarketus-cashout",
    "polymarketus-inplay-cashout",
)


def platform_in(platforms: tuple[str, ...], alias: str = "r") -> str:
    """``r.platform in ('a', 'b')`` from a module constant (never caller input)."""
    quoted = ", ".join(f"'{p}'" for p in platforms)
    return f"{alias}.platform in ({quoted})"


def recent_window(hours: int = 3, alias: str = "r") -> str:
    """Rows updated in the last ``hours``, bounded to the partitions that can hold them."""
    lag = int(hours) + PUBLISH_LAG_HOURS
    return (
        f"{alias}.last_updated > timestamp_sub(current_timestamp(), interval {int(hours)} hour)\n"
        f"    and {alias}.first_publish_time > timestamp_sub(current_timestamp(), interval {lag} hour)"
    )


def sxbet_unmapped_legs(alias: str = "r") -> str:
    """RFQs that can carry an unmapped SX leg.

    The SX maker substitutes unmapped legs under partial pricing, so an
    unmapped leg also sits on ``PARTIAL_PRICING_TOO_FEW_SURVIVORS`` (failed)
    and ``offer_sent_part_mapped`` rows, not only on ``UNMAPPED`` (measured
    on prod 2026-10-13).  The leg itself is ``optic_fixture_id is null``.
    """
    return (
        f"(({alias}.status = 'failed'\n"
        f"      and {alias}.reason in ('MAPPING_FAILED', 'UNMAPPED', 'PARTIAL_PRICING_TOO_FEW_SURVIVORS'))\n"
        f"     or {alias}.status = 'offer_sent_part_mapped')"
    )


def dkex_mapping_failed(alias: str = "r") -> str:
    """DraftKings mapping failures: ``skipped`` + ``MAPPING_FAILED``, the ticker on each leg.

    The maker writes no ``metadata.unmapped``; ``legs[].platform_mapping`` carries
    ``market_ticker`` + ``side`` (prod, 2026-10-16: 5,051 RFQs in 6h, all ``skipped``).
    """
    return f"{alias}.status = 'skipped'\n    and {alias}.reason = 'MAPPING_FAILED'"


def underdog_no_mmmapper_row(alias: str = "r") -> str:
    """Underdog legs with no mmmapper row: ``skipped`` + ``UNMAPPED_OPTIC``, ticker on the legs.

    The other Underdog miss, ``failed`` + ``UNMAPPED``, names its ticker in
    ``metadata.unmapped`` (mm-underdogrfq ``mapping/mapping_sources.py``, ``reasons.py``).
    """
    return f"{alias}.status = 'skipped'\n    and {alias}.reason = 'UNMAPPED_OPTIC'"


def unmapped_failed(alias: str = "r") -> str:
    """Mapping failures; ``status`` first so the clustered column prunes blocks."""
    return f"{alias}.status = 'failed'\n    and {alias}.reason in ('MAPPING_FAILED', 'UNMAPPED')"


_TOKENS = {
    "__RECENT_3H__": recent_window(3),
    "__KALSHI__": platform_in(KALSHI_PLATFORMS),
    "__POLY__": platform_in(POLY_PLATFORMS),
    "__NOVIG__": platform_in(NOVIG_PLATFORMS),
    "__PX__": platform_in(PX_PLATFORMS),
    "__UNDERDOG__": platform_in(UNDERDOG_PLATFORMS),
    "__DKEX__": platform_in(DKEX_PLATFORMS),
    "__HUDDLE__": platform_in(HUDDLE_PLATFORMS),
    "__SXBET__": platform_in(SXBET_PLATFORMS),
    "__SXBET_GAP__": sxbet_unmapped_legs(),
    "__DKEX_GAP__": dkex_mapping_failed(),
    "__UNDERDOG_OPTIC_GAP__": underdog_no_mmmapper_row(),
    "__UNMAPPED_FAILED__": unmapped_failed(),
}


def render_rfq_filters(sql: str) -> str:
    """Fill the ``__RECENT_3H__`` / platform / ``__UNMAPPED_FAILED__`` tokens in a SQL template."""
    for token, fragment in _TOKENS.items():
        sql = sql.replace(token, fragment)
    return sql
