"""Tip-league status for a crypto.com ``meta_league`` + Editor prefill to fix it."""

from __future__ import annotations

import copy
from typing import Any

from mappers.control_plane.chat_profiles import parser_profile
from mappers.control_plane.entry import league_label

BOOK = "crypto.com"

# SPORTS_GROUPING → tip sport, for a brand-new league only (Editor still asks).
_SPORT_BY_GROUPING = {
    "NFL": "football",
    "CFB": "football",
    "NCAAF": "football",
    "MLB": "baseball",
    "NBA": "basketball",
    "WNBA": "basketball",
    "NCAAB": "basketball",
    "NHL": "hockey",
    "SOCCER": "soccer",
    "TENNIS": "tennis",
    "UFC": "mma",
    "MMA": "mma",
    "ESPORTS": "esports",
}


def _crypto_exchange(row: Any) -> dict[str, Any] | None:
    """The league row's crypto.com exchange pin, if any."""
    for ex in row.exchanges or []:
        if str(ex.get("sportsbook") or "").lower() == BOOK:
            return ex
    return None


def _other_book(ex: dict[str, Any]) -> bool:
    """True for exchange pins that are not crypto.com."""
    return str(ex.get("sportsbook") or "").lower() != BOOK


def _exchange_league(ex: dict[str, Any]) -> str:
    """crypto.com LEAGUE the pin reads (settings.league, else source_league_id)."""
    settings = ex.get("settings") or {}
    raw = settings.get("league") if isinstance(settings, dict) else None
    return str(raw or ex.get("source_league_id") or "").strip()


def _tip_rows(store: Any | None) -> list[Any]:
    """Live (non-tombstoned) tip league rows."""
    rid = getattr(store, "current_rule_set_id", None) if store is not None else None
    if not rid or store is None or not hasattr(store, "leagues_for"):
        return []
    return [row for row in store.leagues_for(rid) if not getattr(row, "tombstone", False)]


def crypto_league_index(store: Any | None) -> dict[str, Any]:
    """``meta_league`` (casefold) → tip rows pinning it, plus slug/label lookup."""
    by_meta: dict[str, list[Any]] = {}
    by_name: dict[str, Any] = {}
    for row in _tip_rows(store):
        by_name.setdefault(str(row.league).casefold(), row)
        by_name.setdefault(league_label(str(row.league)).casefold(), row)
        ex = _crypto_exchange(row)
        if ex is None:
            continue
        meta = _exchange_league(ex).casefold()
        if meta:
            by_meta.setdefault(meta, []).append(row)
    for rows in by_meta.values():
        rows.sort(key=lambda r: str(r.league))
    return {"by_meta": by_meta, "by_name": by_name}


def _pin_enabled(row: Any) -> bool:
    """League and its crypto.com pin are both on."""
    ex = _crypto_exchange(row)
    return bool(row.enabled) and ex is not None and ex.get("enabled", True) is not False


def _crypto_pin(meta_league: str, sport_grouping: str, base: dict[str, Any] | None) -> dict[str, Any]:
    """crypto.com exchange pin for ``meta_league``, keeping any existing settings."""
    pin = copy.deepcopy(base) if base else {}
    settings = dict(pin.get("settings") or {})
    settings["league"] = meta_league
    if sport_grouping and not settings.get("sport_grouping"):
        settings["sport_grouping"] = sport_grouping
    pin.update(
        {
            "sportsbook": BOOK,
            "enabled": True,
            "parser_profile": pin.get("parser_profile") or parser_profile(BOOK),
            "source_league_id": pin.get("source_league_id") or meta_league,
            "settings": settings,
        }
    )
    return pin


def _amend_state(row: Any, meta_league: str, sport_grouping: str) -> dict[str, Any]:
    """Editor state amending ``row`` with an enabled crypto.com pin."""
    exchanges = [copy.deepcopy(ex) for ex in row.exchanges or [] if _other_book(ex)]
    exchanges.append(_crypto_pin(meta_league, sport_grouping, _crypto_exchange(row)))
    return {
        "tab": "league",
        "mode": "amend",
        "league": row.league,
        "sport": row.sport,
        "optic_league_id": row.optic_league_id,
        "fixture_source": row.fixture_source,
        "fixture_horizon_hours": row.fixture_horizon_hours,
        "enabled": True,
        "exchanges": exchanges,
        "focusSportsbook": BOOK,
    }


def _create_state(meta_league: str, sport_grouping: str) -> dict[str, Any]:
    """Editor state for a new league carrying only the crypto.com pin."""
    return {
        "tab": "league",
        "mode": "create",
        "sport": _SPORT_BY_GROUPING.get(sport_grouping.upper(), ""),
        "fixture_source": "api",
        "enabled": True,
        "exchanges": [_crypto_pin(meta_league, sport_grouping, None)],
        "focusSportsbook": BOOK,
    }


def league_status(meta_league: str, sport_grouping: str, index: dict[str, Any]) -> dict[str, Any]:
    """``{status, league, league_label, sport, fix}`` for one catalogue league.

    ``status``: ``in_tip`` (a tip league pins it, enabled), ``disabled`` (pinned
    but the league or its crypto.com exchange is off), ``not_in_tip``. ``fix`` is
    the Editor league-form state (router ``location.state``) that closes the gap.
    """
    meta = meta_league.strip()
    rows = index["by_meta"].get(meta.casefold()) or []
    live = [row for row in rows if _pin_enabled(row)]
    if live:
        return _status("in_tip", live[0], None, candidates=[r.league for r in live])
    if rows:
        return _status("disabled", rows[0], _amend_state(rows[0], meta, sport_grouping))
    named = index["by_name"].get(meta.casefold())
    if named is not None:
        return _status("not_in_tip", named, _amend_state(named, meta, sport_grouping))
    return {
        "status": "not_in_tip",
        "league": None,
        "league_label": None,
        "sport": _SPORT_BY_GROUPING.get(sport_grouping.upper()) or None,
        "candidates": [],
        "fix": {"action": "create", "entry_state": _create_state(meta, sport_grouping)},
    }


def _status(
    status: str,
    row: Any,
    entry_state: dict[str, Any] | None,
    *,
    candidates: list[str] | None = None,
) -> dict[str, Any]:
    """Status dict for a tip row, with an optional Editor fix."""
    fix = {"action": "amend", "entry_state": entry_state} if entry_state else None
    return {
        "status": status,
        "league": row.league,
        "league_label": league_label(str(row.league)),
        "sport": row.sport or None,
        "candidates": candidates or [row.league],
        "fix": fix,
    }
