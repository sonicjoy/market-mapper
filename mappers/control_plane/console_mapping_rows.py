"""Structured mapping rows for Proposed / review detail (human Source | Target)."""

from __future__ import annotations

from typing import Any, Literal

from mappers.control_plane.alias_evidence import parse_ref, pin_alias_refs
from mappers.control_plane.console_mapping_clone import (
    clone_previews,
    clone_rule_pins,
    mapping_side,
    rows_from_rule_groups,
    rule_row_key,
)
from mappers.control_plane.console_mapping_optic import apply_optic_abbr, is_optic_book, optic_refs_for_pin
from mappers.control_plane.crypto_optic_match import entity_name_from_crypto_refs, event_title_from_crypto_refs
from mappers.control_plane.dry_run_already import resolved_enabled, resolved_fixture_horizon
from mappers.control_plane.entry import league_label
from mappers.control_plane.gap_fix_ai_suggest import AI_NOTE, is_ai_suggest_pin
from mappers.control_plane.league_review import book_label, enabled_book_text, league_card_copy
from mappers.control_plane.market_rule_card import apply_rule_card
from mappers.control_plane.models import (
    BatchChangesPayload,
    EntityAliasPayload,
    MappingLeaguePayload,
    MappingMarketRulesPayload,
    MarketRulePin,
    ProposalRecord,
)
from mappers.control_plane.rows import MarketRuleRow
from mappers.handicap_name_crumb import is_selection_alias

RowKind = Literal["alias", "market_rule", "league"]
RowAction = Literal["add", "update", "delete"]
RowTier = Literal["confirmed", "guess", "ai"]


def _named_value(refs: list[str], prefix: str) -> str:
    for ref in refs:
        if ref.startswith(prefix):
            shown = ref[len(prefix) :].strip()
            if shown:
                return shown
    return ""


def _optic_competitor_name(refs: list[str], code: str) -> str:
    code_l = code.strip().lower()
    for ref in refs:
        head, mid, rest = parse_ref(ref)
        if head != "optic" or mid != "competitor":
            continue
        cid, _, shown = rest.partition(":")
        if cid.lower() == code_l and shown.strip():
            return shown.strip()
    return ""


def _alias_source_name(
    sportsbook: str,
    code: str,
    canonical_name: str,
    refs: list[str],
) -> str:
    """Sportsbook-native source label: evidence name, else the pin, never a vs-title."""
    book = sportsbook.strip().lower()
    if book == "optic":
        shown = _optic_competitor_name(refs, code)
        if shown:
            return shown
    if book == "polymarket_usa":
        shown = _named_value(refs, "polymarket_usa:name:")
        if shown:
            return shown
    if book in {"crypto", "crypto.com"}:
        shown = entity_name_from_crypto_refs(refs, canonical_name)
        if shown:
            return shown
    if book == "polymarket":
        shown = _named_value(refs, "polymarket:name:")
        if shown:
            return shown
    pin = code.strip()
    if pin and " vs " not in pin.lower():
        return pin
    canon = canonical_name.strip()
    if canon:
        return canon
    return code


def _title_from_refs(refs: list[str]) -> str:
    for ref in refs:
        if ref.startswith("kalshi:title:"):
            return ref.split(":", 2)[-1]
        if ref.startswith("poly:question:"):
            return ref.split(":", 2)[-1]
    return event_title_from_crypto_refs(refs)


def _row_base(
    *,
    kind: RowKind,
    key: str,
    action: RowAction,
    league: str,
    sport: str,
    league_is_new: bool,
    evidence: list[str] | None = None,
    rfq_demand: int | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "key": key,
        "action": action,
        "tier": "confirmed",
        "confidence": None,
        "reason": None,
        "alternatives": [],
        "keep_default": True,
        "league": league,
        "league_label": league_label(league),
        "league_is_new": league_is_new,
        "sport": sport,
        "rfq_demand": rfq_demand,
        "next_fixtures": [],
        "evidence": evidence or [],
    }


def _alias_refs(ea: EntityAliasPayload, pin: Any, evidence: list[str]) -> list[str]:
    """Per-pin evidence; Optic pins keep identity refs only."""
    book = str(pin.sportsbook or "")
    own = list(ea.evidence_refs or [])
    code = str(pin.alias_value or "")
    name = ea.canonical_name or ""
    if is_optic_book(book):
        return optic_refs_for_pin(own, evidence, code, name)
    return pin_alias_refs(own, evidence, code, name, book, ea.league)


def _skip_selection_alias(pin: Any) -> bool:
    """True for Polymarket name pins that are market outcomes."""
    if str(pin.sportsbook or "").lower() != "polymarket":
        return False
    if str(pin.alias_kind or "") != "name":
        return False
    return is_selection_alias(str(pin.alias_value or ""))


