"""Match Polymarket US events (typed team abbreviations) onto Optic fixtures."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from mappers.canonical_codes import names_fit, person_league, school_marks
from mappers.control_plane.gap_fix_name_bind import unique_side, vs_sides
from mappers.poly_usa_code_bind import unique_code_side as _bind_code_side


def shift_day(day: str, days: int) -> str:
    """ISO date plus ``days``, or empty when ``day`` is not YYYY-MM-DD."""
    parts = day.split("-")
    if len(parts) != 3:
        return ""
    try:
        y, m, d = (int(p) for p in parts)
        return (date(y, m, d) + timedelta(days=days)).isoformat()
    except ValueError:
        return ""


def fixture_date(fx: dict[str, Any]) -> str:
    """Calendar day from a BQ row (``d``) or Optic API ``start_date``."""
    raw = fx.get("d")
    if raw:
        return str(raw)[:10]
    start = str(fx.get("start_date") or "")
    return start[:10]


def fixture_sides(fx: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    """home_id, home_abbr, home_name, away_id, away_abbr, away_name."""
    if fx.get("home_name") is not None or fx.get("home_abbr") is not None:
        return (
            str(fx.get("home_id") or ""),
            str(fx.get("home_abbr") or ""),
            str(fx.get("home_name") or ""),
            str(fx.get("away_id") or ""),
            str(fx.get("away_abbr") or ""),
            str(fx.get("away_name") or ""),
        )
    home = (fx.get("home_competitors") or [{}])
    away = (fx.get("away_competitors") or [{}])
    home_row = home[0] if home else {}
    away_row = away[0] if away else {}
    return (
        str(home_row.get("id") or ""),
        str(home_row.get("abbreviation") or ""),
        str(home_row.get("name") or ""),
        str(away_row.get("id") or ""),
        str(away_row.get("abbreviation") or ""),
        str(away_row.get("name") or ""),
    )


def normalize_fixture(fx: dict[str, Any]) -> dict[str, Any]:
    """BQ or API fixture → matcher shape with ``d`` and home/away fields."""
    hid, habbr, hname, aid, aabbr, aname = fixture_sides(fx)
    return {
        **fx,
        "d": fixture_date(fx),
        "home_id": hid,
        "home_abbr": habbr,
        "home_name": hname,
        "away_id": aid,
        "away_abbr": aabbr,
        "away_name": aname,
        "optic_league_id": str(fx.get("optic_league_id") or ""),
        "sport": str(fx.get("sport") or ""),
    }


def best_fixture(
    event: dict[str, Any],
    fixtures: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Unique date±1 match by keyed names, title+codes, or a unique code pair."""
    keyed = _best_by_keyed_names(event, fixtures)
    titled = _best_by_title(event, fixtures)
    codes = _best_by_codes(event, fixtures)
    if titled is not None:
        return _pick_hit(keyed, titled, codes)
    return _pick_hit(keyed, _best_by_title_order(event, fixtures), codes)


