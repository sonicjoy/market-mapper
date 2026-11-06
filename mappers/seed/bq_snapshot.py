"""Load the latest shadow mapping rule snapshot from BigQuery (M2).

COW candidates store only changed keys under their ``rule_set_id``. Dual-read
must coalesce tip→root so Python is compared to the full logical snapshot,
not the sparse tip layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from google.cloud import bigquery

from mappers.seed.models import MarketRuleIR
from mappers.seed.tip_alignment import lineage_ids

RULE_SETS = "markets_us.mapping_rule_sets"
MARKET_RULES = "markets_us.mapping_market_rules"
LEAGUES_TABLE = "markets_us.mapping_leagues"

_MARKET_SQL = f"""
select rule_set_id, rule_id, rule_group_id, league, sportsbook, rule_kind,
       source_key_type, source_key, match_operator, market_family,
       canonical_market_type, action, priority, enabled, confidence,
       notes, settlement_note, line_offset, yes_side, side_swap,
       official_description, citation_url,
       ifnull(tombstone, false) as tombstone
from `{MARKET_RULES}`
where rule_set_id in unnest(@ids)
"""  # nosec B608 — table name is a module constant

_LEAGUE_SQL = f"""
select rule_set_id, league, output_order, ifnull(tombstone, false) as tombstone
from `{LEAGUES_TABLE}`
where rule_set_id in unnest(@ids)
"""  # nosec B608


def latest_rule_set_id(client: bigquery.Client) -> str | None:
    sql = f"""
    select rule_set_id
    from `{RULE_SETS}`
    order by created_at desc
    limit 1
    """  # nosec B608 — table name is a module constant
    rows = list(client.query(sql).result())
    return rows[0].rule_set_id if rows else None


def load_market_rules(
    client: bigquery.Client, rule_set_id: str,
) -> list[MarketRuleIR]:
    """Logical market rules for ``rule_set_id`` (ancestors included)."""
    chain = _lineage_chain(client, rule_set_id)
    grouped = _group_by_rule_set(_query_ids(client, _MARKET_SQL, chain), chain)
    return _coalesce_rules(chain, grouped)


def load_output_orders(
    client: bigquery.Client, rule_set_id: str,
) -> dict[str, list[str]]:
    """Logical ``output_order`` per league for ``rule_set_id``."""
    chain = _lineage_chain(client, rule_set_id)
    grouped = _group_by_rule_set(_query_ids(client, _LEAGUE_SQL, chain), chain)
    return _coalesce_orders(chain, grouped)


def _parent_map(client: bigquery.Client) -> dict[str, str | None]:
    sql = f"""
    select rule_set_id, parent_rule_set_id
    from `{RULE_SETS}`
    """  # nosec B608
    return {
        str(row.rule_set_id): (
            str(row.parent_rule_set_id) if row.parent_rule_set_id else None
        )
        for row in client.query(sql).result()
    }


def _lineage_chain(client: bigquery.Client, rule_set_id: str) -> list[str]:
    return lineage_ids(_parent_map(client), rule_set_id)


def _query_ids(
    client: bigquery.Client, sql: str, ids: list[str],
) -> list[Any]:
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("ids", "STRING", ids)],
    )
    return list(client.query(sql, job_config=config).result())


def _group_by_rule_set(
    rows: Sequence[Any], chain: Sequence[str],
) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {rid: [] for rid in chain}
    for row in rows:
        bucket = grouped.get(str(row.rule_set_id))
        if bucket is not None:
            bucket.append(row)
    return grouped


def _rule_key(row: Any) -> tuple[object, object, object, object]:
    return (row.league, row.sportsbook, row.source_key_type, row.source_key)


def _coalesce_rules(
    chain: Sequence[str], grouped: dict[str, list[Any]],
) -> list[MarketRuleIR]:
    seen: set[tuple[object, object, object, object]] = set()
    out: list[MarketRuleIR] = []
    for rid in chain:
        for row in grouped.get(rid, []):
            key = _rule_key(row)
            if key in seen:
                continue
            seen.add(key)
            if bool(row.tombstone):
                continue
            out.append(_row_to_rule(row))
    return out


def _coalesce_orders(
    chain: Sequence[str], grouped: dict[str, list[Any]],
) -> dict[str, list[str]]:
    seen: set[str] = set()
    out: dict[str, list[str]] = {}
    for rid in chain:
        for row in grouped.get(rid, []):
            league = str(row.league)
            if league in seen:
                continue
            seen.add(league)
            if bool(row.tombstone):
                continue
            out[league] = list(row.output_order or [])
    return out


def _optional_float(value: Any) -> float | None:
    """Null line offset when the cell is blank."""
    if value is None or value == "":
        return None
    return float(value)


def _optional_text(value: Any) -> str | None:
    """Null yes-side when the cell is blank."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: Any) -> bool | None:
    """Null side-swap when the cell is blank. False is a real value."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no"}:
            return False
        return None
    return bool(value)


def _row_to_rule(r: Any) -> MarketRuleIR:
    return MarketRuleIR(
        rule_id=r.rule_id,
        rule_group_id=r.rule_group_id,
        league=r.league,
        sportsbook=r.sportsbook,
        rule_kind=r.rule_kind,
        source_key_type=r.source_key_type,
        source_key=r.source_key,
        action=r.action,
        canonical_market_type=r.canonical_market_type,
        priority=int(r.priority),
        enabled=bool(r.enabled),
        confidence=r.confidence,
        match_operator=r.match_operator or "exact",
        market_family=r.market_family,
        notes=r.notes,
        settlement_note=r.settlement_note,
        line_offset=_optional_float(getattr(r, "line_offset", None)),
        yes_side=_optional_text(getattr(r, "yes_side", None)),
        side_swap=_optional_bool(getattr(r, "side_swap", None)),
        official_description=_optional_text(getattr(r, "official_description", None)),
        citation_url=_optional_text(getattr(r, "citation_url", None)),
    )
