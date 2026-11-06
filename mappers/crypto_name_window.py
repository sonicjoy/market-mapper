"""Bind a crypto.com TENNIS game to its Optic fixture by participant names + start window.

crypto.com stamps some tennis EVENT_DATEs hours early (Challenger
McCabe/Ymer: 02:00Z against Optic's 07:30Z), which crosses an Eastern
midnight and misses the ET-date lookup.  Both sides carry the participant
name as a typed field (catalogue HOME/AWAY_PARTICIPANT, Optic competitor
name), so a game binds when the normalised names are *equal* (no fuzzy
matching), exactly one fixture qualifies, and its start is within
``CRYPTO_NAME_WINDOW`` of the crypto stamp.  Anything else stays unmapped.  Called only when the league's
``CryptoConfig.sport_grouping`` is TENNIS; no other sport uses it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from mappers.shared import normalize_player_name, parse_iso_datetime

CRYPTO_NAME_WINDOW = timedelta(hours=12)


def name_window_entries(
    index: dict[Any, list[Any]],
    home_name: str,
    away_name: str,
    start_date: str,
) -> tuple[list[Any], bool] | None:
    """(entries, flipped) for the sole fixture with these names in the window."""
    home = normalize_player_name(home_name)
    away = normalize_player_name(away_name)
    if not home or not away:
        return None
    when = parse_iso_datetime(start_date)
    hits: list[tuple[Any, bool]] = []
    seen: set[int] = set()
    for entries in index.values():
        for entry in entries:
            if id(entry) in seen:
                continue
            seen.add(id(entry))
            fx = entry.fixture
            fh = normalize_player_name(fx.home_name)
            fa = normalize_player_name(fx.away_name)
            if (fh, fa) == (home, away):
                flipped = False
            elif (fh, fa) == (away, home):
                flipped = True
            else:
                continue
            if abs(parse_iso_datetime(fx.start_date) - when) <= CRYPTO_NAME_WINDOW:
                hits.append((entry, flipped))
    if len(hits) != 1:
        return None
    return [hits[0][0]], hits[0][1]
