"""Every soccer league must use the shared Optic taxonomy.

Optic market ids are league-independent — `total_corners` is `total_corners`
whether the fixture is a Champions League tie or a Latvian Virsliga game — so the
mapping from optic market id to MarketType must not vary per competition. It used
to, because each league hand-maintained its own dict, and coverage diverged by
accident: EPL shipped six fewer keys than its siblings for months, world_cup was
missing `player_saves`, and UCL was missing `to_advance` despite being a knockout
competition.

These tests make that drift impossible: a new soccer league, or a market added to
one league only, fails here.
"""

import os

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

import pytest  # noqa: E402

from mappers.run import LEAGUES  # noqa: E402
from mappers.sport import Sport
from mappers.vocab.soccer_markets import (  # noqa: E402
    SOCCER_OPTIC_CUP_TABLE_TYPES,
    SOCCER_OPTIC_TABLE_TYPES,
)

_SOCCER = sorted(
    slug for slug, cfg in LEAGUES.items() if cfg.sport == Sport.SOCCER
)
# Knockout competitions: the only soccer leagues that legitimately carry
# `to_advance`. A round-robin league has no tie to advance from, so Optic never
# prices it there and wiring it would be dead config, not fail-safe inclusion.
_CUPS = {
    "ucl",
    "world_cup",
    "conmebol_sudamericana",
    "europa_league",
    "europa_conference_league",
    "leagues_cup",
    "efl_cup",
    "uefa_super_cup",
    "england_community_shield",
    "ofc_champions_league",
}


def test_there_are_soccer_leagues_to_check():
    assert _SOCCER, "no wired soccer leagues — the rest of this file would vacuously pass"


@pytest.mark.parametrize("league", _SOCCER)
def test_soccer_league_uses_the_shared_taxonomy(league):
    expected = SOCCER_OPTIC_CUP_TABLE_TYPES if league in _CUPS else SOCCER_OPTIC_TABLE_TYPES
    actual = LEAGUES[league].OPTIC.table_types
    assert actual == expected, (
        f"{league} diverges from the shared soccer taxonomy. "
        f"missing={sorted(set(expected) - set(actual))} "
        f"extra={sorted(set(actual) - set(expected))} — add markets to "
        "mappers/vocab/soccer_markets.py, not to one league."
    )


@pytest.mark.parametrize("league", _SOCCER)
def test_soccer_league_output_order_covers_the_taxonomy(league):
    cfg = LEAGUES[league]
    order = set(cfg.OUTPUT_ORDER)
    for market_id, mt in cfg.OPTIC.table_types.items():
        assert mt in order, (league, market_id, mt)


def test_cup_overlay_is_the_base_plus_only_to_advance():
    assert set(SOCCER_OPTIC_CUP_TABLE_TYPES) - set(SOCCER_OPTIC_TABLE_TYPES) == {"to_advance"}
    for k, v in SOCCER_OPTIC_TABLE_TYPES.items():
        assert SOCCER_OPTIC_CUP_TABLE_TYPES[k] == v


def test_non_cup_soccer_leagues_do_not_carry_to_advance():
    for lg in _SOCCER:
        if lg not in _CUPS:
            assert "to_advance" not in LEAGUES[lg].OPTIC.table_types, lg
