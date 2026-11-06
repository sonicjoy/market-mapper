"""Optic fixture rows for the Proposed rail and Coverage explorer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def fixture_rows_from_optic(
    fixtures: list[dict[str, Any]],
    *,
    sort: bool = True,
) -> list[dict[str, Any]]:
    """Normalize Optic fixture dicts for console rail."""
    out: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    for fx in fixtures:
        fxid = str(fx.get("id") or fx.get("fixture_id") or "").strip()
        if not fxid:
            continue
        start = str(fx.get("start_date") or fx.get("commence_time") or "")
        home = _comp_name(fx, "home")
        away = _comp_name(fx, "away")
        label = f"{home} vs {away}".strip()
        ttko_hours: float | None = None
        if start:
            try:
                kick = datetime.fromisoformat(start.replace("Z", "+00:00"))
                ttko_hours = (kick - now).total_seconds() / 3600.0
            except ValueError:
                ttko_hours = None
        optic_status = str(fx.get("status") or "").strip()
        row = {
            "fixture_id": fxid,
            "label": label,
            "home": home,
            "away": away,
            "start_date": start,
            "ttko_hours": ttko_hours,
            "optic_status": optic_status or None,
            "home_competitor_ids": _comp_ids(fx, "home"),
            "away_competitor_ids": _comp_ids(fx, "away"),
            "home_abbr": _comp_abbr(fx, "home"),
            "away_abbr": _comp_abbr(fx, "away"),
        }
        gid = str(fx.get("game_id") or "").strip()
        if gid:
            row["game_id"] = gid
        out.append(row)
    if sort:
        out.sort(key=upcoming_fixture_sort_key)
    return out


def upcoming_fixture_sort_key(row: dict[str, Any]) -> tuple[bool, bool, float, str]:
    """Upcoming kickoffs first, then started, then missing kickoff."""
    ttko = row.get("ttko_hours")
    missing = not isinstance(ttko, int | float)
    started = (not missing) and float(ttko) < 0
    when = 9999.0 if missing else float(ttko)
    return (missing, started, when, str(row.get("fixture_id") or ""))


def fixture_start_sort_key(row: dict[str, Any]) -> tuple[bool, float, str]:
    """Ascending kickoff; missing start sorts last."""
    ttko = row.get("ttko_hours")
    missing = not isinstance(ttko, int | float)
    when = 9999.0 if missing else float(ttko)
    return (missing, when, str(row.get("fixture_id") or ""))


def _comp_name(fx: dict[str, Any], side: str) -> str:
    for key in (f"{side}_competitors", f"{side}_team"):
        val = fx.get(key)
        if isinstance(val, list) and val:
            return str(val[0].get("name") or val[0].get("abbreviation") or "")
        if isinstance(val, dict):
            return str(val.get("name") or val.get("abbreviation") or "")
    return str(fx.get(f"{side}_name") or "")


def _comp_ids(fx: dict[str, Any], side: str) -> list[str]:
    val = fx.get(f"{side}_competitors")
    if not isinstance(val, list):
        return []
    ids: list[str] = []
    for comp in val:
        cid = str(comp.get("id") or comp.get("competitor_id") or "").strip()
        if cid:
            ids.append(cid)
    return ids


def _comp_abbr(fx: dict[str, Any], side: str) -> str:
    for key in (f"{side}_competitors", f"{side}_team"):
        val = fx.get(key)
        if isinstance(val, list) and val:
            return str(val[0].get("abbreviation") or "").strip()
        if isinstance(val, dict):
            return str(val.get("abbreviation") or "").strip()
    return str(fx.get(f"{side}_abbr") or "").strip()


def _name_on_side(target: str, side: str) -> bool:
    """True when the Optic side name is this competitor (word-aware)."""
    if not target or not side:
        return False
    if target == side:
        return True
    return f" {target} " in f" {side} "


def attach_next_fixtures(
    rows: list[dict[str, Any]],
    fixtures_by_league: dict[str, list[dict[str, Any]]],
) -> None:
    """Fill next_fixtures on alias rows from Optic window."""
    for row in rows:
        if row.get("kind") != "alias":
            continue
        league = str(row.get("league") or "")
        target_name = str((row.get("target") or {}).get("name") or "").lower()
        matched: list[dict[str, Any]] = []
        for fx in fixtures_by_league.get(league) or []:
            home = str(fx.get("home") or "").lower()
            away = str(fx.get("away") or "").lower()
            if _name_on_side(target_name, home) or _name_on_side(target_name, away):
                matched.append(fx)
        row["next_fixtures"] = matched[:3]
        _fill_optic_abbr(row, matched)


def _fill_optic_abbr(row: dict[str, Any], matched: list[dict[str, Any]]) -> None:
    """Copy the fixture-side abbreviation onto an Optic pin when harvest omitted it."""
    if str(row.get("sportsbook") or "").lower() != "optic":
        return
    target = row.get("target")
    source = row.get("source")
    if not isinstance(target, dict) or str(target.get("abbr") or "").strip():
        return
    name = str(target.get("name") or "").lower()
    for fx in matched:
        abbr = _abbr_on_named_side(fx, name)
        if not abbr:
            continue
        target["abbr"] = abbr
        if isinstance(source, dict) and not str(source.get("abbr") or "").strip():
            source["abbr"] = abbr
        return


def _abbr_on_named_side(fx: dict[str, Any], name: str) -> str:
    """Optic abbreviation for the fixture side that matches this name."""
    if _name_on_side(name, str(fx.get("home") or "").lower()):
        return str(fx.get("home_abbr") or "").strip()
    if _name_on_side(name, str(fx.get("away") or "").lower()):
        return str(fx.get("away_abbr") or "").strip()
    return ""


def rail_fixtures_for_rows(
    league_rows: list[dict[str, Any]],
    league_fixtures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep only fixtures that pending alias pins would unblock."""
    wanted = {
        str(fx.get("fixture_id") or "")
        for row in league_rows
        if row.get("kind") == "alias"
        for fx in (row.get("next_fixtures") or [])
    }
    wanted.discard("")
    return [fx for fx in league_fixtures if str(fx.get("fixture_id") or "") in wanted]