def _alias_row(
    ea: EntityAliasPayload,
    pin: Any,
    *,
    evidence: list[str],
    action: RowAction,
    sport: str,
    league_is_new: bool,
) -> dict[str, Any]:
    book = str(pin.sportsbook or "")
    code = str(pin.alias_value or "")
    alias_kind = str(pin.alias_kind or "")
    refs = _alias_refs(ea, pin, evidence)
    title = _title_from_refs(refs)
    source_name = _alias_source_name(book, code, ea.canonical_name or "", refs)
    target_name = str(ea.canonical_name or ea.canonical_key or "")
    slug = _named_value(refs, "polymarket:slug:") if book == "polymarket" else ""
    row = _row_base(
        kind="alias",
        key=f"alias:{ea.league}:{ea.canonical_key}:{book}:{code}",
        action=action,
        league=ea.league,
        sport=sport,
        league_is_new=league_is_new,
        evidence=refs,
    )
    row["sportsbook"] = book
    row["source"] = mapping_side(
        platform=book_label(book),
        name=source_name,
        code=code,
        description=title,
        slug=slug,
        alias_kind=alias_kind,
    )
    row["target"] = mapping_side(
        platform="Optic",
        name=target_name,
        code=str(ea.canonical_key or ""),
    )
    apply_optic_abbr(row, refs)
    _mark_ai_row(row, list(ea.evidence_refs or []))
    return row


def _mark_ai_row(row: dict[str, Any], extra: list[str] | None = None) -> None:
    """AI harvest pins default Keep; Drop is still one click away."""
    refs = [str(r) for r in list(extra or []) + list(row.get("evidence") or [])]
    if is_ai_suggest_pin({"evidence_refs": refs}) or AI_NOTE in refs:
        row["tier"] = "ai"


