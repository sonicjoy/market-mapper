"""Unique names_fit bind of PX abbreviations onto Optic fixture codes.

Mapper and gap-propose share this so a PX 3-letter abbr (HUL) can join an
Optic 4-char code (HCA7) without a private matcher. Fail-closed: both sides
must fit one fixture; do not steal an existing alias.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, MutableMapping
from typing import Any, NamedTuple

from mappers.canonical_codes import names_fit, tokens
from mappers.exchanges.px import ParsedEvent
from mappers.shared import AliasValue, MatchKey, resolve_team


class NamedSide(NamedTuple):
    """One competitor: exchange/Optic abbr, display name, optional Optic id."""

    abbr: str
    name: str
    oid: str = ""


def person_surname_agree(left: str, right: str) -> bool:
    """Same family name on multi-token person labels (not identity alone)."""
    lt, rt = tokens(left), tokens(right)
    if len(lt) < 2 or len(rt) < 2:
        return False
    return lt[-1].casefold() == rt[-1].casefold()


def person_given_name_spelling_variant(left: str, right: str) -> bool:
    """Same surname, different given — likely feed typo (Abedallah/Abdullah)."""
    if names_fit(left, right, player=True):
        return False
    if not person_surname_agree(left, right):
        return False
    lt, rt = tokens(left), tokens(right)
    given_a, given_b = lt[0].casefold(), rt[0].casefold()
    if given_a == given_b:
        return False
    shared = 0
    for left_ch, right_ch in zip(given_a, given_b, strict=False):
        if left_ch != right_ch:
            break
        shared += 1
    return shared >= 2


def side_fits_player(
    needle: str,
    optic_side: str,
    partner_feed: str,
    partner_optic: str,
) -> bool:
    """One catalogue side against one Optic competitor; partner anchors the pair."""
    if names_fit(needle, optic_side, player=True):
        return True
    if not person_given_name_spelling_variant(needle, optic_side):
        return False
    if person_surname_agree(needle, partner_optic) and not names_fit(
        partner_feed, partner_optic, player=True,
    ):
        return False
    return names_fit(partner_feed, partner_optic, player=True)


def orientation_pair_ok(
    cat_a: str,
    cat_b: str,
    optic_a: str,
    optic_b: str,
    *,
    player: bool,
) -> bool:
    """cat_a→optic_a and cat_b→optic_b when player; else strict names_fit."""
    if not player:
        return names_fit(cat_a, optic_a, player=False) and names_fit(
            cat_b, optic_b, player=False,
        )
    return side_fits_player(cat_a, optic_a, cat_b, optic_b) and side_fits_player(
        cat_b, optic_b, cat_a, optic_a,
    )


def pair_fits(
    left_home: NamedSide,
    left_away: NamedSide,
    right_home: NamedSide,
    right_away: NamedSide,
    *,
    player: bool,
) -> bool:
    """True when both sides fit one Optic fixture (names_fit or surname-anchored)."""
    lh, la, rh, ra = left_home.name, left_away.name, right_home.name, right_away.name
    if orientation_pair_ok(lh, la, rh, ra, player=player):
        return True
    return orientation_pair_ok(lh, la, ra, rh, player=player)


def optic_competitor_for_catalogue_name(
    label: str,
    partner: str,
    optic_home: str,
    optic_away: str,
    optic_home_id: str,
    optic_away_id: str,
    *,
    player: bool,
) -> tuple[str, str]:
    """Optic display name and id for one catalogue participant in a pair."""
    if not label.strip() or not partner.strip():
        return "", ""
    pairs = (
        (optic_home, optic_home_id, optic_away, optic_away_id),
        (optic_away, optic_away_id, optic_home, optic_home_id),
    )
    for opt_a, id_a, opt_b, id_b in pairs:
        if not orientation_pair_ok(label, partner, opt_a, opt_b, player=player):
            continue
        if side_fits_player(label, opt_a, partner, opt_b):
            return opt_a, id_a
        if side_fits_player(label, opt_b, partner, opt_a):
            return opt_b, id_b
    return "", ""


def unique_optic_sides(
    px_home: NamedSide,
    px_away: NamedSide,
    fixtures: list[tuple[NamedSide, NamedSide]],
    *,
    player: bool,
) -> tuple[NamedSide, NamedSide] | None:
    """Sole Optic home/away pair that unique-matches the PX names, else None."""
    hits: list[tuple[NamedSide, NamedSide]] = []
    for home, away in fixtures:
        if pair_fits(px_home, px_away, home, away, player=player) or pair_fits(
            px_home, px_away, away, home, player=player,
        ):
            hits.append((home, away))
    if len(hits) != 1:
        return None
    return hits[0]


def aligned_pairs(
    px_home: NamedSide,
    px_away: NamedSide,
    optic_home: NamedSide,
    optic_away: NamedSide,
    *,
    player: bool,
) -> list[tuple[NamedSide, NamedSide]] | None:
    """PX side → matching Optic side, or None when orientation is not unique.

    ``pair_fits`` accepts either orientation, so it cannot pick one. Test
    each orientation on its own and refuse when both or neither fit — a
    guess here pins each competitor to its opponent (2026-09-30 side flip).
    """
    names = (px_home.name, px_away.name)
    direct = orientation_pair_ok(*names, optic_home.name, optic_away.name, player=player)
    flipped = orientation_pair_ok(*names, optic_away.name, optic_home.name, player=player)
    if direct == flipped:
        return None
    if direct:
        return [(px_home, optic_home), (px_away, optic_away)]
    return [(px_home, optic_away), (px_away, optic_home)]


def planned_px_aliases(
    pairs: list[tuple[NamedSide, NamedSide]],
    aliases: Mapping[str, AliasValue],
) -> dict[str, str] | None:
    """PX abbr → Optic canonical for missing codes. None on collision."""
    planned: dict[str, str] = {}
    for px_side, optic_side in pairs:
        if px_side.abbr == optic_side.abbr:
            continue
        existing = aliases.get(px_side.abbr)
        if existing is None:
            planned[px_side.abbr] = optic_side.abbr
            continue
        if isinstance(existing, str) and existing == optic_side.abbr:
            continue
        return None
    return planned


def px_event_team_map(
    event: ParsedEvent,
    aliases: Mapping[str, AliasValue],
) -> dict[str, str]:
    """Abbreviation and canonical keys used by classify-and-attach."""
    etm: dict[str, str] = {}
    for comp in event.raw.competitors:
        canonical = resolve_team(
            comp.abbreviation, aliases, comp.name, comp.id)
        etm[comp.abbreviation] = canonical
        etm[canonical] = canonical
    for comp in event.raw.competitors:
        if comp.name:
            etm.setdefault(comp.name, etm[comp.abbreviation])
    return etm


def pin_px_name_miss(
    event: ParsedEvent,
    index: Mapping[MatchKey, list[Any]],
    aliases: MutableMapping[str, AliasValue],
    *,
    player: bool,
) -> bool:
    """In-memory PX abbr pins when a unique same-date Optic name match exists."""
    sides = _event_sides(event)
    if sides is None:
        return False
    px_home, px_away = sides
    fixtures = _index_fixtures(index, event.match_key.game_date)
    hit = unique_optic_sides(px_home, px_away, fixtures, player=player)
    if hit is None:
        return False
    pairs = aligned_pairs(px_home, px_away, hit[0], hit[1], player=player)
    if pairs is None:
        return False
    planned = planned_px_aliases(pairs, aliases)
    if not planned:
        return False
    for abbr, canonical in planned.items():
        aliases[abbr] = canonical
        print(
            f"  px name-bind: in-memory {abbr} → {canonical}",
            file=sys.stderr,
        )
    etm = px_event_team_map(event, aliases)
    home = next(c for c in event.raw.competitors if c.side == "home")
    away = next(c for c in event.raw.competitors if c.side == "away")
    event.match_key = MatchKey(
        event.match_key.game_date,
        etm[home.abbreviation],
        etm[away.abbreviation],
    )
    return True


def _event_sides(event: ParsedEvent) -> tuple[NamedSide, NamedSide] | None:
    """Home/away NamedSides from a parsed PX event."""
    by_side: dict[str, NamedSide] = {}
    for comp in event.raw.competitors:
        by_side[comp.side] = NamedSide(comp.abbreviation, comp.name)
    if "home" not in by_side or "away" not in by_side:
        return None
    return by_side["home"], by_side["away"]


def _index_fixtures(
    index: Mapping[MatchKey, list[Any]],
    game_date: str,
) -> list[tuple[NamedSide, NamedSide]]:
    """Optic home/away sides for one ET date."""
    out: list[tuple[NamedSide, NamedSide]] = []
    for key, entries in index.items():
        if key.game_date != game_date:
            continue
        for entry in entries:
            fx = entry.fixture
            out.append((
                NamedSide(fx.home, fx.home_name, _oid(fx, fx.home)),
                NamedSide(fx.away, fx.away_name, _oid(fx, fx.away)),
            ))
    return out


def _oid(fx: Any, abbr: str) -> str:
    """Optic competitor id for this canonical abbr, if team_map has it."""
    for oid, code in (getattr(fx, "team_map", None) or {}).items():
        if str(code) == abbr:
            return str(oid)
    return ""
