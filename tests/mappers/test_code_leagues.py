"""Code-owned leagues join the run set and read their Polymarket US leagues."""

from __future__ import annotations

from mappers.canonical_codes import person_league
from mappers.exchanges.polymarket_usa_leagues import US_LEAGUE_IDS_BY_OPTIC
from mappers.seed.code_leagues import CODE_LEAGUES
from mappers.seed.tip_leagues import resolve_run_leagues
from mappers.sport import Sport
from mappers.vocab.poly_usa_smt import smt_spec
from mappers.vocab.soccer_markets import SOCCER_OPTIC_TABLE_TYPES


def test_code_leagues_join_an_empty_tip_with_poly_usa() -> None:
    out = resolve_run_leagues({}, [])
    for slug, (sport, optic_ids) in CODE_LEAGUES.items():
        cfg = out[slug]
        assert (cfg.OPTIC.league_id, *cfg.OPTIC.extra_league_ids) == optic_ids
        assert cfg.POLYMARKET_USA is not None
        assert cfg.POLYMARKET_USA.league_ids == US_LEAGUE_IDS_BY_OPTIC[optic_ids[0]]
        assert person_league(slug) == (
            sport in (Sport.TENNIS, Sport.BOXING, Sport.DARTS)
        )


def test_darts_reads_its_gateway_leagues() -> None:
    out = resolve_run_leagues({}, [])
    for slug, ids in (("pdc_darts", {175}), ("modus_darts", {211})):
        us = out[slug].POLYMARKET_USA
        assert us is not None and us.league_ids == frozenset(ids)
    assert smt_spec("darts_match_winner") is not None


def test_greek_cup_is_fetched_as_soccer() -> None:
    """No tip row: without the code entry its gateway league 280 had no fixtures to bind."""
    cfg = resolve_run_leagues({}, [])["greece_cup"]
    assert cfg.sport == Sport.SOCCER and cfg.OPTIC.league_id == "greece_-_cup"
    assert cfg.OPTIC.table_types == SOCCER_OPTIC_TABLE_TYPES
    assert cfg.POLYMARKET_USA is not None
    assert cfg.POLYMARKET_USA.league_ids == frozenset({280})


def test_nhl_enums_map() -> None:
    for smt in (
        "hockey_team_total_goals",
        "hockey_team_regulation_winner",
        "hockey_team_first_period_total",
        "hockey_team_third_period_spread",
        "hockey_team_second_period_winner",
    ):
        assert smt_spec(smt) is not None, smt


def test_doubles_pair_binds_member_by_member() -> None:
    from mappers.exchanges.polymarket_usa_structured import _name_fits

    optic = "Gabriela Dabrowski // Luisa Stefani"
    assert _name_fits("Dabrowski G / Stefani L", optic, person=True)
    assert _name_fits("Stefani L / Dabrowski G", optic, person=True)
    # The pipeline's folded side joins members with a single slash.
    folded = "Gabriela Dabrowski / Luisa Stefani"
    assert _name_fits("Dabrowski G / Stefani L", folded, person=True)
    # One member missing, or a bare surname the single rule rejects: no bind.
    assert not _name_fits("Dabrowski G / Olmos G", optic, person=True)
    assert not _name_fits("Dabrowski G", optic, person=True)
    # Same surname, initials pick the sister.
    sisters = "Francisca Jorge // Matilde Jorge"
    assert not _name_fits("Jorge F / Jorge F", sisters, person=True)
