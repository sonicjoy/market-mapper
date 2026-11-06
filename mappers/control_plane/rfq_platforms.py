"""RFQ ``reporting_us.rfq_latest`` platform values grouped by gap harvest book."""

from __future__ import annotations

from typing import Any

# book id used in gap_inventory / harvest
BOOK_KALSHI = "kalshi"
BOOK_CRYPTO = "crypto"
BOOK_POLY = "polymarket"
BOOK_NOVIG = "novig"
BOOK_PX = "prophetx"
BOOK_UNDERDOG = "underdog"
BOOK_DKEX = "dkex"
BOOK_HUDDLE = "huddle"
BOOK_SXBET = "sxbet"

# Kalshi is reported (PLATFORMS_BY_BOOK) but never harvested: it maps from
# its own typed fields, so there is no tip alias or rule pin to propose.
HARVEST_BOOKS: tuple[str, ...] = (
    BOOK_CRYPTO,
    BOOK_POLY,
    BOOK_NOVIG,
    BOOK_PX,
    BOOK_UNDERDOG,
    BOOK_DKEX,
    BOOK_HUDDLE,
    # SX: classified only (gap_fix_sxbet) -- its leagues, market types and
    # name pins are code tables, so there is no tip pin to draft.
    BOOK_SXBET,
)

PLATFORMS_BY_BOOK: dict[str, tuple[str, ...]] = {
    BOOK_KALSHI: ("kalshi", "kalshi-inplay", "kalshi-inplay-cashout"),
    BOOK_CRYPTO: ("cryptocom", "cryptocom-inplay"),
    BOOK_POLY: (),  # use ``sql_poly_platform_predicate`` (like polymarket%)
    BOOK_NOVIG: ("novig", "novig-inplay"),
    BOOK_PX: ("prophetx", "prophetx-inplay"),
    BOOK_UNDERDOG: ("underdog", "underdog-inplay"),
    # DraftKings Exchange writes ``draftkings`` (prod, 2026-10-16); ``dkex`` is only our book id.
    BOOK_DKEX: ("draftkings", "draftkings-inplay"),
    BOOK_HUDDLE: ("huddle",),
    BOOK_SXBET: ("sxbet",),
}

_ALL_KNOWN: frozenset[str] = frozenset(
    p for platforms in PLATFORMS_BY_BOOK.values() for p in platforms
)


def sql_platform_in(book: str) -> str:
    """SQL ``r.platform in (...)`` fragment for a harvest book."""
    platforms = PLATFORMS_BY_BOOK.get(book, ())
    if not platforms:
        raise ValueError(f"no fixed platform list for book {book!r}")
    quoted = ", ".join(f"'{p}'" for p in platforms)
    return f"r.platform in ({quoted})"


def sql_crypto_platform_predicate(alias: str = "r") -> str:
    """Crypto.com prematch + in-play platforms."""
    platforms = PLATFORMS_BY_BOOK[BOOK_CRYPTO]
    quoted = ", ".join(f"'{p}'" for p in platforms)
    return f"{alias}.platform in ({quoted})"


def sql_poly_platform_predicate(alias: str = "r") -> str:
    """Polymarket official + US + in-play."""
    return f"lower({alias}.platform) like 'polymarket%'"


def sql_unknown_platform_predicate(alias: str = "r") -> str:
    """True for RFQ platforms gap harvest does not inventory yet."""
    platforms = sorted(_ALL_KNOWN)
    quoted = ", ".join(f"'{p}'" for p in platforms)
    return (
        f"lower({alias}.platform) not like 'polymarket%' "
        f"and {alias}.platform not in ({quoted})"
    )


def fetch_unknown_mapping_failure_platforms(
    *,
    project: str | None = None,
    hours: int = 3,
    query_fn: Any | None = None,
) -> list[tuple[str, int]]:
    """RFQ platforms with mapping failures outside the harvest inventory set."""
    import os

    from google.cloud import bigquery

    from BigQuery.client import ro_query

    proj = project or os.environ.get("GCP_PROJECT") or "rs-marketmaking"
    sql = unknown_mapping_failure_platforms_sql(project=proj, hours=hours)
    if query_fn is not None:
        raw = list(query_fn(sql))
    else:
        try:
            client = bigquery.Client(project=proj)
            raw = list(ro_query(client, sql))
        except Exception:  # noqa: BLE001 — offline pytest / missing ADC
            return []
    out: list[tuple[str, int]] = []
    for row in raw:
        platform = str(getattr(row, "platform", "") or row.get("platform", "")).strip()
        demand = int(getattr(row, "demand", 0) or row.get("demand", 0) or 0)
        if platform and demand > 0:
            out.append((platform, demand))
    return out


def unknown_mapping_failure_platforms_sql(*, project: str, hours: int = 3) -> str:
    """Platforms with mapping failures outside the known harvest set."""
    where = sql_unknown_platform_predicate("r")
    return _UNKNOWN_PLATFORMS_SQL.format(
        project=project,
        where=where,
        hours=int(hours),
    )


_UNKNOWN_PLATFORMS_SQL = """
select r.platform as platform, count(*) as demand
from `{project}.reporting_us.rfq_latest` r
where r.last_updated > timestamp_sub(current_timestamp(), interval {hours} hour)
  and r.first_publish_time > timestamp_sub(current_timestamp(), interval 48 hour)
  and r.reason in ('MAPPING_FAILED', 'UNMAPPED')
  and {where}
group by 1
having count(*) > 0
order by demand desc
"""  # nosec B608


def is_known_mapping_failure_platform(platform: str) -> bool:
    """True when gap harvest understands this rfq_latest platform."""
    text = platform.strip().lower()
    if not text:
        return False
    if text in _ALL_KNOWN:
        return True
    return text.startswith("polymarket")
