"""Crypto.com catalogue harvest helpers.

Live meta codes are on ``mapping_leagues`` (crypto.com ``source_league_id`` /
``settings.league``) on the legacy tip, which is retiring; new league wiring
goes in code (``mappers/exchanges/*_leagues.py``), not here. The only
overlays here are harvest name exceptions the league row cannot express
(MLB feed names vs tip canonicals).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from BigQuery.client import CRYPTO_SECURITY_DEF_TABLE, ro_client, ro_query

# FIX participant labels that do not match tip canonical_name.
MLB_CANONICAL_NAMES: dict[str, str] = {
    "Arizona Diamondbacks": "ARI",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KAN",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Athletics": "OAK",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",
    "Seattle Mariners": "SEA",
    "San Francisco Giants": "SF",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WAS",
    "American League All Stars": "ALR",
    "National League All Stars": "NLR",
}

# crypto.com ring name vs Optic legal name. Sweep and Cart use this map.
# Do not loosen names_fit for the pair.
UFC_FEED_NAMES: dict[str, str] = {
    "Tina Black": "VMA5",
}

HARVEST_NAME_EXCEPTIONS: dict[str, dict[str, str]] = {
    "MLB": MLB_CANONICAL_NAMES,
    "UFC": UFC_FEED_NAMES,
}


def crypto_exchange(row: Any) -> dict[str, Any] | None:
    """Enabled crypto.com exchange on a mapping_leagues row, if any."""
    for ex in getattr(row, "exchanges", None) or []:
        if str(ex.get("sportsbook") or "").lower() != "crypto.com":
            continue
        if not ex.get("enabled", True):
            continue
        return ex
    return None


def crypto_meta_code(row: Any) -> str:
    """Catalogue meta_league from the tip crypto.com exchange."""
    ex = crypto_exchange(row)
    if ex is None:
        return ""
    raw = ex.get("settings")
    settings = raw if isinstance(raw, dict) else {}
    code = str(settings.get("league") or ex.get("source_league_id") or "").strip()
    return code.upper()


def crypto_sport_grouping(row: Any) -> str:
    """crypto.com sport_grouping from the tip exchange, else empty."""
    ex = crypto_exchange(row)
    if ex is None:
        return ""
    raw = ex.get("settings")
    settings = raw if isinstance(raw, dict) else {}
    return str(settings.get("sport_grouping") or "").strip().upper()


def is_tennis_crypto_league(row: Any) -> bool:
    """True when this tip league shares NX.F.OPT.TENNIS (sport_grouping)."""
    return crypto_sport_grouping(row) == "TENNIS"


def slugs_for_crypto_meta(meta_league: str, rows: Sequence[Any]) -> frozenset[str]:
    """Tip slugs whose crypto.com exchange matches catalogue meta_league."""
    want = meta_league.strip().upper()
    if not want:
        return frozenset()
    return frozenset(
        str(row.league) for row in rows if crypto_meta_code(row) == want
    )


def narrow_crypto_leagues(
    slugs: list[str],
    meta_league: str,
    rows: Sequence[Any],
) -> list[str]:
    """Keep inferred tip slugs that match catalogue meta_league on the tip.

    NX.F.OPT.TENNIS is shared by ATP / WTA / Challenger / ITF. Searching
    WTA's book for an ATP catalogue match yields a false name_mismatch.
    Unknown meta codes (no tip row claims them) leave the inferred list.
    """
    allowed = slugs_for_crypto_meta(meta_league, rows)
    if not allowed:
        return slugs
    return [slug for slug in slugs if slug in allowed]


def harvest_name_exceptions(meta_code: str) -> dict[str, str] | None:
    """Extra feed-name → canonical map, or None when the tip names suffice."""
    return HARVEST_NAME_EXCEPTIONS.get(meta_code.strip().upper())


def harvest_exception_key(meta_code: str, feed_name: str) -> str | None:
    """Canonical key for a registered feed label, or None."""
    table = harvest_name_exceptions(meta_code)
    if not table:
        return None
    label = feed_name.strip()
    if not label:
        return None
    if label in table:
        return table[label]
    folded = label.casefold()
    for name, key in table.items():
        if name.casefold() == folded:
            return key
    return None


# Keep in lockstep with gap_inventory.CLOSE_MAX_DAYS. Close Optic sides
# must still match catalogue ids whose last FIX publish is older than Chat's
# 30-day window (test crypto_security_def can lag weeks).
CLOSE_EVENT_DAYS = 3

SECDEF_HARVEST_SQL = """
select cid, name
from (
  select
    cast(meta_external_home_id as string) as cid,
    meta_home_participant as name,
    publish_time,
    meta_event_date
  from `{table}`
  where meta_league = '{league}'
    and meta_external_home_id is not null
    and meta_home_participant is not null
  union all
  select
    cast(meta_external_away_id as string) as cid,
    meta_away_participant as name,
    publish_time,
    meta_event_date
  from `{table}`
  where meta_league = '{league}'
    and meta_external_away_id is not null
    and meta_away_participant is not null
)
where {days} <= 0
   or publish_time > timestamp_sub(current_timestamp(), interval {days} day)
   or (
        meta_event_date is not null
        and date(
              safe.parse_timestamp('%Y-%m-%dT%H:%M:%E*S%Ez', meta_event_date),
              'UTC'
            ) between current_date('UTC')
                and date_add(current_date('UTC'), interval {close_days} day)
      )
qualify row_number() over (partition by cid order by publish_time desc) = 1
"""


def harvest_team_ids_from_fix(
    crypto_league: str,
    *,
    days: int = 30,
) -> dict[str, str]:
    """Return feed participant name -> crypto_id from crypto_security_def.

    ``days <= 0`` skips the publish_time cutoff (latest row per id). Close
    ``meta_event_date`` rows are always included, even when last published
    outside the recency window.
    """
    id_to_name: dict[str, str] = {}
    sql = SECDEF_HARVEST_SQL.format(  # nosec B608 — ints + tip league code
        table=CRYPTO_SECURITY_DEF_TABLE,
        league=crypto_league,
        days=int(days),
        close_days=CLOSE_EVENT_DAYS,
    )
    for row in ro_query(ro_client(), sql):
        cid = row.cid
        name = row.name
        if cid and name:
            id_to_name[str(cid)] = name
    return {name: cid for cid, name in id_to_name.items()}
