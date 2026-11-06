"""Polymarket US: women's college basketball reads gateway league 17 (WCBB).

Without this id ``fetch/polymarket_usa.py`` never walks league 17, so every
``aec-wcbb`` market stays unmapped (gateway ``/v2/sports``, 2026-11-05).
"""

from __future__ import annotations

from mappers.exchanges.polymarket_usa_leagues import all_us_league_ids, us_league_ids


def test_ncaaw_reads_its_gateway_league() -> None:
    assert us_league_ids(("ncaaw",)) == frozenset({17})
    assert 17 in all_us_league_ids()


def test_ncaab_keeps_its_own_league() -> None:
    assert us_league_ids(("ncaab",)) == frozenset({4})
