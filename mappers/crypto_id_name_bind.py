"""In-memory crypto.com EXTERNAL_*_ID pins from catalogue names onto Optic.

Mapper and gap-propose share ``names_fit`` / ``unique_optic_sides`` with
PX name-bind. Fail-closed on alias collision.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

from mappers.crypto_meta import harvest_exception_key
from mappers.exchanges import crypto_com
from mappers.px_name_bind import (
    NamedSide,
    aligned_pairs,
    unique_optic_sides,
)
from mappers.shared import AliasValue, MatchKey, resolve_team, to_date_str, to_et_str


def planned_crypto_ids(
    pairs: list[tuple[NamedSide, NamedSide]],
    aliases: Mapping[str, AliasValue],
) -> dict[str, str] | None:
    """crypto_id → Optic canonical when ids are missing. None on collision."""
    planned: dict[str, str] = {}
    for cat_side, optic_side in pairs:
        cid = cat_side.abbr
        canonical = optic_side.abbr
        if not cid or not canonical:
            return None
        existing = aliases.get(cid)
        if existing is None:
            planned[cid] = canonical
            continue
        if isinstance(existing, str) and existing == canonical:
            continue
        return None
    return planned


def pin_crypto_ids_from_selections(
    crypto_by_egid: Mapping[str, list[crypto_com.Selection]],
    index: Mapping[MatchKey, list[Any]],
    aliases: MutableMapping[str, AliasValue],
    *,
    player: bool,
) -> int:
    """Pin catalogue EXTERNAL ids when a unique same-date Optic name match exists."""
    pinned = 0
    for sels in crypto_by_egid.values():
        if not sels:
            continue
        first = max(sels, key=lambda s: s.security_id)
        home_id = str(first.external_home_id or "").strip()
        away_id = str(first.external_away_id or "").strip()
        if not home_id or not away_id:
            continue
        if (
            resolve_team(home_id, aliases) != home_id
            and resolve_team(away_id, aliases) != away_id
        ):
            continue
        matched = _matched_sides(first, home_id, away_id, index, player=player)
        if matched is None:
            continue
        cat_home, cat_away, hit = matched
        pairs = aligned_pairs(cat_home, cat_away, hit[0], hit[1], player=player)
        if pairs is None:
            continue
        planned = planned_crypto_ids(pairs, aliases)
        if not planned:
            continue
        for cid, canonical in planned.items():
            if resolve_team(cid, aliases) == canonical:
                continue
            aliases[cid] = canonical
            pinned += 1
            print(
                f"  crypto id-bind: in-memory {cid} → {canonical}",
                file=sys.stderr,
            )
    return pinned


def _matched_sides(
    first: crypto_com.Selection,
    home_id: str,
    away_id: str,
    index: Mapping[MatchKey, list[Any]],
    *,
    player: bool,
) -> tuple[NamedSide, NamedSide, tuple[NamedSide, NamedSide]] | None:
    """Catalogue sides and the unique Optic fixture, or None."""
    game_date = to_date_str(to_et_str(first.start_date))
    fixtures = _index_fixtures(index, game_date)
    cat_home = _catalogue_side(
        home_id, first.home_participant, first.league, fixtures,
    )
    cat_away = _catalogue_side(
        away_id, first.away_participant, first.league, fixtures,
    )
    hit = unique_optic_sides(cat_home, cat_away, fixtures, player=player)
    if hit is None:
        return None
    return cat_home, cat_away, hit


def _catalogue_side(
    cid: str,
    name: str,
    meta_league: str,
    fixtures: list[tuple[NamedSide, NamedSide]],
) -> NamedSide:
    """Use the Optic display name when the feed label is a registered alias.

    The alias must point at exactly one name on this date. Otherwise the
    feed label is left as-is and ``names_fit`` decides.
    """
    key = harvest_exception_key(meta_league, name)
    if not key:
        return NamedSide(cid, name)
    optic_names = {
        side.name
        for home, away in fixtures
        for side in (home, away)
        if side.abbr == key and side.name
    }
    if len(optic_names) != 1:
        return NamedSide(cid, name)
    return NamedSide(cid, next(iter(optic_names)))


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
