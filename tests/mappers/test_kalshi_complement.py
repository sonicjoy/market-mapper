"""Kalshi moneyline No complement satellites (2-way and soccer double chance)."""

from __future__ import annotations

import pytest

from mappers.kalshi_complement import (
    attach_kalshi_double_chance_complements,
    attach_kalshi_moneyline_complements,
)
from mappers.market_types import MarketType
from mappers.pipeline import row_key
from mappers.shared import TIE_SIDE, CanonicalRow
from mappers.sport import Sport


def _ml_row(
    *,
    side: str,
    home: str = "KC",
    away: str = "DEN",
    ticker: str,
    optic_id: str = "odd-1",
) -> CanonicalRow:
    return CanonicalRow(
        league="nfl",
        start_date="2026-09-14T20:00:00Z",
        home=home,
        away=away,
        market_type=MarketType.MONEYLINE.value,
        side=side,
        optic_id=optic_id,
        kalshi_ticker=ticker,
        kalshi_scope="Game",
        kalshi_side="yes",
    )


def test_nfl_pair_emits_two_complements() -> None:
    home, away = "KC", "DEN"
    home_row = _ml_row(side=home, ticker="KXNFLGAME-26SEP14DENKC-KC")
    away_row = _ml_row(side=away, ticker="KXNFLGAME-26SEP14DENKC-DEN")
    idx = {row_key(home_row): home_row, row_key(away_row): away_row}
    comps = attach_kalshi_moneyline_complements(idx, league="nfl", sport=Sport.FOOTBALL)
    assert len(comps) == 2
    by_side = {c.side: c for c in comps}
    assert by_side[home].kalshi_complement
    assert by_side[home].kalshi_ticker == away_row.kalshi_ticker
    assert by_side[home].kalshi_side == "no"
    assert by_side[home].optic_id == home_row.optic_id
    assert by_side[away].kalshi_ticker == home_row.kalshi_ticker
    assert by_side[away].kalshi_side == "no"


def test_complement_carries_no_other_book_stamp() -> None:
    """Satellite shares the parent's MERGE key — only Kalshi may ride on it."""
    home = _ml_row(side="KC", ticker="KXNFLGAME-26SEP14DENKC-KC")
    away = _ml_row(side="DEN", ticker="KXNFLGAME-26SEP14DENKC-DEN")
    for row in (home, away):
        row.px_event_id = 20023311
        row.px_line_id = "px-line"
        row.crypto_security_id = "SID-1"
        row.crypto_symbol = "NX.F.OPT.NFL-1"
        row.polymarket_clob_token_id = "clob-1"
        row.polymarket_usa_market_id = "pusa-1"
        row.novig_outcome_id = "novig-1"
        row.runshop_market_id = 7
    idx = {row_key(home): home, row_key(away): away}
    other_book = tuple(
        name for name in CanonicalRow.model_fields
        if name.startswith(("px_", "crypto_", "polymarket_", "novig_",
                            "huddle_", "runshop_"))
        and name not in ("crypto_satellite", "polymarket_usa_satellite")
    )
    for comp in attach_kalshi_moneyline_complements(idx, league="nfl", sport=Sport.FOOTBALL):
        assert comp.optic_id is not None
        assert [f for f in other_book if getattr(comp, f) is not None] == []


def test_one_sided_ticker_skips() -> None:
    home_row = _ml_row(side="KC", ticker="KXNFLGAME-26SEP14DENKC-KC")
    idx = {row_key(home_row): home_row}
    assert attach_kalshi_moneyline_complements(idx, league="nfl", sport=Sport.FOOTBALL) == []


@pytest.mark.parametrize(
    ("league", "sport"),
    [
        ("ncaaf", Sport.FOOTBALL),         # game rules omit ties
        ("cricket_odi", Sport.CRICKET),    # ties / rain no-results
        ("npb", Sport.BASEBALL),           # tied after 12 innings
        ("kbo", Sport.BASEBALL),
        ("boxing_matches", Sport.BOXING),  # draws are routine
        ("khl", Sport.HOCKEY),             # unreviewed league: fail closed
    ],
)
def test_league_off_the_allowlist_gets_no_complement(league: str, sport: Sport) -> None:
    rows = [
        _ml_row(side=side, home="AAA", away="BBB", ticker=f"T-{side}")
        for side in ("AAA", "BBB")
    ]
    idx = {row_key(r): r for r in rows}
    assert attach_kalshi_moneyline_complements(idx, league=league, sport=sport) == []