def _best_by_codes(
    event: dict[str, Any],
    fixtures: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Unique date±1 fixture where both team codes uniquely bind, else None."""
    home = str(event.get("home") or "")
    away = str(event.get("away") or "")
    return _unique_fx_orient(
        event, fixtures, lambda fx: _orient_by_codes(home, away, fx, leftover=False),
    )


def _best_by_keyed_names(
    event: dict[str, Any],
    fixtures: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Unique date±1 fixture from gateway names keyed to team codes."""
    home_n, away_n = _keyed_side_names(event)
    return _unique_name_orient(event, fixtures, home_n, away_n)


def _best_by_title_order(
    event: dict[str, Any],
    fixtures: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Title left/right as event home/away when leftover codes cannot orient.

    State/Tech/A&M titles are not team order (Washington vs Washington State).
    Tennis titles keep this path: leftover codes miss and school marks match.
    """
    sides = vs_sides(str(event.get("title") or ""))
    if sides is None:
        return None
    if school_marks(sides[0]) != school_marks(sides[1]):
        return None
    return _unique_name_orient(event, fixtures, sides[0], sides[1])


def _best_by_title(
    event: dict[str, Any],
    fixtures: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Title covers one Optic fixture (any order); leftover codes set event sides."""
    sides = vs_sides(str(event.get("title") or ""))
    if sides is None:
        return None
    covered = _unique_name_orient(event, fixtures, sides[0], sides[1])
    if covered is None:
        return None
    fx = covered["fx"]
    home = str(event.get("home") or "")
    away = str(event.get("away") or "")
    orient = _orient_by_codes(home, away, fx, leftover=True)
    if not orient:
        return None
    return {"score": 3, "orient": orient, "fx": fx}


def _unique_name_orient(
    event: dict[str, Any],
    fixtures: list[dict[str, Any]],
    home_n: str,
    away_n: str,
) -> dict[str, Any] | None:
    """Unique date±1 fixture whose Optic names cover these two displays."""
    if len(home_n) < 4 or len(away_n) < 4:
        return None
    return _unique_fx_orient(
        event, fixtures, lambda fx: _orient_by_names(home_n, away_n, fx),
    )


def _unique_fx_orient(
    event: dict[str, Any],
    fixtures: list[dict[str, Any]],
    orient_fn: Callable[[dict[str, Any]], str],
) -> dict[str, Any] | None:
    """Sole windowed fixture with a non-empty orientation, else None."""
    hits: list[tuple[dict[str, Any], str]] = []
    for raw in fixtures:
        fx = normalize_fixture(raw)
        if not _in_date_window(event, fx):
            continue
        orient = str(orient_fn(fx) or "")
        if orient:
            hits.append((fx, orient))
    if len(hits) != 1:
        return None
    fx, orient = hits[0]
    return {"score": 3, "orient": orient, "fx": fx}


def _in_date_window(event: dict[str, Any], fx: dict[str, Any]) -> bool:
    """True when the fixture calendar day is event date ± 1."""
    day = str(event.get("date") or "")[:10]
    dates = {day, shift_day(day, -1), shift_day(day, 1)}
    dates.discard("")
    return str(fx.get("d") or "") in dates


def _keyed_side_names(event: dict[str, Any]) -> tuple[str, str]:
    """Gateway display names keyed by this event's home/away codes."""
    names = event.get("team_names")
    home_c = str(event.get("home") or "").casefold()
    away_c = str(event.get("away") or "").casefold()
    if not isinstance(names, dict):
        return "", ""
    return (
        str(names.get(home_c) or "").strip(),
        str(names.get(away_c) or "").strip(),
    )


def _unique_code_side(code: str, fx: dict[str, Any]) -> str:
    """home / away when ``code`` uniquely binds one Optic side, else empty."""
    return _bind_code_side(
        code,
        str(fx["home_abbr"]),
        str(fx["away_abbr"]),
        str(fx["home_name"]),
        str(fx["away_name"]),
    )


def _orient_by_codes(
    home: str, away: str, fx: dict[str, Any], *, leftover: bool,
) -> str:
    """same / flip from unique code binds; leftover fills one empty side."""
    home_side = _unique_code_side(home, fx)
    away_side = _unique_code_side(away, fx)
    if home_side and away_side:
        if home_side == away_side:
            return ""
        return "same" if home_side == "home" else "flip"
    if not leftover:
        return ""
    if home_side and not away_side:
        return "same" if home_side == "home" else "flip"
    if away_side and not home_side:
        return "same" if away_side == "away" else "flip"
    return ""


def _pick_hit(*hits: dict[str, Any] | None) -> dict[str, Any] | None:
    """One hit when all present agree on fixture and orientation, else None."""
    present = [hit for hit in hits if hit]
    if not present:
        return None
    keys = {_hit_key(hit) for hit in present}
    if len(keys) != 1:
        return None
    return present[0]


def _hit_key(hit: dict[str, Any]) -> tuple[str, str, str, str]:
    """Identity for agreeing harvest hits."""
    fx = hit["fx"]
    return (
        str(fx.get("home_id") or ""),
        str(fx.get("away_id") or ""),
        str(fx.get("d") or ""),
        str(hit.get("orient") or ""),
    )


def _orient_by_names(home_n: str, away_n: str, fx: dict[str, Any]) -> str:
    """same / flip when each Poly US name uniquely fits one Optic side."""
    player = person_league(str(fx.get("optic_league_id") or ""))
    optic_h = str(fx.get("home_name") or "")
    optic_a = str(fx.get("away_name") or "")
    same = names_fit(home_n, optic_h, player=player) and names_fit(
        away_n, optic_a, player=player,
    )
    flip = names_fit(home_n, optic_a, player=player) and names_fit(
        away_n, optic_h, player=player,
    )
    if same and not flip:
        return "same"
    if flip and not same:
        return "flip"
    home_side = unique_side(home_n, optic_h, optic_a, person=player)
    away_side = unique_side(away_n, optic_h, optic_a, person=player)
    if home_side == "home" and away_side == "away":
        return "same"
    if home_side == "away" and away_side == "home":
        return "flip"
    return ""


def unique_optic_id(
    event: dict[str, Any],
    by_optic: dict[str, list[dict[str, Any]]],
) -> str:
    """Optic league id that uniquely matches ``event``, else empty."""
    hits = [
        oid for oid, rows in by_optic.items() if oid and best_fixture(event, rows)
    ]
    if len(hits) != 1:
        return ""
    return hits[0]


def unique_optic_for_events(
    events: list[dict[str, Any]],
    by_optic: dict[str, list[dict[str, Any]]],
) -> str:
    """Sole Optic id uniquely matched by a majority of events, else empty.

    Non-matches used to be ignored, so one coincidental unique hit among
    hundreds of SETKA tickers onboarded ``norway_3_division``. Fail closed
    unless a majority unique-match the same optic (a single event still
    pins when it is the only evidence).
    """
    hits: list[str] = []
    for event in events:
        oid = unique_optic_id(event, by_optic)
        if oid:
            hits.append(oid)
    unique = set(hits)
    if len(unique) != 1:
        return ""
    need = 1 if len(events) <= 1 else max(2, (len(events) + 1) // 2)
    if len(hits) < need:
        return ""
    return next(iter(unique))


def question_matches_fixture(question: str, fx: dict[str, Any]) -> bool:
    """True when both Optic names appear, or parsed vs-sides equal the fixture."""
    n = normalize_fixture(fx)
    home = str(n.get("home_name") or "")
    away = str(n.get("away_name") or "")
    q = (question or "").casefold()
    if (
        home and away and len(home) >= 4 and len(away) >= 4
        and home.casefold() in q and away.casefold() in q
    ):
        return True
    sides = vs_sides(question)
    if sides is None or not home or not away:
        return False
    return {sides[0].casefold(), sides[1].casefold()} == {
        home.casefold(), away.casefold(),
    }


def unique_optic_for_questions(
    events: list[dict[str, Any]],
    by_optic: dict[str, list[dict[str, Any]]],
) -> str:
    """Sole Optic league id uniquely named in the questions, else empty."""
    found: set[str] = set()
    for event in events:
        oid = _unique_question_optic(event, by_optic)
        if oid == "":
            if _question_hits_any(event, by_optic):
                return ""
            continue
        found.add(oid)
    if len(found) != 1:
        return ""
    return next(iter(found))


def _unique_question_optic(
    event: dict[str, Any],
    by_optic: dict[str, list[dict[str, Any]]],
) -> str:
    """Optic id that uniquely matches this question, else empty."""
    hits = [
        oid for oid, rows in by_optic.items()
        if oid and _question_hits_league(event, rows, oid)
    ]
    if len(hits) != 1:
        return ""
    return hits[0]


def _question_hits_any(
    event: dict[str, Any],
    by_optic: dict[str, list[dict[str, Any]]],
) -> bool:
    """True when the question matches fixtures in more than one league."""
    hits = [
        oid for oid, rows in by_optic.items()
        if oid and _question_hits_league(event, rows, oid)
    ]
    return len(hits) > 1


def _question_hits_league(
    event: dict[str, Any], rows: list[dict[str, Any]], optic_id: str = "",
) -> bool:
    """True when date + both names match at least one fixture in ``rows``."""
    day = str(event.get("date") or "")[:10]
    question = str(event.get("question") or "")
    dates = {day, shift_day(day, -1), shift_day(day, 1)}
    dates.discard("")
    for raw in rows:
        fx = normalize_fixture(raw)
        if str(fx["d"]) not in dates:
            continue
        if question_matches_fixture(question, fx):
            return True
        if _question_unique_binds(question, fx, optic_id):
            return True
    return False


def _question_unique_binds(
    question: str, fx: dict[str, Any], optic_id: str = "",
) -> bool:
    """True when vs-sides uniquely bind opposite Optic competitors."""
    sides = vs_sides(question)
    if sides is None:
        return False
    player = person_league(str(fx.get("optic_league_id") or optic_id))
    home = str(fx.get("home_name") or "")
    away = str(fx.get("away_name") or "")
    left = unique_side(sides[0], home, away, person=player)
    right = unique_side(sides[1], home, away, person=player)
    return {left, right} == {"home", "away"}
