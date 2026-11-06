"""Refuse crypto.com stamps when catalogue names are swapped onto tip ids."""

from __future__ import annotations

from collections.abc import Mapping

from mappers.canonical_codes import names_close, person_league
from mappers.team_side import team_side


def feed_name_fits_team(short: str, full: str) -> bool:
    """True when a feed nickname names the same side as a fixture display name.

    Live Team Prop PARTICIPANT is often a short form ("Giants", "San Jose
    State") while HOME/AWAY_PARTICIPANT is the full listing name.  Whole-word
    suffix in either direction, plus multi-word prefix ("San Jose State" →
    "San Jose State Spartans").  Single-token prefixes stay banned
    ("Ohio" must not bind "Ohio State").
    """
    a, b = short.strip().casefold(), full.strip().casefold()
    if not a or not b:
        return False
    if a == b:
        return True
    if b.endswith(" " + a) or a.endswith(" " + b):
        return True
    return " " in a and b.startswith(a + " ")


def skip_crossed_stamp(
    home_part: str,
    away_part: str,
    home_key: str,
    away_key: str,
    entity_names: Mapping[str, str],
    *,
    league: str,
) -> bool:
    """True when feed names match the opposite canonicals (Song↔Umar)."""
    home_name = str(entity_names.get(home_key) or "")
    away_name = str(entity_names.get(away_key) or "")
    if not home_part or not away_part or not home_name or not away_name:
        return False
    player = person_league(league)
    home_ok = names_close(home_part, home_name, player=player)
    away_ok = names_close(away_part, away_name, player=player)
    if home_ok and away_ok:
        return False
    return names_close(home_part, away_name, player=player) and names_close(
        away_part, home_name, player=player,
    )


def participant_contradicts_side(
    participant: str | None,
    side: str,
    *,
    home: str,
    away: str,
    home_name: str,
    away_name: str,
    league: str,
) -> bool:
    """True when the listing's own PARTICIPANT does not name ``side``.

    Last check before a two-sided crypto.com row is written: the symbol's
    PARTICIPANT is the one name crypto.com gives for what the customer
    backs, so it must name the Optic side we stamp. An in-memory id pin
    that crossed the fighters (2026-09-30, mmmapper 1f843ccc) passes every
    id-based check upstream and is only visible here.

    Person leagues fail closed: no participant, no Optic names, or a name
    that fits neither/both sides drops the row. Club leagues drop only a
    positive contradiction, since nicknames and spellings (Miami Ohio,
    St./Saint) often fit neither side.
    """
    player = person_league(league)
    text = (participant or "").strip()
    if not text or not home_name or not away_name:
        return player
    named = team_side(
        text, home=home, away=away,
        home_name=home_name, away_name=away_name, player=player,
    )
    if named is None and not player:
        fits = [code for code, name in ((home, home_name), (away, away_name))
                if feed_name_fits_team(text, name)]
        named = fits[0] if len(fits) == 1 else None
    if named is None:
        return player
    return named != side
