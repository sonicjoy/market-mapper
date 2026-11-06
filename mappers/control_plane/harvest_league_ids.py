"""Live harvest of exchange source_league_id / settings for league onboard."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mappers.control_plane.harvest_league_ids_common import (
    exchange_pin_on_tip,
    fetch_league_fixtures,
    wired_probe_row,
)
from mappers.control_plane.harvest_league_ids_live import (
    harvest_crypto_meta,
    harvest_dkex_league,
    harvest_novig_league,
    harvest_poly_usa_code,
    harvest_polymarket_prefix,
    harvest_px_tournament,
    harvest_underdog_league,
)
from mappers.seed.poly_usa_exchange import POLY_USA_BOOK
from mappers.shared import FIXTURE_HORIZON_HOURS

FixturesFn = Callable[..., list[dict[str, Any]]]

_PROBE_BOOKS = (
    "crypto.com",
    "optic",
    "polymarket",
    "polymarket_usa",
    "px",
    "novig",
    "underdog",
    "dkex",
)

_HARVEST_LABELS = {
    "crypto.com": "Retrieving league id…",
    "optic": "Retrieving league id…",
    "polymarket": "Retrieving league id…",
    "polymarket_usa": "Retrieving league code…",
    "px": "Retrieving tournament id…",
    "novig": "Retrieving league string…",
    "underdog": "Retrieving venue league…",
    "dkex": "Retrieving venue league…",
}


def harvest_loading_label(sportsbook: str) -> str:
    """Editor spinner copy for one book."""
    return _HARVEST_LABELS.get(sportsbook.strip().lower(), "Retrieving id…")


def exchange_source_on_tip(row: Any, sportsbook: str) -> str:
    """Non-empty source id already on a tip league row for this book."""
    pin = exchange_pin_on_tip(row, sportsbook)
    if pin is None:
        return ""
    return str(pin.get("source_league_id") or "").strip()


def harvest_exchange_source_id(
    store: Any,
    *,
    league: str,
    sport: str,
    optic_league_id: str,
    sportsbook: str,
    fixture_horizon_hours: float | None = None,
    fixtures_fn: FixturesFn | None = None,
) -> dict[str, Any]:
    """Probe one book for a unique source id; never invent when ambiguous."""
    book = sportsbook.strip().lower()
    optic = optic_league_id.strip()
    if book not in _PROBE_BOOKS:
        return {"ok": False, "book": book, "evidence": False, "error": "unknown sportsbook"}
    horizon = float(fixture_horizon_hours or FIXTURE_HORIZON_HOURS)
    fixtures, fetch_error = fetch_league_fixtures(optic, horizon, fixtures_fn)
    if book == "optic":
        return _attach_settings(_optic_result(optic, fixtures, fetch_error))
    if fetch_error and not fixtures:
        return {
            "ok": False,
            "book": book,
            "evidence": False,
            "error": f"optic fixtures: {fetch_error}",
        }
    if book == "polymarket":
        return _attach_settings(harvest_polymarket_prefix(optic, fixtures))
    if book == "crypto.com":
        return _attach_settings(harvest_crypto_meta(league, optic, fixtures, sport=sport))
    if book == POLY_USA_BOOK:
        return _attach_settings(harvest_poly_usa_code(league, optic, sport, fixtures, store))
    if book == "px":
        return _attach_settings(harvest_px_tournament(league, optic, sport, fixtures))
    if book == "novig":
        return _attach_settings(harvest_novig_league(league, optic, fixtures))
    if book == "underdog":
        return _attach_settings(harvest_underdog_league(league, optic, fixtures))
    if book == "dkex":
        return _attach_settings(harvest_dkex_league(league, optic, fixtures))
    return {"ok": False, "book": book, "evidence": False, "error": "unknown sportsbook"}


def harvest_exchange_batch(
    store: Any,
    *,
    league: str,
    sport: str,
    optic_league_id: str,
    sportsbooks: Sequence[str],
    fixture_horizon_hours: float | None = None,
    fixtures_fn: FixturesFn | None = None,
    skip_wired: bool = True,
) -> list[dict[str, Any]]:
    """Harvest many books; optionally skip tip rows that already have an id."""
    slug = league.strip()
    optic = optic_league_id.strip()
    tip_row = _tip_row(store, slug)
    out: list[dict[str, Any]] = []
    for book in sportsbooks:
        name = book.strip().lower()
        if skip_wired and tip_row is not None:
            wired = wired_probe_row(tip_row, name)
            if wired is not None:
                out.append(wired)
                continue
        out.append(
            harvest_exchange_source_id(
                store,
                league=slug,
                sport=sport,
                optic_league_id=optic,
                sportsbook=name,
                fixture_horizon_hours=fixture_horizon_hours,
                fixtures_fn=fixtures_fn,
            )
        )
    return out


def harvest_league_exchange_for_entry(
    store: Any,
    *,
    league: str,
    sport: str,
    optic_league_id: str,
    sportsbook: str,
    fixture_horizon_hours: float | None = None,
) -> dict[str, Any]:
    """Editor single-book harvest: wired tip row first, else live scrape."""
    book = sportsbook.strip().lower()
    rows = harvest_exchange_batch(
        store,
        league=league,
        sport=sport,
        optic_league_id=optic_league_id,
        sportsbooks=[book],
        fixture_horizon_hours=fixture_horizon_hours,
        skip_wired=True,
    )
    if not rows:
        return {"ok": False, "book": book, "evidence": False}
    return _attach_settings(rows[0])


def _tip_row(store: Any, league: str) -> Any | None:
    rid = getattr(store, "current_rule_set_id", None)
    if not rid:
        return None
    for row in store.leagues_for(rid):
        if str(row.league) == league:
            return row
    return None


def _attach_settings(out: dict[str, Any]) -> dict[str, Any]:
    """Mirror harvest source ids into settings keys classify reads."""
    book = str(out.get("book") or "").strip().lower()
    settings = dict(out.get("settings") or {})
    source = str(out.get("source") or "").strip()
    if book in {"polymarket", POLY_USA_BOOK} and not settings.get("slug_prefix"):
        slug = str(out.get("slug_prefix") or source).strip()
        if slug:
            settings["slug_prefix"] = slug
    if book == "novig" and not settings.get("league"):
        code = str(out.get("league") or source).strip()
        if code:
            settings["league"] = code
    if book == "underdog" and not settings.get("league"):
        code = str(out.get("league") or source).strip().upper()
        if code:
            settings["league"] = code
    if book == "dkex" and not settings.get("league"):
        code = str(out.get("league") or source).strip().upper()
        if code:
            settings["league"] = code
    if book == "crypto.com":
        for key in ("league", "sport_grouping"):
            val = str((out.get("settings") or {}).get(key) or settings.get(key) or "").strip()
            if val:
                settings[key] = val
    if book == "px" and settings.get("tournament_id") is None:
        tid = out.get("tournament_id")
        if tid is None and source:
            try:
                tid = int(source)
            except ValueError:
                tid = None
        if tid is not None:
            settings["tournament_id"] = tid
    if settings:
        out["settings"] = settings
    return out


def _optic_result(
    optic_league_id: str,
    fixtures: list[dict[str, Any]],
    fetch_error: str | None,
) -> dict[str, Any]:
    if not optic_league_id:
        return {
            "ok": False,
            "book": "optic",
            "evidence": False,
            "note": "optic_league_id required",
        }
    if fetch_error and not fixtures:
        return {
            "ok": False,
            "book": "optic",
            "evidence": False,
            "error": f"optic fixtures: {fetch_error}",
        }
    return {
        "ok": True,
        "book": "optic",
        "evidence": True,
        "source": optic_league_id,
        "fixture_count": len(fixtures),
        "note": "no fixtures in horizon" if not fixtures else "",
    }
