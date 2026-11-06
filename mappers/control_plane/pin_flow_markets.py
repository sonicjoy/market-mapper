"""One market-rule draft+verify path for Chat, gap-propose, and Unmapped Why."""

from __future__ import annotations

import json
from typing import Any

from mappers.control_plane.dry_run_market_rules import thin_dry_run_market_rules
from mappers.control_plane.gap_fix_ai_suggest import AI_NOTE, AI_REF, is_ai_suggest_pin
from mappers.control_plane.gap_market_bind import (
    bind_optic_market_id,
    book_enabled,
    is_name_match_book,
    market_type_candidates,
    needs_optic_companion,
    resolve_market_type,
    simulate_overlay_applies,
)
from mappers.control_plane.gap_market_period import (
    ai_canonical_allowed,
)
from mappers.control_plane.league_cfg_memo import effective_league_cfg
from mappers.control_plane.market_rule_card import (
    attach_already_mapped_context,
    payload_from_market_pin,
    pin_notes,
)
from mappers.control_plane.models import MappingMarketRulesPayload, MarketRulePin
from mappers.control_plane.official_citation import stamp_market_pin, stamp_official_rule
from mappers.control_plane.pin_flow_served import (
    blocked_prior,
    explicit_suffix_bind,
    flip_canonical_bind,
    observation_sets_served,
    overlay_accepts,
    retarget_block,
)
from mappers.control_plane.rof_before_rule import (
    MarketRuleObservation,
    draft_ignore_market_rule,
    obs_text,
)
from mappers.exchanges.crypto_com import crypto_python_wired_skip
from mappers.vocab.poly_usa_console import is_smt_rule, wired_canonical


def is_market_pin(pin: dict[str, Any]) -> bool:
    """True when this harvest pin is a mapping_market_rules payload."""
    return str(pin.get("kind") or "") == "mapping_market_rules"


def market_payload_from_pin(pin: dict[str, Any]) -> MappingMarketRulesPayload:
    """Strip harvest-only fields into a market-rules payload."""
    return payload_from_market_pin(pin)


