"""Clone-from market-rule pins for Proposed mapping rows."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.league_review import book_label
from mappers.control_plane.market_rule_evidence import (
    context_mapping_rows,
    evidence_by_source_key,
)
from mappers.control_plane.models import MarketRulePin
from mappers.control_plane.rows import MarketRuleRow

_CLONE_PREFIX = "clone:"


def mapping_side(
    *,
    platform: str = "",
    name: str = "",
    description: str = "",
    sport: str = "",
    league: str = "",
    code: str = "",
    id_: str = "",
    symbol: str = "",
    slug: str = "",
    alias_kind: str = "",
) -> dict[str, str]:
    """Sparse Source/Target dict for a Proposed mapping card."""
    out: dict[str, str] = {}
    if platform:
        out["platform"] = platform
    if name:
        out["name"] = name
    if description:
        out["description"] = description
    if sport:
        out["sport"] = sport
    if league:
        out["league"] = league
    if code:
        out["code"] = code
    if id_:
        out["id"] = id_
    if symbol:
        out["symbol"] = symbol
    if slug:
        out["slug"] = slug
    if alias_kind:
        out["alias_kind"] = alias_kind
    return out


def clone_row_key(league: str) -> str:
    """Legacy mapping-row key for dropping a whole cloned taxonomy."""
    return f"{_CLONE_PREFIX}{league}"


def parse_clone_key(key: str) -> str | None:
    """League slug from a clone bundle key, else None."""
    if not key.startswith(_CLONE_PREFIX):
        return None
    slug = key[len(_CLONE_PREFIX) :].strip()
    return slug or None


def rows_from_rule_groups(
    payload: Any,
    *,
    groups: dict[str, Any] | None,
    tip_leagues: dict[str, Any],
    new_leagues: set[str],
    pin_rows: Any,
) -> list[dict[str, Any]]:
    """Explicit rule pins plus read-only already-mapped context."""
    rows: list[dict[str, Any]] = []
    for lg in payload.leagues:
        rows.extend(pin_rows(
            lg.league, lg.market_rules, groups=groups,
            sport=str(lg.sport or getattr(tip_leagues.get(lg.league), "sport", None) or ""),
            league_is_new=lg.league in new_leagues,
            evidence_by_key=evidence_by_source_key(
                list(lg.evidence_refs or []),
                [str(pin.source_key or "") for pin in lg.market_rules],
            ),
        ))
    for group in payload.market_rules:
        sport = str(getattr(tip_leagues.get(group.league), "sport", None) or "")
        fresh = group.league in new_leagues
        owned = evidence_by_source_key(
            list(group.evidence_refs or []),
            [str(pin.source_key or "") for pin in (*group.rules, *group.context_rules)],
        )
        rows.extend(pin_rows(
            group.league, group.rules, groups=groups, sport=sport,
            league_is_new=fresh, evidence_by_key=owned,
        ))
        rows.extend(context_mapping_rows(
            group.league, group.context_rules, sport=sport,
            league_is_new=fresh, evidence_by_key=owned,
        ))
    return rows


def rule_row_key(league: str, pin: MarketRulePin) -> str:
    """Same key shape as explicit market-rule mapping rows."""
    return f"rule:{league}:{pin.sportsbook}:{pin.source_key_type}:{pin.source_key}"


def clone_rule_pins(tip_rules: list[MarketRuleRow], from_league: str) -> list[MarketRulePin]:
    """Copy analogue-league tip rules as pins onto the new league."""
    out: list[MarketRulePin] = []
    for row in tip_rules:
        if row.tombstone or (row.league or "") != from_league:
            continue
        if str(row.sportsbook or "").lower() == "kalshi":
            # Kalshi maps from its own typed fields; tip rules are never copied.
            continue
        out.append(_pin_from_tip(row))
    return out


def _pin_from_tip(row: MarketRuleRow) -> MarketRulePin:
    return MarketRulePin(
        sportsbook=row.sportsbook,
        rule_kind=row.rule_kind,
        source_key_type=row.source_key_type,
        source_key=row.source_key,
        action=row.action,
        canonical_market_type=row.canonical_market_type,
        priority=row.priority,
        enabled=row.enabled,
        confidence=row.confidence,
        match_operator=row.match_operator,
        notes=row.notes,
        line_offset=row.line_offset,
        yes_side=row.yes_side,
        side_swap=row.side_swap,
        official_description=row.official_description,
        citation_url=row.citation_url,
    )


def clone_previews(
    tip_rules: list[MarketRuleRow],
    from_league: str,
) -> list[dict[str, str]]:
    """Checker lines for the league card; Keep/Drop lives on per-rule cards."""
    out: list[dict[str, str]] = []
    for pin in clone_rule_pins(tip_rules, from_league):
        out.append(
            {
                "sportsbook": pin.sportsbook,
                "sportsbook_label": book_label(pin.sportsbook),
                "source_key": pin.source_key,
                "source_key_type": pin.source_key_type,
                "action": pin.action,
                "canonical_market_type": str(pin.canonical_market_type or ""),
            }
        )
    return out
