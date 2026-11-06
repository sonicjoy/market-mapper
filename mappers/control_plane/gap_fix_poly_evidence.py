"""Review evidence refs for Polymarket name-overlay pins.

Split out of gap_fix_poly_names so the binding logic and the ref formatting
each stay under the file size gate. Leaf of that module: it never imports
back.
"""

from __future__ import annotations

from typing import Any

from mappers.control_plane.entry import league_label
from mappers.control_plane.evidence_format import optic_competitor_ref, optic_fixture_ref
from mappers.control_plane.poly_us_match import normalize_fixture
from mappers.control_plane.rows import LeagueRow


def fx_key(fx: dict[str, Any]) -> str:
    """Stable fixture identity without requiring a BQ fixture id."""
    return f"{fx.get('d')}|{fx.get('home_id')}|{fx.get('away_id')}"


def poly_name_evidence(
    row: LeagueRow,
    event: dict[str, Any],
    oid: str,
    optic_name: str,
    poly_name: str,
    fx: dict[str, Any],
) -> list[str]:
    """Source sport/league/market plus Optic fixture for Review."""
    refs = [*_source_refs(row, event, poly_name), *_match_refs(fx, oid, optic_name)]
    return list(dict.fromkeys(r for r in refs if r))


def _source_refs(row: LeagueRow, event: dict[str, Any], poly_name: str) -> list[str]:
    """Sport, league, slug, question, market, and the Poly display name."""
    refs: list[str] = []
    sport = str(row.sport or event.get("sport") or "").strip()
    if sport:
        refs.append(f"source:sport:{sport}")
    slug = str(row.league or "").strip()
    if slug:
        refs.append(f"source:league:{league_label(slug)} ({slug})")
    question = str(event.get("question") or "").strip()
    market_slug = str(event.get("slug") or "").strip()
    if market_slug:
        refs.append(f"gap:{market_slug}")
        refs.append(f"polymarket:slug:{market_slug}")
    else:
        prefix = str(event.get("prefix") or "").strip()
        day = str(event.get("date") or "").strip()
        if prefix or day:
            refs.append(f"gap:poly-name:{prefix}:{day}")
    if question:
        refs.append(f"polymarket:question:{question}")
        market = _market_label(question)
        if market:
            refs.append(f"polymarket:market:{market}")
    description = str(event.get("description") or "").strip()
    if description and description != question:
        refs.append(f"polymarket:description:{description}")
    day = str(event.get("date") or "").strip()[:10]
    if day:
        refs.append(f"source:date:{day}")
    outcome = str(event.get("outcome_label") or "").strip()
    if outcome:
        refs.append(f"polymarket:outcome:{outcome}")
    refs.append(f"polymarket:name:{poly_name}")
    return refs


def _match_refs(fx: dict[str, Any], oid: str, optic_name: str) -> list[str]:
    """Named Optic fixture + this competitor."""
    probe = _fixture_probe(fx)
    refs: list[str] = []
    fixture = optic_fixture_ref(probe)
    if fixture:
        refs.append(fixture)
    league_id = str(probe.get("optic_league_id") or "").strip()
    league_name = str(fx.get("optic_league_name") or "").strip()
    if league_name:
        refs.append(f"optic:league:{league_name}")
    elif league_id:
        refs.append(f"optic:id:{league_id}")
    refs.append(optic_competitor_ref(oid, optic_name))
    return [r for r in refs if r]


def _fixture_probe(fx: dict[str, Any]) -> dict[str, Any]:
    """optic_fixture_ref shape: home/away strings plus a fixture id."""
    n = normalize_fixture(fx)
    fxid = str(fx.get("fixture_id") or fx.get("id") or fx.get("game_id") or fx_key(n))
    day = str(n.get("d") or "")[:10]
    start = str(fx.get("start_date") or day)
    return {
        "fixture_id": fxid,
        "id": fxid,
        "home": str(n.get("home_name") or ""),
        "away": str(n.get("away_name") or ""),
        "start_date": start,
        "optic_league_id": str(n.get("optic_league_id") or ""),
    }


def _market_label(question: str) -> str:
    """Question suffix after ':' (O/U, spread), else moneyline."""
    if ":" in question:
        return question.split(":", 1)[1].strip()
    return "moneyline"
