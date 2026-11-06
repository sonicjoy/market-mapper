"""Alert when a live tip crypto_id's catalogue name is a different entity.

Mapper ticks resolve sides by crypto_id only. A swapped pin (Song's id on
Umar) would invert fight moneylines. This check joins the activated tip to
the latest SecurityDef participant names and publishes mismatches.

Usage:
    GCP_PROJECT=rs-marketmaking python -m BigQuery.crypto_id_name_check
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

from BigQuery.alerts import build_publisher
from BigQuery.client import CRYPTO_SECURITY_DEF_TABLE, ro_client, ro_query
from BigQuery.mapping_rule_rows import ENTITIES_CURRENT_TABLE
from mappers.canonical_codes import names_close, person_league, tokens

_KALSHI_NOTE = re.compile(r"\s+--\s+Kalshi uses\s+\S+\s*$", re.I)

logger = logging.getLogger(__name__)

_TIP_SQL = """
select
  e.league,
  e.canonical_key,
  e.canonical_name,
  a.alias_value as crypto_id
from `{table}` e
cross join unnest(e.aliases) a
where lower(a.sportsbook) = 'crypto.com'
  and lower(a.alias_kind) in ('external_id', 'crypto_id')
  and a.alias_value is not null
"""

_CAT_SQL = """
with sides as (
  select
    cast(meta_external_home_id as string) as crypto_id,
    meta_home_participant as live_name,
    publish_time
  from `{table}`
  where publish_time > timestamp_sub(current_timestamp(), interval 21 day)
    and meta_external_home_id is not null
    and meta_home_participant is not null
  union all
  select
    cast(meta_external_away_id as string),
    meta_away_participant,
    publish_time
  from `{table}`
  where publish_time > timestamp_sub(current_timestamp(), interval 21 day)
    and meta_external_away_id is not null
    and meta_away_participant is not null
)
select crypto_id, live_name
from sides
qualify row_number() over (
  partition by crypto_id order by publish_time desc
) = 1
"""


def fetch_tip_crypto_ids(client: Any) -> list[dict[str, str]]:
    """Activated-tip crypto.com id pins."""
    sql = _TIP_SQL.replace("{table}", ENTITIES_CURRENT_TABLE)
    return [
        {
            "league": str(row.league or ""),
            "canonical_key": str(row.canonical_key or ""),
            "canonical_name": str(row.canonical_name or ""),
            "crypto_id": str(row.crypto_id or "").strip(),
        }
        for row in ro_query(client, sql)
        if str(row.crypto_id or "").strip()
    ]


def fetch_live_names(client: Any) -> dict[str, str]:
    """Latest catalogue participant name per crypto.com EXTERNAL id."""
    sql = _CAT_SQL.replace("{table}", CRYPTO_SECURITY_DEF_TABLE)
    return {
        str(row.crypto_id).strip(): str(row.live_name or "").strip()
        for row in ro_query(client, sql)
        if str(row.crypto_id or "").strip() and str(row.live_name or "").strip()
    }


def _clean_name(name: str) -> str:
    """Drop harvest notes so 'Club -- Kalshi uses X' still names_close."""
    return _KALSHI_NOTE.sub("", name).strip()


def _label_ok(shown: str, owner: str, *, player: bool) -> bool:
    """True when catalogue label is the same person/club as the tip name."""
    left, right = _clean_name(shown), _clean_name(owner)
    if names_close(left, right, player=player):
        return True
    if not player:
        return False
    live_toks = [t.upper() for t in tokens(left)]
    owner_toks = [t.upper() for t in tokens(right)]
    return (
        len(live_toks) >= 2
        and live_toks[0] in owner_toks
        and live_toks[-1] in owner_toks
    )


def mismatch_rows(
    pins: list[dict[str, str]], live: dict[str, str],
) -> list[str]:
    """Swap or wrong-person pins; ignore longer club spellings without a sibling."""
    by_league: dict[str, list[dict[str, str]]] = {}
    for pin in pins:
        by_league.setdefault(pin["league"], []).append(pin)
    lines: list[str] = []
    for league, group in sorted(by_league.items()):
        player = person_league(league)
        for pin in group:
            line = _one_mismatch(pin, live, group, player=player)
            if line:
                lines.append(line)
    return lines


def _one_mismatch(
    pin: dict[str, str],
    live: dict[str, str],
    group: list[dict[str, str]],
    *,
    player: bool,
) -> str | None:
    """Swap (sibling) or person mismatch; empty when the pin's own name fits."""
    cid = pin["crypto_id"]
    shown = live.get(cid) or ""
    owner = pin["canonical_name"] or pin["canonical_key"]
    if not shown or _label_ok(shown, owner, player=player):
        return None
    sibling = _sibling_key(shown, pin["canonical_key"], group, player=player)
    if sibling:
        return (
            f"[{pin['league']}] crypto.com {cid} is live as {shown!r}, "
            f"not {owner!r} (matches {sibling})"
        )
    if not player:
        return None
    return (
        f"[{pin['league']}] crypto.com {cid} is live as {shown!r}, "
        f"not {owner!r}"
    )


def _sibling_key(
    shown: str, owner_key: str, group: list[dict[str, str]], *, player: bool,
) -> str:
    """Other canonical in this league whose name matches the live label."""
    for other in group:
        if other["canonical_key"] == owner_key:
            continue
        name = other["canonical_name"] or other["canonical_key"]
        if _label_ok(shown, name, player=player):
            return other["canonical_key"]
    return ""


def format_alert(lines: list[str]) -> str:
    """Slack body for tip crypto_id name mismatches."""
    head = (
        f"crypto.com tip id/name mismatch: {len(lines)} pin(s) — "
        "mapper will not stamp crossed sides"
    )
    return "\n".join([head, *lines[:20]])


def run_check() -> int:
    """Query tip × catalogue and publish when mismatches exist."""
    client = ro_client()
    pins = fetch_tip_crypto_ids(client)
    live = fetch_live_names(client)
    lines = mismatch_rows(pins, live)
    if not lines:
        logger.info("no crypto.com tip id/name mismatches (%d pins)", len(pins))
        return 0
    text = format_alert(lines)
    logger.warning("%s", text)
    publisher = build_publisher()
    try:
        publisher.publish("warning", text)
    finally:
        publisher.close()
    return 0


def main() -> int:
    """CLI entry: never fail the pipeline."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        return run_check()
    except Exception:
        logger.exception("crypto id/name check failed (non-fatal)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