@pytest.mark.parametrize("sport", [Sport.BASKETBALL, Sport.TENNIS, Sport.ESPORTS])
def test_drawless_sports_complement_in_every_league(sport: Sport) -> None:
    rows = [
        _ml_row(side=side, home="AAA", away="BBB", ticker=f"T-{side}")
        for side in ("AAA", "BBB")
    ]
    idx = {row_key(r): r for r in rows}
    assert len(attach_kalshi_moneyline_complements(
        idx, league="some_new_league", sport=sport)) == 2


def test_soccer_3way_skips() -> None:
    home = CanonicalRow(
        league="epl",
        start_date="2026-09-12T15:00:00Z",
        home="LIV",
        away="CHE",
        market_type=MarketType.MONEYLINE_3WAY.value,
        side="LIV",
        optic_id="odd-epl",
        kalshi_ticker="KXEPLGAME-26SEP12LIVCHE-LIV",
        kalshi_scope="Game",
        kalshi_side="yes",
    )
    idx = {row_key(home): home}
    assert attach_kalshi_moneyline_complements(idx, league="nfl", sport=Sport.FOOTBALL) == []


# --- 3-way soccer: GAME No → Optic double chance ---------------------------

_ENG, _ESP = "ENG", "ESP"
_NL_EVENT = "KXUEFANLGAME-26SEP26ENGESP"


def _nl_row(market_type: MarketType, side: str, **extra) -> CanonicalRow:
    return CanonicalRow(
        league="uefa_nations_league",
        start_date="2026-09-26T18:45:00Z",
        home=_ENG,
        away=_ESP,
        market_type=market_type.value,
        side=side,
        **extra,
    )


def _nl_yes(suffix: str, side: str, **extra) -> CanonicalRow:
    return _nl_row(
        MarketType.MONEYLINE_3WAY, side,
        optic_id=f"ml-{side}",
        kalshi_ticker=f"{_NL_EVENT}-{suffix}",
        kalshi_scope="Game",
        kalshi_side="yes",
        **extra,
    )


def _nl_dc(side: str, **extra) -> CanonicalRow:
    return _nl_row(MarketType.DOUBLE_CHANCE, side, optic_id=f"dc-{side}", **extra)


def _nl_index(*rows: CanonicalRow) -> dict[tuple, CanonicalRow]:
    return {row_key(r): r for r in rows}


_NL_DC_ROWS = (_nl_dc("ENG/ESP"), _nl_dc("ENG/_TIE"), _nl_dc("ESP/_TIE"))


def test_each_game_no_lands_on_the_double_chance_excluding_it() -> None:
    idx = _nl_index(
        _nl_yes("ENG", _ENG), _nl_yes("ESP", _ESP), _nl_yes("TIE", TIE_SIDE),
        *_NL_DC_ROWS,
    )
    comps = attach_kalshi_double_chance_complements(idx)
    by_ticker = {c.kalshi_ticker: c for c in comps}
    assert {t: c.side for t, c in by_ticker.items()} == {
        f"{_NL_EVENT}-ENG": "ESP/_TIE",
        f"{_NL_EVENT}-ESP": "ENG/_TIE",
        f"{_NL_EVENT}-TIE": "ENG/ESP",
    }
    for comp in comps:
        assert comp.kalshi_side == "no"
        assert comp.kalshi_complement
        assert comp.market_type == MarketType.DOUBLE_CHANCE.value
        assert comp.optic_id == f"dc-{comp.side}"


def test_one_yes_ticker_is_enough() -> None:
    idx = _nl_index(_nl_yes("TIE", TIE_SIDE), *_NL_DC_ROWS)
    comps = attach_kalshi_double_chance_complements(idx)
    assert [(c.kalshi_ticker, c.side) for c in comps] == [
        (f"{_NL_EVENT}-TIE", "ENG/ESP"),
    ]


