"""Bind book codes onto fixture sides via Optic competitor abbreviation.

Tip aliases map book code → canonical_key. Mapper ``Fixture.home`` is often
that canonical (optic_id override), while Kalshi / Polymarket USA / PX still
emit the Optic abbreviation (``BBR`` vs ``BRF8``). Join on either token.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from mappers.shared import AliasValue, MatchKey


def optic_abbr(fx: Any, *, home: bool) -> str:
    """Raw Optic competitor abbreviation, or the canonical side if unset."""
    if home:
        raw = str(getattr(fx, "home_optic_abbr", None) or "").strip()
        return raw or str(fx.home)
    raw = str(getattr(fx, "away_optic_abbr", None) or "").strip()
    return raw or str(fx.away)


def side_codes(canonical: str, optic: str) -> set[str]:
    """Casefolded tokens that identify one fixture side."""
    out = {(canonical or "").strip().casefold()}
    oa = (optic or "").strip().casefold()
    if oa:
        out.add(oa)
    return {token for token in out if token}


def fixture_home_codes(fx: Any) -> set[str]:
    """Casefolded canonical + Optic abbr for the home side."""
    return side_codes(str(fx.home), optic_abbr(fx, home=True))


def fixture_away_codes(fx: Any) -> set[str]:
    """Casefolded canonical + Optic abbr for the away side."""
    return side_codes(str(fx.away), optic_abbr(fx, home=False))


def code_fits_side(code: str, canonical: str, optic: str) -> bool:
    """True when ``code`` is this side's canonical or Optic abbreviation."""
    token = (code or "").strip().casefold()
    return bool(token) and token in side_codes(canonical, optic)


def oriented_hit(home: str, away: str, fx: Any) -> bool:
    """True when home/away match this fixture's sides in this order."""
    if not hasattr(fx, "home") or not hasattr(fx, "away"):
        return False
    h, a = (home or "").strip().casefold(), (away or "").strip().casefold()
    return bool(h) and bool(a) and h in fixture_home_codes(fx) and a in fixture_away_codes(fx)


def pair_hit(home: str, away: str, fx: Any) -> bool:
    """True when home/away match this fixture in either orientation."""
    return oriented_hit(home, away, fx) or oriented_hit(away, home, fx)


def lookup_oriented(
    index: Mapping[MatchKey, list[Any]],
    date: str,
    home: str,
    away: str,
) -> list[Any]:
    """Schedule entries for this date and orientation (canonical or Optic abbr)."""
    found = list(index.get(MatchKey(date, home, away)) or [])
    if found:
        return found
    hits: list[Any] = []
    seen: set[int] = set()
    for key, entries in index.items():
        if key.game_date != date:
            continue
        for entry in entries:
            ident = id(entry)
            if ident in seen:
                continue
            fx = getattr(entry, "fixture", entry)
            if oriented_hit(home, away, fx):
                seen.add(ident)
                hits.append(entry)
    return hits


def lookup_pair(
    index: Mapping[MatchKey, list[Any]],
    home: str,
    away: str,
) -> list[Any]:
    """Entries whose sides are this pair in either orientation, any date."""
    hits: list[Any] = []
    seen: set[int] = set()
    for key, entries in index.items():
        key_hit = {key.home, key.away} == {home, away}
        for entry in entries:
            ident = id(entry)
            if ident in seen:
                continue
            fx = getattr(entry, "fixture", entry)
            if key_hit or pair_hit(home, away, fx):
                seen.add(ident)
                hits.append(entry)
    return hits


def match_keys_for_pair(
    index: Mapping[MatchKey, list[Any]],
    home: str,
    away: str,
) -> list[MatchKey]:
    """Canonical MatchKeys for fixtures whose sides are this pair."""
    out: list[MatchKey] = []
    seen: set[MatchKey] = set()
    for key, entries in index.items():
        key_hit = key.home == home and key.away == away
        for entry in entries:
            fx = getattr(entry, "fixture", entry)
            if not key_hit and not pair_hit(home, away, fx):
                continue
            if hasattr(fx, "home") and hasattr(fx, "away"):
                ck = MatchKey(key.game_date, str(fx.home), str(fx.away))
            else:
                ck = key
            if ck not in seen:
                seen.add(ck)
                out.append(ck)
            break
        else:
            if key_hit and key not in seen:
                seen.add(key)
                out.append(key)
    return out


def planned_optic_abbr_aliases(
    raw_home: str,
    raw_away: str,
    fx: Any,
) -> dict[str, str]:
    """Book codes that equal this fixture's Optic abbr and differ from canonical."""
    rh, ra = (raw_home or "").strip(), (raw_away or "").strip()
    if oriented_hit(rh, ra, fx):
        pairs = (
            (rh, str(fx.home), optic_abbr(fx, home=True)),
            (ra, str(fx.away), optic_abbr(fx, home=False)),
        )
    elif oriented_hit(ra, rh, fx):
        pairs = (
            (rh, str(fx.away), optic_abbr(fx, home=False)),
            (ra, str(fx.home), optic_abbr(fx, home=True)),
        )
    else:
        return {}
    out: dict[str, str] = {}
    for raw, canonical, oa in pairs:
        if not raw or raw.casefold() == canonical.casefold():
            continue
        if not code_fits_side(raw, canonical, oa):
            continue
        out[raw] = canonical
        if raw.upper() != raw:
            out[raw.upper()] = canonical
    return out


def pin_optic_abbr_codes(
    raw_home: str,
    raw_away: str,
    fx: Any,
    aliases: MutableMapping[str, AliasValue],
) -> dict[str, str]:
    """In-memory book-code → canonical when the code is this fixture's Optic abbr."""
    applied: dict[str, str] = {}
    for code, canonical in planned_optic_abbr_aliases(raw_home, raw_away, fx).items():
        existing = aliases.get(code)
        if existing is None:
            aliases[code] = canonical
            applied[code] = canonical
            continue
        if isinstance(existing, str) and existing == canonical:
            continue
    return applied
