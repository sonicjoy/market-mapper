"""Official Path 2 name-overlay harvest (polymarket / name on existing Optic entities).

When a prefix is already wired, unique_optic_for_questions is silent. Live
classify still misses when Poly question names do not contain Optic display
names (Leipzig / Gladbach, reverse tennis, apostrophe, Optic birth year).
Draft overlays when both sides uniquely bind by yearless/folded tokens among
that league's date±1 slate. Exact already-mapped names stay silent. Collision
on a key skips that key. A unique surname in the window is not a person bind
when given names disagree. Missing > wrong.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from mappers.alias_kinds import optic_pin
from mappers.canonical_codes import school_marks
from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.entity_types import match_entity_type_for_league
from mappers.control_plane.gap_fix_name_bind import (
    name_bind_keys,
    person_unique_hit_ok,
    vs_sides,
)
from mappers.control_plane.gap_fix_poly_evidence import fx_key as _fx_key
from mappers.control_plane.gap_fix_poly_evidence import poly_name_evidence
from mappers.control_plane.gap_fix_poly_leagues import official_slug_prefix
from mappers.control_plane.gap_fix_tip import (
    index_tip_leagues,
    indexed_has_poly_name,
    indexed_optic_key,
    league_tip,
)
from mappers.control_plane.poly_us_match import (
    normalize_fixture,
    shift_day,
)
from mappers.control_plane.rows import LeagueRow
from mappers.exchanges.polymarket import _norm_name
from mappers.handicap_name_crumb import is_selection_alias, is_selection_question
from mappers.seed.poly_usa_exchange import POLY_BOOK

_STYLE_DEFAULT = "mlb_suffix"
_SKIP_LEAD = ("will there", "will the ")


def draft_official_name_overlays(
    store: Any,
    key: str,
    events: list[dict[str, Any]],
    rows: list[LeagueRow],
    pins: list[dict[str, Any]],
    ctx: dict[str, Any],
) -> None:
    """Append unique polymarket/name pins for each tip league on this prefix."""
    seen: set[tuple[str, str, str]] = ctx.setdefault("seen", set())
    claimed: dict[tuple[str, str], str] = ctx.setdefault("poly_names", {})
    ctx.setdefault("tips", index_tip_leagues(store))
    for row in _wired_rows(key, rows):
        _overlay_wired_row(store, row, events, pins, ctx, seen, claimed)


def _overlay_wired_row(
    store: Any,
    row: LeagueRow,
    events: list[dict[str, Any]],
    pins: list[dict[str, Any]],
    ctx: dict[str, Any],
    seen: set[tuple[str, str, str]],
    claimed: dict[tuple[str, str], str],
) -> None:
    """Draft overlays against one wired league's Optic slate."""
    fixtures = _row_fixtures(row, ctx["fixtures"])
    if not fixtures:
        return
    style = _question_style(row)
    skipped: list[dict[str, str]] = ctx.setdefault("skipped", [])
    tips = ctx.get("tips")
    for event in events:
        pins.extend(
            _pins_for_event(
                store, row, event, fixtures, style, seen, claimed, skipped, tips,
            )
        )


def question_sides(question: str, style: str = _STYLE_DEFAULT) -> tuple[str, str] | None:
    """Two display names from a vs/beat question, else None."""
    text = _question_body(question, style)
    if not text:
        return None
    return vs_sides(text)


def significant_token(normed: str) -> str:
    """Last yearless non-particle bind key with length ≥ 4, else empty."""
    keys = name_bind_keys(normed, person=False)
    return keys[0] if keys else ""


def _pins_for_event(
    store: Any,
    row: LeagueRow,
    event: dict[str, Any],
    fixtures: list[dict[str, Any]],
    style: str,
    seen: set[tuple[str, str, str]],
    claimed: dict[tuple[str, str], str],
    skipped: list[dict[str, str]],
    tips: Any,
) -> list[dict[str, Any]]:
    """Name pins for one official event, or empty when uniqueness fails."""
    sides = question_sides(str(event.get("question") or ""), style)
    if sides is None:
        return []
    if is_selection_alias(sides[0]) or is_selection_alias(sides[1]):
        return []
    day = str(event.get("date") or "")
    window = _date_window(fixtures, day)
    if any(_pair_matches(sides[0], sides[1], fx, style) for fx in window):
        return []
    binds = unique_name_binds(sides[0], sides[1], fixtures, day, style)
    if not binds:
        skip = _ambiguous_skip(row, event, sides, window, style)
        if skip:
            skipped.append(skip)
        return []
    out: list[dict[str, Any]] = []
    for poly_name, optic_name, oid, fx in binds:
        pin = _name_pin(
            store, row, poly_name, optic_name, oid, event, fx, seen, claimed, tips,
        )
        if pin is not None:
            out.append(pin)
    return out


