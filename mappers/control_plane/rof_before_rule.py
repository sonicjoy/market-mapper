"""Ignore draft for Polymarket US ``rof-before-rN``.

Chat, gap-propose, and Cart all call ``draft_and_verify_market_rules``,
which dispatches ``action=ignore`` here. There is no second matcher.
"""

from __future__ import annotations

from typing import Any, TypedDict

from mappers.control_plane.dry_run_market_rules import thin_dry_run_market_rules
from mappers.control_plane.gap_market_bind import (
    book_enabled,
    is_name_match_book,
    tip_market_rule,
)
from mappers.control_plane.league_cfg_memo import effective_league_cfg
from mappers.control_plane.models import MappingMarketRulesPayload, MarketRulePin
from mappers.control_plane.official_citation import stamp_official_rule
from mappers.vocab.combat_usa import (
    ROF_BEFORE_KEY_TYPE,
    ROF_BEFORE_MATCH,
    ROF_BEFORE_NOTES,
    ROF_BEFORE_SOURCE_KEY,
)


class MarketRuleObservation(TypedDict, total=False):
    """One market-rule candidate before dry-run."""

    league: str
    sportsbook: str
    source_key: str
    source_key_type: str
    demand: int
    evidence_refs: list[str]
    match_operator: str
    market_group: str
    live_optic_market_ids: set[str]
    action: str
    notes: str
    line_offset: float | None
    yes_side: str | None
    side_swap: bool | None
    official_description: str | None
    citation_url: str | None
    canonical_market_type: str
    flip_ignore: bool


_BOOK = "polymarket_usa"
_LEAGUE = "ufc"
_EVIDENCE = "combat_usa:rof-before-rN"


def rof_before_ignore_observation() -> MarketRuleObservation:
    """The phase-1 ignore. Canonical stays null until Optic ids are confirmed."""
    return {
        "league": _LEAGUE,
        "sportsbook": _BOOK,
        "source_key": ROF_BEFORE_SOURCE_KEY,
        "source_key_type": ROF_BEFORE_KEY_TYPE,
        "match_operator": ROF_BEFORE_MATCH,
        "action": "ignore",
        "notes": ROF_BEFORE_NOTES,
        "evidence_refs": [_EVIDENCE],
        "demand": 0,
    }


def mentions_rof_before(league: str, book: str, market: str) -> bool:
    """True when Chat named this UFC Polymarket US suffix family."""
    text = market.casefold()
    if league != _LEAGUE or book != _BOOK or not text:
        return False
    return "rof-before" in text or ("rof" in text and "before" in text)


def harvest_rof_before_ignore(
    store: Any,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
) -> None:
    """Draft the ignore even when RFQ inventory is empty."""
    drafted: list[dict[str, Any]] = []
    draft_ignore_market_rule(
        store, rof_before_ignore_observation(), drafted, skipped, set(),
    )
    pins.extend(drafted)


def draft_ignore_market_rule(
    store: Any,
    obs: MarketRuleObservation,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str, str]],
) -> None:
    """Dry-run one ignore. A live ignore is skipped. A prior map may be replaced."""
    league, book, key_type, key = _identity(obs)
    if not (league and book and key_type and key):
        skipped.append(_skip(obs, "incomplete"))
        return
    loaded = _loaded(store, obs, league, book, skipped)
    if loaded is None:
        return
    rules = loaded
    if _already_ignored(rules, book, key_type, key):
        skipped.append(_skip(obs, "already_ignored"))
        return
    identity = (league, book, key_type, key)
    if identity in seen:
        return
    rule_pins = [_ignore_pin(obs)]
    dry = _dry_run(store, league, rule_pins)
    if not dry.get("ok"):
        detail = ";".join(dry.get("blockers") or [])[:120]
        skipped.append(_skip(obs, "dry_run_blocked", detail=detail))
        return
    seen.add(identity)
    pins.append(_pin_payload(league, rule_pins, obs))


def _loaded(
    store: Any,
    obs: MarketRuleObservation,
    league: str,
    book: str,
    skipped: list[dict[str, str]],
) -> list[Any] | None:
    """Tip rules once the league and book are on the tip.

    A league that is not on this store is a no-op. Other harvests must not
    see a skip row for a class they were not walking.
    """
    if not is_name_match_book(book) and book != "novig":
        skipped.append(_skip(obs, "not_name_match_book"))
        return None
    loaded = effective_league_cfg(store, league)
    if loaded is None:
        return None
    _cfg, league_row, rules = loaded
    if not book_enabled(league_row, book):
        return None
    return rules


def _already_ignored(rules: list[Any], book: str, key_type: str, key: str) -> bool:
    prior = tip_market_rule(
        rules, sportsbook=book, source_key_type=key_type, source_key=key,
    )
    return prior is not None and str(prior.action or "") == "ignore"


def obs_text(obs: MarketRuleObservation, key: str) -> str | None:
    """Blank official text stays null. It is not stored inside notes."""
    raw = obs.get(key)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _ignore_pin(obs: MarketRuleObservation) -> dict[str, Any]:
    """One ignore pin. Canonical stays null. Columns pass through when set."""
    return stamp_official_rule(MarketRulePin(
        sportsbook=str(obs.get("sportsbook") or "").strip().lower(),
        rule_kind="taxonomy",
        source_key_type=str(obs.get("source_key_type") or "").strip(),
        source_key=str(obs.get("source_key") or "").strip(),
        action="ignore",
        canonical_market_type=None,
        league=str(obs.get("league") or "").strip(),
        match_operator=str(obs.get("match_operator") or "exact"),
        notes=obs_text(obs, "notes"),
        line_offset=obs.get("line_offset"),
        yes_side=obs_text(obs, "yes_side"),
        side_swap=obs.get("side_swap"),
        official_description=obs_text(obs, "official_description"),
        citation_url=obs_text(obs, "citation_url"),
    ).model_dump(mode="json"))


def _dry_run(store: Any, league: str, rule_pins: list[dict[str, Any]]) -> dict[str, Any]:
    payload = MappingMarketRulesPayload(
        league=league,
        rules=[MarketRulePin.model_validate(pin) for pin in rule_pins],
    )
    rid = getattr(store, "current_rule_set_id", None)
    leagues = list(store.leagues_for(rid)) if rid else []
    tip_rules = list(store.market_rules_for(rid)) if rid else []
    return thin_dry_run_market_rules(leagues, tip_rules, payload)


def _pin_payload(
    league: str,
    rule_pins: list[dict[str, Any]],
    obs: MarketRuleObservation,
) -> dict[str, Any]:
    refs = [str(item) for item in (obs.get("evidence_refs") or []) if item]
    return {
        "kind": "mapping_market_rules",
        "league": league,
        "rules": rule_pins,
        "evidence_refs": refs,
    }


def _identity(obs: MarketRuleObservation) -> tuple[str, str, str, str]:
    return (
        str(obs.get("league") or "").strip(),
        str(obs.get("sportsbook") or "").strip().lower(),
        str(obs.get("source_key_type") or "").strip(),
        str(obs.get("source_key") or "").strip(),
    )


def _skip(
    obs: MarketRuleObservation,
    reason: str,
    *,
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
    if detail:
        row["detail"] = detail
    return row
