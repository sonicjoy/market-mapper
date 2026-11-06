"""Match catalogue/title names onto Optic fixtures (accent/FC-aware)."""

from __future__ import annotations

import re
from typing import Any

from mappers.canonical_codes import names_fit
from mappers.control_plane.gap_fix_name_bind import unique_side
from mappers.px_name_bind import NamedSide, pair_fits

_VS = re.compile(r"\s+vs\.?\s+", re.I)
_AT = re.compile(r"\s+@\s+")


def name_sides(name: str) -> tuple[str, str] | None:
    """Split 'A vs B' or soccer 'Away @ Home' into two name sides."""
    core = name.split(":", 1)[0].strip()
    for splitter in (_VS, _AT):
        parts = splitter.split(core, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            return parts[0].strip(), parts[1].strip()
    return None


def catalogue_sides(cat: dict[str, Any]) -> tuple[str, str] | None:
    """The two participants crypto.com names, else the sides of its event title.

    ``meta_home_participant`` / ``meta_away_participant`` are fields; ``meta_name``
    is a display string that may carry a market suffix or no ``vs`` at all.
    """
    home = str(cat.get("home_name") or "").strip()
    away = str(cat.get("away_name") or "").strip()
    if home and away and home.casefold() != away.casefold():
        return home, away
    return name_sides(str(cat.get("meta_name") or ""))


def is_matchup_title(name: str) -> bool:
    """True for catalogue event titles ('A vs B' / 'A @ B')."""
    return name_sides(name) is not None


def entity_name_from_crypto_refs(refs: list[str], canonical_name: str) -> str:
    """Participant crypto:name for this canonical; skip matchup titles."""
    want = canonical_name.strip()
    for shown in _crypto_participant_names(refs):
        if want and (
            names_fit(shown, want, player=True)
            or names_fit(shown, want, player=False)
        ):
            return shown
    return want


def event_title_from_crypto_refs(refs: list[str]) -> str:
    """Fixture title from crypto:title, else a leftover matchup crypto:name."""
    for ref in refs:
        if ref.startswith("crypto:title:"):
            shown = ref.split(":", 2)[-1].strip()
            if shown:
                return shown
    for ref in refs:
        if not ref.startswith("crypto:name:"):
            continue
        shown = ref.split(":", 2)[-1].strip()
        if is_matchup_title(shown):
            return shown
    return ""


def _crypto_participant_names(refs: list[str]) -> list[str]:
    """crypto:name values that are people/clubs, not event titles."""
    out: list[str] = []
    for ref in refs:
        if not ref.startswith("crypto:name:"):
            continue
        shown = ref.split(":", 2)[-1].strip()
        if shown and not is_matchup_title(shown) and shown not in out:
            out.append(shown)
    return out


def day_names_a_side(
    fixtures: list[dict[str, Any]],
    sides: tuple[str, str],
    day: str,
    *,
    player: bool,
) -> bool:
    """True when either catalogue side fits a competitor on that day."""
    pool = _day_only(fixtures, day) or fixtures
    for game in pool:
        for key in ("home_competitors", "away_competitors"):
            shown = _side_name(game, key)
            if shown and (
                names_fit(sides[0], shown, player=player)
                or names_fit(sides[1], shown, player=player)
            ):
                return True
    return False


def best_fixture(
    fixtures: list[dict[str, Any]],
    sides: tuple[str, str],
    *,
    player: bool,
) -> dict[str, Any] | None:
    """First fixture whose home/away names cover both catalogue sides."""
    a, b = sides
    for game in fixtures:
        home = _side_name(game, "home_competitors")
        away = _side_name(game, "away_competitors")
        if not _sides_cover(a, b, home, away, player=player):
            continue
        return _fixture_hit(game, home, away)
    return None


def fixture_for_ids(
    fixtures: list[dict[str, Any]],
    ids: list[str],
) -> dict[str, Any] | None:
    """First fixture whose competitor ids cover both catalogue EXTERNAL ids."""
    want = {cid.strip() for cid in ids if cid and cid.strip()}
    if len(want) < 2:
        return None
    for game in fixtures:
        home_id = _side_id(game, "home_competitors")
        away_id = _side_id(game, "away_competitors")
        if {home_id, away_id} != want:
            continue
        return _fixture_hit(
            game, _side_name(game, "home_competitors"), _side_name(game, "away_competitors"),
        )
    return None


def unique_fixture(
    fixtures: list[dict[str, Any]],
    sides: tuple[str, str],
    *,
    player: bool,
) -> dict[str, Any] | None:
    """Sole fixture whose home/away names cover both catalogue sides."""
    hits: list[dict[str, Any]] = []
    for game in fixtures:
        home = _side_name(game, "home_competitors")
        away = _side_name(game, "away_competitors")
        if not _sides_cover(sides[0], sides[1], home, away, player=player):
            continue
        hits.append(_fixture_hit(game, home, away))
        if len(hits) > 1:
            return None
    return hits[0] if hits else None


def match_optic_fixture(
    fixtures: list[dict[str, Any]],
    sides: tuple[str, str] | None,
    ids: list[str],
    day: str,
    *,
    player: bool,
) -> dict[str, Any] | None:
    """Day-first name/id match; unique horizon hit when that day is a miss."""
    needle = day.strip()[:10]
    if needle:
        day_pool = _day_only(fixtures, day)
        if day_pool:
            hit = _id_or_name(day_pool, sides, ids, player=player, unique=False)
            if hit:
                return hit
        return _id_or_name(fixtures, sides, ids, player=player, unique=True)
    return _id_or_name(fixtures, sides, ids, player=player, unique=False)


def fixtures_on_day(fixtures: list[dict[str, Any]], day: str) -> list[dict[str, Any]]:
    """Keep fixtures whose start_date prefix matches YYYY-MM-DD; else all."""
    return _day_only(fixtures, day) or fixtures


def _day_only(fixtures: list[dict[str, Any]], day: str) -> list[dict[str, Any]]:
    """Fixtures on YYYY-MM-DD; empty when the day is missing or blank."""
    needle = day.strip()[:10]
    if not needle:
        return list(fixtures)
    return [
        game for game in fixtures
        if str(game.get("start_date") or "")[:10] == needle
    ]


def _id_or_name(
    fixtures: list[dict[str, Any]],
    sides: tuple[str, str] | None,
    ids: list[str],
    *,
    player: bool,
    unique: bool,
) -> dict[str, Any] | None:
    """Competitor-id match, then catalogue names (first or unique)."""
    hit = fixture_for_ids(fixtures, ids) if ids else None
    if hit:
        return hit
    if sides is None:
        return None
    if unique:
        return unique_fixture(fixtures, sides, player=player)
    return best_fixture(fixtures, sides, player=player)


def _fixture_hit(game: dict[str, Any], home: str, away: str) -> dict[str, Any]:
    """Optic match payload used by the crypto gap probe."""
    return {
        "fixture_id": game.get("id"),
        "start_date": game.get("start_date"),
        "home": home,
        "away": away,
        "home_id": _side_id(game, "home_competitors"),
        "away_id": _side_id(game, "away_competitors"),
    }


def _sides_cover(a: str, b: str, home: str, away: str, *, player: bool) -> bool:
    """True when catalogue sides map onto opposite Optic competitors."""
    if pair_fits(
        NamedSide("", a), NamedSide("", b),
        NamedSide("", home), NamedSide("", away),
        player=player,
    ):
        return True
    a_side = unique_side(a, home, away, person=player)
    b_side = unique_side(b, home, away, person=player)
    return {a_side, b_side} == {"home", "away"}


def _side_name(game: dict[str, Any], key: str) -> str:
    """Display name for one fixture side."""
    row = (game.get(key) or [{}])[0]
    return str(row.get("name") or "").strip()


def _side_id(game: dict[str, Any], key: str) -> str:
    """Optic competitor id for one fixture side."""
    row = (game.get(key) or [{}])[0]
    return str(row.get("id") or "").strip()


def other_competitor_name(game: dict[str, Any], this_oid: str) -> str:
    """Display name for the other competitor on this Optic fixture."""
    want = this_oid.strip()
    for key in ("home_competitors", "away_competitors"):
        row = (game.get(key) or [{}])[0]
        cid = str(row.get("id") or "").strip()
        if cid and cid != want:
            return str(row.get("name") or "").strip()
    return ""