def _ambiguous_skip(
    row: LeagueRow,
    event: dict[str, Any],
    sides: tuple[str, str],
    window: list[dict[str, Any]],
    style: str,
) -> dict[str, str] | None:
    """AI-suggest skip when overlay uniqueness failed but Optic names exist."""
    candidates = _window_candidates(window)
    if not candidates:
        return None
    if _already_optic_name(sides[0], window, style):
        return None
    return {
        "reason": "name_ambiguous",
        "league": str(row.league),
        "title": str(event.get("question") or ""),
        "needle": sides[0],
        "alias_book": POLY_BOOK,
        "alias_value": sides[0],
        "candidates": json.dumps(candidates, separators=(",", ":")),
        "prefix": str(event.get("prefix") or ""),
    }


def _already_optic_name(needle: str, window: list[dict[str, Any]], style: str) -> bool:
    """True when the needle is already an Optic display name in the window.

    Live classify resolves those by name, so an overlay would be a no-op —
    the same rule _unmatched_pairs applies once both sides bind. Guards the
    skip path so an unparsed opposite side cannot send an intact name to AI.
    """
    return bool(_exact_index(window, style).get(_norm_name(needle, style)))


def _window_candidates(window: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Deduped Optic competitors in the date window, with fixture opponent."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in window:
        fx = normalize_fixture(raw)
        home_id = str(fx.get("home_id") or "")
        home = str(fx.get("home_name") or "")
        away_id = str(fx.get("away_id") or "")
        away = str(fx.get("away_name") or "")
        for oid, name, opp in ((home_id, home, away), (away_id, away, home)):
            if not oid or not name or oid in seen:
                continue
            seen.add(oid)
            row = {"id": oid, "name": name}
            if opp:
                row["opponent"] = opp
            out.append(row)
    return out


def unique_name_binds(
    poly_a: str,
    poly_b: str,
    fixtures: list[dict[str, Any]],
    day: str,
    style: str,
) -> list[tuple[str, str, str, dict[str, Any]]]:
    """(poly, optic display, oid, fixture) pairs that need overlay, or empty."""
    window = _date_window(fixtures, day)
    if not window:
        return []
    if any(_pair_matches(poly_a, poly_b, fx, style) for fx in window):
        return []
    index = _token_index(window, style)
    exact = _exact_index(window, style)
    bind_a = _unique_competitor(poly_a, index, exact, style)
    bind_b = _unique_competitor(poly_b, index, exact, style)
    if bind_a is None or bind_b is None:
        return []
    if bind_a["fx_id"] != bind_b["fx_id"] or bind_a["oid"] == bind_b["oid"]:
        return []
    if bind_a["side"] == bind_b["side"]:
        return []
    return _unmatched_pairs(poly_a, bind_a, poly_b, bind_b, style)


def _unmatched_pairs(
    poly_a: str,
    bind_a: dict[str, Any],
    poly_b: str,
    bind_b: dict[str, Any],
    style: str,
) -> list[tuple[str, str, str, dict[str, Any]]]:
    """Sides whose Poly display is not already the Optic name."""
    out: list[tuple[str, str, str, dict[str, Any]]] = []
    fx = bind_a.get("fx") or {}
    for poly_name, bind in ((poly_a, bind_a), (poly_b, bind_b)):
        optic_name = bind["name"]
        if _norm_name(poly_name, style) == _norm_name(optic_name, style):
            continue
        out.append((poly_name, optic_name, bind["oid"], dict(fx)))
    return out


def _unique_competitor(
    poly_name: str,
    index: dict[str, list[dict[str, Any]]],
    exact: dict[str, list[dict[str, Any]]],
    style: str,
) -> dict[str, Any] | None:
    """Sole date-window competitor: exact _norm_name, else unique bind keys."""
    hits = exact.get(_norm_name(poly_name, style)) or []
    oids = {row["oid"] for row in hits}
    if len(oids) == 1:
        return hits[0]
    person = style == "tennis_prefix"
    for key in name_bind_keys(poly_name, person=person):
        hits = index.get(key) or []
        oids = {row["oid"] for row in hits}
        if len(oids) != 1:
            continue
        row = hits[0]
        chosen = str(row["name"])
        if person and not person_unique_hit_ok(poly_name, chosen):
            continue
        if person or school_marks(poly_name) == school_marks(chosen):
            return row
    return None


def _exact_index(
    window: list[dict[str, Any]],
    style: str,
) -> dict[str, list[dict[str, Any]]]:
    """Normalized Optic display name → competitor rows in the date window."""
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in window:
        fx = normalize_fixture(raw)
        for side, oid, name in (
            ("home", str(fx["home_id"]), str(fx["home_name"])),
            ("away", str(fx["away_id"]), str(fx["away_name"])),
        ):
            if not oid:
                continue
            row = {
                "oid": oid,
                "name": name,
                "side": side,
                "fx_id": _fx_key(fx),
                "fx": fx,
            }
            buckets[_norm_name(name, style)].append(row)
    return dict(buckets)


def _token_index(
    window: list[dict[str, Any]],
    style: str,
) -> dict[str, list[dict[str, Any]]]:
    """Bind key → competitor rows in the date window."""
    person = style == "tennis_prefix"
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in window:
        fx = normalize_fixture(raw)
        for side, oid, name in (
            ("home", str(fx["home_id"]), str(fx["home_name"])),
            ("away", str(fx["away_id"]), str(fx["away_name"])),
        ):
            if not oid:
                continue
            row = {
                "oid": oid,
                "name": name,
                "side": side,
                "fx_id": _fx_key(fx),
                "fx": fx,
            }
            for key in name_bind_keys(name, person=person):
                buckets[key].append(row)
    return dict(buckets)


def _pair_matches(poly_a: str, poly_b: str, fx: dict[str, Any], style: str) -> bool:
    """True when both Poly displays already equal the Optic names (or flipped)."""
    home = _norm_name(str(normalize_fixture(fx).get("home_name") or ""), style)
    away = _norm_name(str(normalize_fixture(fx).get("away_name") or ""), style)
    a, b = _norm_name(poly_a, style), _norm_name(poly_b, style)
    return (a == home and b == away) or (a == away and b == home)


def _date_window(fixtures: list[dict[str, Any]], day: str) -> list[dict[str, Any]]:
    """Fixtures on ``day`` ± 1."""
    dates = {day[:10], shift_day(day[:10], -1), shift_day(day[:10], 1)}
    dates.discard("")
    return [fx for fx in fixtures if str(normalize_fixture(fx).get("d") or "") in dates]


def _name_pin(
    store: Any,
    row: LeagueRow,
    poly_name: str,
    optic_name: str,
    oid: str,
    event: dict[str, Any],
    fx: dict[str, Any],
    seen: set[tuple[str, str, str]],
    claimed: dict[tuple[str, str], str],
    tips: Any,
) -> dict[str, Any] | None:
    """One polymarket/name pin on the sole Optic owner, or None."""
    if is_selection_alias(poly_name):
        return None
    league = str(row.league)
    indexed = league_tip(store, league, tips)
    canonical = indexed_optic_key(indexed, oid)
    if not canonical or indexed_has_poly_name(indexed, canonical, poly_name):
        return None
    seen_key = (league, canonical, poly_name.casefold())
    if seen_key in seen:
        return None
    claim_key = (league, poly_name.casefold())
    taken = claimed.get(claim_key)
    if taken and taken != canonical:
        return None
    claimed[claim_key] = canonical
    seen.add(seen_key)
    want = match_entity_type_for_league(store, league)
    entity_type = indexed.types.get(canonical, "") or want
    if entity_type not in ("team", "player", "fighter"):
        entity_type = want
    display = indexed.names.get(canonical) or optic_name
    return alias_payload(
        league, canonical, display, entity_type,
        [
            {"sportsbook": POLY_BOOK, "alias_kind": "name", "alias_value": poly_name},
            optic_pin(oid),
        ],
        poly_name_evidence(row, event, oid, optic_name, poly_name, fx),
    )


def _wired_rows(key: str, rows: list[LeagueRow]) -> list[LeagueRow]:
    """Tip leagues publishing this official prefix (itf men+women share itf)."""
    return [row for row in rows if official_slug_prefix(row).casefold() == key]


def _question_body(question: str, style: str) -> str:
    """Strip tennis tournament prefix; drop lead-in props."""
    text = (question or "").strip()
    if not text or is_selection_question(text):
        return ""
    if any(text.casefold().startswith(lead) for lead in _SKIP_LEAD):
        return ""
    if style == "tennis_prefix" and ":" in text:
        return text.rsplit(":", 1)[-1].strip()
    return text


def _row_fixtures(row: LeagueRow, by_optic: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Optic window rows for this league's primary + extra Optic ids."""
    out: list[dict[str, Any]] = []
    for oid in [str(row.optic_league_id or "").strip(), *list(row.extra_optic_league_ids or [])]:
        if oid:
            out.extend(by_optic.get(oid) or [])
    return out


def _question_style(row: LeagueRow) -> str:
    """Official Polymarket question_style, or mlb_suffix."""
    for ex in row.exchanges or []:
        if str(ex.get("sportsbook") or "") != POLY_BOOK:
            continue
        settings = ex.get("settings") or {}
        if not isinstance(settings, dict):
            continue
        style = str(settings.get("question_style") or "").strip()
        if style:
            return style
    return _STYLE_DEFAULT
