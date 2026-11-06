"""Gap leaderboard: resolve one grouped SQL row to league / fixture / kickoff / fix link.

Each venue names things differently; this is the only place that knows how:

* **kalshi** - ``league_hint`` is the series (``KXNHLGAME``), shown as-is: the tip
  carries no Kalshi series, so it never resolves to a tip league. Fixture is the
  event-ticker tail (``26SEP26ANALA``), kickoff day parsed from it.
* **polymarket_usa** - ``league_hint`` is the slug's inner US code (``mlb``),
  matched to the tip league whose polymarket_usa pin carries it. Kickoff day is
  the slug date.
* **crypto** - ``league_hint`` is crypto.com ``meta_league``; tip status is the
  Venue gaps league status. Kickoff and fixture name come from the catalogue.
* **dkex** - ``league_hint`` is the ticker's league token (``NFL``), matched to
  the tip league whose DKEX pin carries it. Fixture is the competition handle;
  no kickoff.
* **underdog** - ``league_hint`` is the UDX venue token (``NFL``); its leagues are
  code-owned (``VENUE_TOKEN_TO_LEAGUE_SLUG``). Fixture is teams + day
  (``CHIATL26OCT18``), kickoff day parsed from it.
* **novig / px / sxbet** - legs carry opaque ids only; no league, no kickoff.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlencode

from mappers.control_plane.console_fixture_phase import row_phase_from_ttko
from mappers.control_plane.console_unmapped import _as_utc, _ttko_hours
from mappers.control_plane.console_venue_gaps_league import crypto_league_index, league_status
from mappers.control_plane.entry import league_label
from mappers.control_plane.gap_fix_dkex_leagues import dkex_venue_token
from mappers.control_plane.gap_inventory import _kickoff_date
from mappers.control_plane.underdog_legacy_vocab import VENUE_TOKEN_TO_LEAGUE_SLUG
from mappers.seed.poly_usa_exchange import us_league_code

PLATFORM_LABELS: dict[str, str] = {
    "kalshi": "Kalshi",
    "polymarket_usa": "Polymarket US",
    "crypto": "crypto.com",
    "novig": "Novig",
    "px": "ProphetX",
    "dkex": "DraftKings Exchange",
    "underdog": "Underdog",
    "sxbet": "SX Bet",
}
UNRESOLVED = "(unresolved)"
_SLUG_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})$")
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_UDX_DAY = re.compile(r"(\d{2})(" + "|".join(_MONTHS) + r")(\d{2})$")


def build_indexes(store: Any | None) -> dict[str, Any]:
    """Tip lookups used to resolve every venue's league hint (built once per request)."""
    poly_us: dict[str, tuple[str, str]] = {}
    dkex: dict[str, tuple[str, str]] = {}
    sports: dict[str, str] = {}
    rid = getattr(store, "current_rule_set_id", None) if store is not None else None
    if rid and store is not None and hasattr(store, "leagues_for"):
        for row in store.leagues_for(rid):
            code = us_league_code(row).lower()
            if code and code not in poly_us:
                poly_us[code] = (str(row.league), str(row.sport or ""))
            token = dkex_venue_token(row)
            if token and token not in dkex:
                dkex[token] = (str(row.league), str(row.sport or ""))
            sports.setdefault(str(row.league), str(row.sport or ""))
    return {"crypto": crypto_league_index(store), "poly_us": poly_us, "dkex": dkex, "sports": sports}


def resolve_league(book: str, hint: str, indexes: dict[str, Any]) -> dict[str, Any]:
    """``{key, label, tip_league, sport, in_tip}`` for one venue league hint."""
    tip: tuple[str, str] | None = None
    if book == "polymarket_usa" and hint:
        tip = indexes["poly_us"].get(hint.lower())
    elif book == "crypto" and hint:
        status = league_status(hint, "", indexes["crypto"])
        if status["status"] == "in_tip" and status["league"]:
            tip = (str(status["league"]), str(status["sport"] or ""))
    elif book == "dkex" and hint:
        tip = indexes.get("dkex", {}).get(hint.upper())
    elif book == "underdog" and hint:
        slug = VENUE_TOKEN_TO_LEAGUE_SLUG.get(hint.upper())
        if slug:
            tip = (slug, indexes.get("sports", {}).get(slug, ""))
    if tip is not None:
        slug, sport = tip
        return {
            "key": f"{book}:{slug}",
            "label": league_label(slug),
            "tip_league": slug,
            "sport": sport or None,
            "in_tip": True,
            "hint": hint,
        }
    shown = hint or UNRESOLVED
    return {"key": f"{book}:~{shown}", "label": shown, "tip_league": None, "sport": None, "in_tip": False, "hint": hint}


def fixture_kickoff(book: str, row: dict[str, Any]) -> tuple[datetime | None, bool]:
    """Kickoff for a fixture row and whether it is a date only (no time of day)."""
    start = _as_utc(row.get("start_at"))
    if start is not None:
        return start, False
    key = str(row.get("fixture_key") or "")
    day: date | None = None
    if book == "kalshi":
        day = _kickoff_date("kalshi", f"{row.get('league_hint') or ''}-{key}")
    elif book == "polymarket_usa":
        matched = _SLUG_DATE.search(key)
        if matched:
            try:
                day = date(int(matched.group(1)), int(matched.group(2)), int(matched.group(3)))
            except ValueError:
                day = None
    elif book == "underdog":
        matched = _UDX_DAY.search(key)
        if matched:
            try:
                day = date(2000 + int(matched.group(1)), _MONTHS.index(matched.group(2)) + 1, int(matched.group(3)))
            except ValueError:
                day = None
    if day is None:
        return None, False
    return datetime(day.year, day.month, day.day, 23, 59, tzinfo=UTC), True


def fixture_name(book: str, row: dict[str, Any]) -> str:
    """Human label for a fixture row."""
    name = str(row.get("fixture_name") or "").strip()
    if name:
        return name
    key = str(row.get("fixture_key") or "")
    if book == "novig":
        return f"Novig market {key[:8]}" if key else UNRESOLVED
    if book == "px":
        return f"ProphetX event {key}" if key else UNRESOLVED
    if book == "dkex":
        return f"DraftKings event {key}" if key else UNRESOLVED
    if book == "sxbet":
        return f"SX market {key[:10]}" if key else UNRESOLVED
    return key or UNRESOLVED


def fix_link(book: str, fixture_key: str, ttko: float | None, market: str | None = None) -> str | None:
    """Console URL that fixes this row; None where no page inventories the venue yet."""
    phase = row_phase_from_ttko(ttko)
    if book == "crypto":
        params: dict[str, str] = {"q": fixture_key, "phase": phase}
        if market:
            params["market"] = market
        return f"/venue-gaps?{urlencode(params)}"
    if book in {"kalshi", "sxbet"}:
        return f"/unmapped?{urlencode({'platform': book, 'q': fixture_key, 'phase': phase})}"
    return None


def kickoff_fields(book: str, row: dict[str, Any]) -> dict[str, Any]:
    """``start_date`` / ``ttko_hours`` / ``kickoff_date_only`` for a fixture payload."""
    start, date_only = fixture_kickoff(book, row)
    return {
        "start_date": start.isoformat() if start else None,
        "ttko_hours": _ttko_hours(start),
        "kickoff_date_only": date_only,
    }