def draft_and_verify_market_rules(
    store: Any,
    observations: list[MarketRuleObservation],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Unique-bind market rules. Ignore→map only when the observation says flip_ignore."""
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for obs in observations:
        _draft_one(store, obs, pins, skipped, seen)
    attach_already_mapped_context(store, pins, skipped)
    return pins, skipped


def _draft_one(
    store: Any,
    obs: MarketRuleObservation,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str, str]],
) -> None:
    if str(obs.get("action") or "") == "ignore":
        draft_ignore_market_rule(store, obs, pins, skipped, seen)
        return
    checked = _precheck(store, obs, skipped)
    if checked is None:
        return
    cfg, rules = checked
    bound = _bind_canonical(obs, cfg, rules, skipped)
    if bound is None:
        return
    optic_id, canonical, bind_refs = bound
    league = str(obs.get("league") or "").strip()
    rule_pins = _rule_pins(
        obs, rules, optic_id=optic_id, canonical=canonical,
        notes=pin_notes(obs, obs_text(obs, "notes")),
    )
    dry = _dry_run(store, league, rule_pins)
    if not dry.get("ok"):
        skipped.append(_skip(obs, "dry_run_blocked", detail=";".join(dry.get("blockers") or [])[:120]))
        return
    identity = (
        league,
        str(obs.get("sportsbook") or "").strip().lower(),
        str(obs.get("source_key_type") or "").strip(),
        str(obs.get("source_key") or "").strip(),
    )
    if identity in seen:
        return
    seen.add(identity)
    pins.append(
        {
            "kind": "mapping_market_rules",
            "league": league,
            "rules": rule_pins,
            "evidence_refs": _refs(obs, bind_refs),
        },
    )


def _bind_canonical(
    obs: MarketRuleObservation,
    cfg: Any,
    rules: list[Any],
    skipped: list[dict[str, str]],
) -> tuple[str, str, list[str]] | None:
    """(optic_id, canonical, evidence) once the bind survives every hard gate."""
    book = str(obs.get("sportsbook") or "").strip().lower()
    source_key = str(obs.get("source_key") or "").strip()
    live_ids = set(obs.get("live_optic_market_ids") or set())
    market_group = str(obs.get("market_group") or "")
    bound = flip_canonical_bind(obs, cfg) or bind_optic_market_id(
        league=str(obs.get("league") or "").strip(),
        book=book,
        source_key=source_key,
        live_ids=live_ids,
        market_group=market_group,
    ) or explicit_suffix_bind(obs, cfg)
    if bound is None:
        row = _skip(obs, "no_optic_canonical")
        candidates = market_type_candidates(live_ids, cfg)
        if candidates:
            row["candidates"] = json.dumps(candidates, separators=(",", ":"))
        skipped.append(row)
        return None
    optic_id, _spine_cmt, bind_refs = bound
    mt = resolve_market_type(cfg, optic_id)
    if mt is None:
        skipped.append(_skip(obs, "needs_code", optic_id=optic_id))
        return None
    canonical = str(mt.value)
    if not overlay_accepts(
        obs, cfg, rules, canonical, market_group, obs_text(obs, "notes"),
    ):
        skipped.append(_skip(obs, "overlay_unwired", optic_id=optic_id))
        return None
    blocked = retarget_block(obs, cfg, rules, canonical)
    if blocked:
        skipped.append(_skip(obs, blocked, detail=canonical))
        return None
    return optic_id, canonical, bind_refs


def _precheck(
    store: Any,
    obs: MarketRuleObservation,
    skipped: list[dict[str, str]],
) -> tuple[Any, list[Any]] | None:
    """Effective cfg + tip rules once the observation clears the hard gates."""
    league = str(obs.get("league") or "").strip()
    book = str(obs.get("sportsbook") or "").strip().lower()
    source_key = str(obs.get("source_key") or "").strip()
    source_key_type = str(obs.get("source_key_type") or "").strip()
    if not league or not book or not source_key or not source_key_type:
        skipped.append(_skip(obs, "incomplete"))
        return None
    if not is_name_match_book(book):
        skipped.append(_skip(obs, "not_name_match_book"))
        return None
    loaded = effective_league_cfg(store, league)
    if loaded is None:
        skipped.append(_skip(obs, "league_not_on_tip"))
        return None
    cfg, league_row, rules = loaded
    if not book_enabled(league_row, book):
        skipped.append(_skip(obs, "league_not_on_tip"))
        return None
    flipping = bool(obs.get("flip_ignore"))
    if not flipping and not observation_sets_served(obs) and _poly_usa_python_wired(obs, cfg, skipped):
        return None
    if not flipping and not observation_sets_served(obs) and _crypto_python_wired(obs, cfg, skipped):
        return None
    if blocked_prior(obs, rules, book, source_key_type, source_key, skipped, _skip):
        return None
    return cfg, rules


def _poly_usa_python_wired(
    obs: MarketRuleObservation,
    cfg: Any,
    skipped: list[dict[str, str]],
) -> bool:
    """Polymarket US maps from its enum table, so a tip map rule is never pinned."""
    if str(obs.get("sportsbook") or "").strip().lower() != "polymarket_usa":
        return False
    key = str(obs.get("source_key") or "")
    wired = None
    if is_smt_rule(str(obs.get("source_key_type") or "")):
        wired = wired_canonical(cfg, key)
    if wired is not None:
        skipped.append(_skip(obs, "already_mapped", detail=wired))
    else:
        skipped.append(_skip(obs, "needs_code", detail="poly_usa_smt"))
    return True


def _crypto_python_wired(
    obs: MarketRuleObservation,
    cfg: Any,
    skipped: list[dict[str, str]],
) -> bool:
    """True when Python already maps this crypto.com contract type."""
    if str(obs.get("sportsbook") or "").strip().lower() != "crypto.com":
        return False
    crypto = getattr(cfg, "CRYPTO", None)
    if crypto is None:
        return False
    hit = crypto_python_wired_skip(
        crypto,
        str(obs.get("source_key") or ""),
        str(obs.get("source_key_type") or ""),
        str(obs.get("market_group") or ""),
    )
    if hit is None:
        return False
    reason, detail = hit
    skipped.append(_skip(obs, reason, detail=detail))
    return True


def _rule_pins(
    obs: MarketRuleObservation,
    rules: list[Any],
    *,
    optic_id: str,
    canonical: str,
    notes: str | None = None,
) -> list[dict[str, Any]]:
    """Book pin, plus the tip Optic canonical row when the league lacks one."""
    league = str(obs.get("league") or "").strip()
    out: list[dict[str, Any]] = []
    if needs_optic_companion(rules, optic_id):
        out.append(_optic_pin(league, optic_id, canonical, notes=notes))
    out.append(
        _book_pin(
            league,
            str(obs.get("sportsbook") or "").strip().lower(),
            str(obs.get("source_key_type") or "").strip(),
            str(obs.get("source_key") or "").strip(),
            canonical,
            match_operator=str(obs.get("match_operator") or "exact"),
            notes=notes,
            official_description=obs_text(obs, "official_description"),
            citation_url=obs_text(obs, "citation_url"),
            line_offset=obs.get("line_offset"),
            yes_side=obs_text(obs, "yes_side"),
            side_swap=obs.get("side_swap"),
        ),
    )
    return out


def _dry_run(store: Any, league: str, rule_pins: list[dict[str, Any]]) -> dict[str, Any]:
    payload = MappingMarketRulesPayload(
        league=league, rules=[MarketRulePin.model_validate(p) for p in rule_pins],
    )
    rid = getattr(store, "current_rule_set_id", None)
    leagues = list(store.leagues_for(rid)) if rid else []
    tip_rules = list(store.market_rules_for(rid)) if rid else []
    return thin_dry_run_market_rules(leagues, tip_rules, payload)


def _refs(obs: MarketRuleObservation, extra: list[str]) -> list[str]:
    refs = list(obs.get("evidence_refs") or [])
    refs.extend(extra)
    demand = int(obs.get("demand") or 0)
    if demand:
        refs.append(f"rfq_demand:{demand}")
    return refs


def _ai_market_rules(
    store: Any,
    obs: MarketRuleObservation,
    *,
    optic_id: str,
    canonical: str,
) -> tuple[str, list[dict[str, Any]]] | None:
    """League + rule pins when the closed-list pick passes dry-run."""
    league = str(obs.get("league") or "").strip()
    book = str(obs.get("sportsbook") or "").strip().lower()
    source_key = str(obs.get("source_key") or "").strip()
    source_key_type = str(obs.get("source_key_type") or "").strip()
    loaded = effective_league_cfg(store, league)
    if loaded is None:
        return None
    cfg, _row, rules = loaded
    if optic_id not in set(obs.get("live_optic_market_ids") or set()):
        return None
    mt = resolve_market_type(cfg, optic_id)
    if mt is None or str(mt.value) != canonical:
        return None
    group = str(obs.get("market_group") or "")
    allowed = ai_canonical_allowed(
        cfg, league=league, book=book, source_key=source_key,
        source_key_type=source_key_type, canonical=canonical, market_group=group,
    )
    trial_notes = AI_NOTE
    applies = simulate_overlay_applies(
        cfg, rules, sportsbook=book, source_key_type=source_key_type,
        source_key=source_key, canonical=canonical, market_group=group,
        notes=trial_notes,
    )
    if not allowed or not applies:
        return None
    notes = trial_notes
    pins = _rule_pins(obs, rules, optic_id=optic_id, canonical=canonical, notes=notes)
    if not _dry_run(store, league, pins).get("ok"):
        return None
    return league, pins


def draft_ai_market_pin(
    store: Any,
    obs: MarketRuleObservation,
    *,
    optic_id: str,
    canonical: str,
    skip_reason: str = "",
) -> dict[str, Any] | None:
    """One AI suggestion pin after closed-list pick; same dry-run gate."""
    checked = _ai_market_rules(store, obs, optic_id=optic_id, canonical=canonical)
    if checked is None:
        return None
    league, rule_pins = checked
    extra = [AI_REF, f"ai:skip:{skip_reason or 'unknown'}", AI_NOTE, f"optic:market_id:{optic_id}"]
    return {
        "kind": "mapping_market_rules",
        "league": league,
        "rules": rule_pins,
        "evidence_refs": _refs(obs, extra),
    }


def verify_market_pins(
    store: Any,
    pins: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep market pins that pass thin dry-run (no live-name probe)."""
    kept: list[dict[str, Any]] = []
    skipped: list[str] = []
    rid = getattr(store, "current_rule_set_id", None)
    leagues = list(store.leagues_for(rid)) if rid else []
    rules = list(store.market_rules_for(rid)) if rid else []
    for pin in pins:
        if not is_market_pin(pin):
            continue
        stamped = stamp_market_pin(pin)
        if is_ai_suggest_pin(stamped):
            kept.append(stamped)
            continue
        payload = market_payload_from_pin(stamped)
        dry = thin_dry_run_market_rules(leagues, rules, payload)
        if dry.get("ok"):
            kept.append(stamped)
        else:
            skipped.extend(str(b) for b in (dry.get("blockers") or []))
    return kept, skipped


def _book_pin(
    league: str,
    book: str,
    source_key_type: str,
    source_key: str,
    canonical: str,
    *,
    match_operator: str = "exact",
    notes: str | None = None,
    official_description: str | None = None,
    citation_url: str | None = None,
    line_offset: float | None = None,
    yes_side: str | None = None,
    side_swap: bool | None = None,
) -> dict[str, Any]:
    return stamp_official_rule(MarketRulePin(
        sportsbook=book,
        rule_kind="taxonomy",
        source_key_type=source_key_type,
        source_key=source_key,
        action="map",
        canonical_market_type=canonical,
        league=league,
        match_operator=match_operator,
        notes=notes,
        official_description=official_description,
        citation_url=citation_url,
        line_offset=line_offset,
        yes_side=yes_side,
        side_swap=side_swap,
    ).model_dump(mode="json"))


def _optic_pin(
    league: str,
    optic_id: str,
    canonical: str,
    *,
    notes: str | None = None,
) -> dict[str, Any]:
    return stamp_official_rule(MarketRulePin(
        sportsbook="optic",
        rule_kind="taxonomy",
        source_key_type="market_id",
        source_key=optic_id,
        action="map",
        canonical_market_type=canonical,
        league=league,
        notes=notes,
    ).model_dump(mode="json"))


def _skip(
    obs: MarketRuleObservation,
    reason: str,
    *,
    optic_id: str = "",
    detail: str = "",
) -> dict[str, str]:
    row = {
        "reason": reason,
        "league": str(obs.get("league") or ""),
        "sportsbook": str(obs.get("sportsbook") or ""),
        "source_key": str(obs.get("source_key") or ""),
        "source_key_type": str(obs.get("source_key_type") or ""),
        "demand": str(int(obs.get("demand") or 0)),
    }
    if optic_id:
        row["optic_id"] = optic_id
    if detail:
        row["detail"] = detail
    group = str(obs.get("market_group") or "").strip()
    if group:
        row["market_group"] = group
    return row