def _rule_row(
    league: str,
    pin: MarketRulePin,
    *,
    action: RowAction,
    sport: str,
    league_is_new: bool,
    rfq_demand: int | None = None,
    clone_from: str = "",
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    book = str(pin.sportsbook or "")
    canonical = str(pin.canonical_market_type or "")
    refs = list(evidence or [])
    notes = str(pin.notes or "").strip()
    if clone_from:
        refs.append(f"clone_market_rules_from:{clone_from}")
    row = _row_base(
        kind="market_rule",
        key=rule_row_key(league, pin),
        action=action,
        league=league,
        sport=sport,
        league_is_new=league_is_new,
        rfq_demand=rfq_demand,
        evidence=refs,
    )
    row["sportsbook"] = book
    row["source"] = mapping_side(
        platform=book_label(book),
        name=str(pin.source_key or ""),
        code=str(pin.source_key or ""),
        description=str(pin.source_key_type or ""),
    )
    row["target"] = mapping_side(
        platform="Optic",
        name=canonical or "ignored",
        description="ignore" if pin.action == "ignore" else canonical,
    )
    if clone_from:
        row["clone_from"] = clone_from
    row["official_description"] = str(pin.official_description or "").strip() or None
    row["citation_url"] = str(pin.citation_url or "").strip() or None
    row["notes"] = notes or None
    apply_rule_card(row, pin, league=league, evidence_refs=refs)
    _mark_ai_row(row, [*refs, notes] if notes else refs)
    return row


def _league_row(
    lg: MappingLeaguePayload,
    *,
    action: RowAction,
    league_is_new: bool,
    clone_from: str = "",
    cloned_rules: list[dict[str, str]] | None = None,
    prior: Any | None = None,
) -> dict[str, Any]:
    books = enabled_book_text(lg.exchanges)
    row = _row_base(
        kind="league",
        key=f"league:{lg.league}",
        action=action,
        league=lg.league,
        sport=str(lg.sport or ""),
        league_is_new=league_is_new,
        evidence=list(lg.evidence_refs or []),
    )
    row["source"] = mapping_side(platform="Platforms", name=books, description=books)
    row["target"] = mapping_side(
        platform="Optic",
        name=league_label(lg.league),
        id_=str(lg.optic_league_id or ""),
        league=lg.league,
    )
    reason, diff = league_card_copy(lg, prior)
    row["reason"] = reason
    row["league_diff"] = diff
    row["optic_league_id"] = str(lg.optic_league_id or "")
    row["fixture_source"] = str(lg.fixture_source or "api")
    row["fixture_horizon_hours"] = resolved_fixture_horizon(lg.fixture_horizon_hours, prior)
    row["enabled"] = resolved_enabled(lg.enabled, prior)
    row["exchanges"] = [ex.model_dump(mode="json") for ex in lg.exchanges]
    if clone_from:
        row["clone_from"] = clone_from
        row["cloned_rules"] = cloned_rules or []
    return row


def _alias_action(pin: Any, groups: dict[str, Any] | None, hint: str) -> RowAction:
    """Delete when the pin is a removal; otherwise snapshot add/update."""
    if getattr(pin, "remove", False):
        return "delete"
    return _action_from_group(groups, "aliases", hint)


def _action_from_group(groups: dict[str, Any] | None, kind: str, line_hint: str) -> RowAction:
    if not groups:
        return "add"
    group = groups.get(kind) or {}
    lines = list(group.get("lines") or [])
    for line in lines:
        if line_hint in str(line) and str(line).strip().startswith("~"):
            return "update"
    return "add"


def _league_payload_rows(
    lg: MappingLeaguePayload,
    *,
    groups: dict[str, Any] | None,
    league_is_new: bool,
    tip_market_rules: list[MarketRuleRow],
    prior: Any | None = None,
) -> list[dict[str, Any]]:
    clone_from = str(lg.clone_market_rules_from or "").strip()
    previews = clone_previews(tip_market_rules, clone_from) if clone_from else []
    action: RowAction = (
        "update"
        if prior is not None
        else _action_from_group(
            groups,
            "leagues",
            lg.league,
        )
    )
    rows = [
        _league_row(
            lg,
            action=action,
            league_is_new=league_is_new,
            clone_from=clone_from,
            cloned_rules=previews,
            prior=prior,
        )
    ]
    if not clone_from:
        return rows
    embedded = {rule_row_key(lg.league, pin) for pin in lg.market_rules}
    pins = [p for p in clone_rule_pins(tip_market_rules, clone_from) if rule_row_key(lg.league, p) not in embedded]
    rows.extend(
        _rule_pin_rows(
            lg.league,
            pins,
            groups=groups,
            sport=str(lg.sport or ""),
            league_is_new=league_is_new,
            clone_from=clone_from,
        )
    )
    return rows


def _rows_from_aliases(
    payload: BatchChangesPayload,
    *,
    groups: dict[str, Any] | None,
    tip_leagues: dict[str, Any],
    new_leagues: set[str],
    evidence: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ea in payload.entity_aliases:
        sport = str(getattr(tip_leagues.get(ea.league), "sport", None) or "")
        for pin in ea.aliases:
            if _skip_selection_alias(pin):
                continue
            rows.append(
                _alias_row(
                    ea,
                    pin,
                    evidence=evidence,
                    action=_alias_action(
                        pin,
                        groups,
                        str(pin.alias_value or ea.canonical_key),
                    ),
                    sport=sport,
                    league_is_new=ea.league in new_leagues,
                )
            )
    return rows


def _rows_from_rules(
    payload: BatchChangesPayload,
    *,
    groups: dict[str, Any] | None,
    tip_leagues: dict[str, Any],
    new_leagues: set[str],
) -> list[dict[str, Any]]:
    return rows_from_rule_groups(
        payload,
        groups=groups,
        tip_leagues=tip_leagues,
        new_leagues=new_leagues,
        pin_rows=_rule_pin_rows,
    )


def _rule_pin_rows(
    league: str,
    pins: list[MarketRulePin],
    *,
    groups: dict[str, Any] | None,
    sport: str,
    league_is_new: bool,
    clone_from: str = "",
    evidence: list[str] | None = None,
    evidence_by_key: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    return [
        _rule_row(
            league,
            pin,
            action=_action_from_group(groups, "market_rules", pin.source_key),
            sport=sport,
            league_is_new=league_is_new,
            clone_from=clone_from,
            evidence=(
                list(evidence_by_key.get(str(pin.source_key or ""), []))
                if evidence_by_key is not None
                else evidence
            ),
        )
        for pin in pins
    ]


def payload_as_batch(payload: object) -> BatchChangesPayload | None:
    """Wrap a single artifact into batch_changes so row builders stay one path."""
    if isinstance(payload, BatchChangesPayload):
        return payload
    if isinstance(payload, EntityAliasPayload):
        return BatchChangesPayload(entity_aliases=[payload])
    if isinstance(payload, MappingLeaguePayload):
        return BatchChangesPayload(leagues=[payload])
    if isinstance(payload, MappingMarketRulesPayload):
        return BatchChangesPayload(market_rules=[payload])
    return None


def mapping_rows_from_proposal(
    proposal: ProposalRecord,
    *,
    groups: dict[str, Any] | None,
    tip_leagues: dict[str, Any],
    new_leagues: set[str],
    tip_market_rules: list[MarketRuleRow] | None = None,
) -> list[dict[str, Any]]:
    """Build unique mapping rows from a proposal payload."""
    payload = payload_as_batch(proposal.payload)
    evidence = [ref for ref in proposal.evidence_refs if ref.strip() and not ref.startswith("Batch:")]
    if payload is None:
        return []
    rules = tip_market_rules or []
    league_rows = [
        row
        for lg in payload.leagues
        for row in _league_payload_rows(
            lg,
            groups=groups,
            league_is_new=lg.league in new_leagues,
            tip_market_rules=rules,
            prior=tip_leagues.get(lg.league),
        )
    ]
    return [
        *league_rows,
        *_rows_from_aliases(
            payload,
            groups=groups,
            tip_leagues=tip_leagues,
            new_leagues=new_leagues,
            evidence=evidence,
        ),
        *_rows_from_rules(
            payload,
            groups=groups,
            tip_leagues=tip_leagues,
            new_leagues=new_leagues,
        ),
    ]