def test_missing_double_chance_odd_skips() -> None:
    idx = _nl_index(_nl_yes("ENG", _ENG), _nl_dc("ENG/_TIE"), _nl_dc("ENG/ESP"))
    assert attach_kalshi_double_chance_complements(idx) == []


def test_double_chance_without_optic_odd_or_already_stamped_skips() -> None:
    idx = _nl_index(
        _nl_yes("ENG", _ENG),
        _nl_row(MarketType.DOUBLE_CHANCE, "ESP/_TIE", optic_id=None),
    )
    assert attach_kalshi_double_chance_complements(idx) == []
    stamped = _nl_dc(
        "ESP/_TIE", kalshi_ticker=f"{_NL_EVENT}-ENG",
        kalshi_scope="Game", kalshi_side="no")
    idx = _nl_index(_nl_yes("ENG", _ENG), stamped)
    assert attach_kalshi_double_chance_complements(idx) == []


def test_only_yes_rows_complement() -> None:
    yes = _nl_yes("ENG", _ENG)
    yes.kalshi_side = "no"
    assert attach_kalshi_double_chance_complements(
        _nl_index(yes, *_NL_DC_ROWS)) == []


def test_double_chance_complement_carries_no_other_book_stamp() -> None:
    dc = _nl_dc(
        "ESP/_TIE", crypto_security_id="SID-1",
        crypto_symbol="NX.F.OPT.UNL-1", polymarket_usa_market_id="pusa-1")
    comps = attach_kalshi_double_chance_complements(
        _nl_index(_nl_yes("ENG", _ENG), dc))
    assert len(comps) == 1
    assert comps[0].crypto_symbol is None
    assert comps[0].polymarket_usa_market_id is None
    assert dc.crypto_symbol == "NX.F.OPT.UNL-1"  # parent untouched



_NL_1H_EVENT = "KXUEFANL1H-26SEP26ENGESP"


def _nl_1h_yes(suffix: str, side: str) -> CanonicalRow:
    return _nl_row(
        MarketType.FIRST_HALF_WINNER_3WAY, side,
        optic_id=f"1h-{side}",
        kalshi_ticker=f"{_NL_1H_EVENT}-{suffix}",
        kalshi_scope="1st Half Winner",
        kalshi_side="yes",
    )


def _nl_1h_dc(side: str) -> CanonicalRow:
    return _nl_row(
        MarketType.FIRST_HALF_DOUBLE_CHANCE, side, optic_id=f"1hdc-{side}")


def test_first_half_no_lands_on_the_first_half_double_chance() -> None:
    idx = _nl_index(
        _nl_1h_yes("ENG", _ENG), _nl_1h_yes("ESP", _ESP),
        _nl_1h_yes("TIE", TIE_SIDE),
        _nl_1h_dc("ENG/ESP"), _nl_1h_dc("ENG/_TIE"), _nl_1h_dc("ESP/_TIE"),
    )
    comps = attach_kalshi_double_chance_complements(idx)
    assert {c.kalshi_ticker: (c.market_type, c.side) for c in comps} == {
        f"{_NL_1H_EVENT}-ENG": ("1h_double_chance", "ESP/_TIE"),
        f"{_NL_1H_EVENT}-ESP": ("1h_double_chance", "ENG/_TIE"),
        f"{_NL_1H_EVENT}-TIE": ("1h_double_chance", "ENG/ESP"),
    }
    assert all(c.kalshi_side == "no" and c.kalshi_complement for c in comps)


def test_periods_never_cross() -> None:
    """A full-game No must not land on the 1H double chance, nor vice versa."""
    idx = _nl_index(
        _nl_yes("ENG", _ENG), _nl_1h_dc("ESP/_TIE"),
        _nl_1h_yes("ESP", _ESP), _nl_dc("ENG/_TIE"),
    )
    assert attach_kalshi_double_chance_complements(idx) == []


def test_other_fixture_double_chance_is_not_used() -> None:
    other = _nl_dc("ESP/_TIE")
    other.start_date = "2026-10-01T18:45:00Z"
    assert attach_kalshi_double_chance_complements(
        _nl_index(_nl_yes("ENG", _ENG), other)) == []
