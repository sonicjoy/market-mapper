"""Polymarket US Path 2 helpers: team-code resolve, complement keys, Optic index.

Stamping/stripping runs on structured gateway fields — see
``test_polymarket_usa_structured.py``. No symbol is ever parsed.
"""

from __future__ import annotations

from mappers.exchanges import optic
from mappers.exchanges.polymarket import PolymarketConfig
from mappers.exchanges.polymarket_usa_match import resolve_team_code
from mappers.market_types import MarketType
from mappers.pipeline import (
    _build_optic_usa_index,
    _usa_complement_key,
    _usa_optic_agree,
    row_key,
)
from mappers.shared import CanonicalRow
from mappers.vocab.soccer_markets import SOCCER_OPTIC_CUP_TABLE_TYPES, soccer_market_rules

_SOCCER_POLY = PolymarketConfig(
    slug_prefix="uecl",
    optic_league_id="uefa_-_europa_conference_league",
    market_types={
        "moneyline": MarketType.MONEYLINE_3WAY,
        "btts": MarketType.BTTS,
        "to_advance": MarketType.TO_ADVANCE,
        "spread": MarketType.POINT_SPREAD,
        "total": MarketType.GAME_TOTAL,
    },
    market_rules=soccer_market_rules,
)


def test_resolve_team_code_skips_canonical_key_not_on_fixture():
    """Kalshi WHU → WHUF6 must not break bind against Optic abbr WHU."""
    sides = {"MIL", "WHU"}
    assert resolve_team_code(
        "whu", {}, {"whu": "WHUF6"}, fixture_sides=sides,
    ) == "WHU"
    assert resolve_team_code(
        "por", {"por": "POR"}, {}, fixture_sides={"POR", "BBR"},
    ) == "POR"


_MLB_POLY = PolymarketConfig(
    slug_prefix="mlb",
    optic_league_id="mlb",
    market_types={
        "moneyline": MarketType.MONEYLINE,
        "spread": MarketType.POINT_SPREAD,
        "total": MarketType.GAME_TOTAL,
    },
    market_rules=(),
)


_MLB_ALIASES = {"sea": "SEA", "tor": "TOR", "tex": "TEX", "mil": "MIL"}


def _mlb_spread_row(*, side: str, line: float, optic_id: str) -> CanonicalRow:
    return CanonicalRow(
        league="mlb",
        start_date="2026-08-28T23:40:00Z",
        home="MIL",
        away="TEX",
        market_type=MarketType.POINT_SPREAD.value,
        side=side,
        line=line,
        optic_id=optic_id,
    )


def test_usa_complement_key_spread_and_total():
    """TEX -1.5 and MIL +1.5 are the same run line; over/under swap the label."""
    tex = row_key(_mlb_spread_row(side="TEX", line=-1.5, optic_id="a"))
    mil = row_key(_mlb_spread_row(side="MIL", line=1.5, optic_id="b"))
    assert _usa_complement_key(tex) == mil
    assert _usa_complement_key(mil) == tex

    over = (
        "mlb", "2026-08-28T23:40:00Z", "MIL", "TEX",
        MarketType.GAME_TOTAL.value, None, 8.5, "over", None,
    )
    under = (
        "mlb", "2026-08-28T23:40:00Z", "MIL", "TEX",
        MarketType.GAME_TOTAL.value, None, 8.5, "under", None,
    )
    assert _usa_complement_key(over) == under
    assert _usa_complement_key(under) == over

    ml = (
        "mlb", "2026-08-28T23:40:00Z", "MIL", "TEX",
        MarketType.MONEYLINE.value, None, None, "TEX", None,
    )
    assert _usa_complement_key(ml) is None


def test_usa_optic_agree_accepts_complement_listing():
    """Optic hanging the ticker on the plus side still covers Path 2's minus."""
    tex = row_key(_mlb_spread_row(side="TEX", line=-1.5, optic_id="a"))
    mil = row_key(_mlb_spread_row(side="MIL", line=1.5, optic_id="b"))
    assert _usa_optic_agree(tex, {mil})
    assert _usa_optic_agree(tex, {tex, mil})
    wrong_line = row_key(_mlb_spread_row(side="MIL", line=2.5, optic_id="c"))
    assert not _usa_optic_agree(tex, {wrong_line})


def test_usa_index_keeps_both_spread_sides():
    """US ticker is a market id; the index must not last-write-wins one side."""
    ticker = "asc-mlb-tex-mil-2026-08-28-neg-1pt5"
    tex = _mlb_spread_row(side="TEX", line=-1.5, optic_id="odd-tex")
    mil = _mlb_spread_row(side="MIL", line=1.5, optic_id="odd-mil")
    src = {"Polymarket (USA)": {"market_id": ticker}}
    odds = {
        "odd-tex": optic.Odd(
            id="g:book:run_line:tex", market_id="run_line",
            grouping_key="default", source_ids=src,
        ),
        "odd-mil": optic.Odd(
            id="g:book:run_line:mil", market_id="run_line",
            grouping_key="default", source_ids=src,
        ),
    }
    idx = _build_optic_usa_index(
        {row_key(tex): tex, row_key(mil): mil}, odds,
    )
    keys = idx[ticker]
    assert row_key(tex) in keys
    assert row_key(mil) in keys
    assert _usa_optic_agree(row_key(tex), keys)


_CFB_POLY = PolymarketConfig(
    slug_prefix="cfb",
    optic_league_id="ncaaf",
    market_types={
        "moneyline": MarketType.MONEYLINE,
        "spread": MarketType.POINT_SPREAD,
        "total": MarketType.GAME_TOTAL,
    },
    market_rules=(),
)
_CFB_ALIASES = {"ncar": "UNC", "tcu": "TCU"}


def test_soccer_optic_cup_has_to_advance():
    assert "to_advance" in SOCCER_OPTIC_CUP_TABLE_TYPES


_CS2_POLY = PolymarketConfig(
    slug_prefix="cs2",
    optic_league_id="cs2",
    market_types={
        "moneyline": MarketType.MONEYLINE,
        "map_handicap": MarketType.MAP_HANDICAP,
        "total_maps": MarketType.TOTAL_MAPS,
    },
    market_rules=(),
)
_CS2_ALIASES = {"war": "WAR6", "mars": "MAR7"}
_HCAP_OFFICIAL = "asc-cs2-war-mars-2026-09-11-hcap-neg-1pt5"
_HCAP_REVERSED = "asc-cs2-mars-war-2026-09-11-hcap-neg-1pt5"
_TRUE_START = "2026-09-11T23:00:00Z"
_CLONE_START = "2026-09-10T20:00:00Z"
_CS2_STARTS = {"cs2-war-mars-2026-09-11": _TRUE_START}


def _cs2_hcap_row(
    *, start: str, home: str, away: str, side: str, line: float, optic_id: str,
) -> CanonicalRow:
    return CanonicalRow(
        league="cs2",
        start_date=start,
        home=home,
        away=away,
        market_type=MarketType.MAP_HANDICAP.value,
        side=side,
        line=line,
        optic_id=optic_id,
    )


def _usa_odd(oid: str, ticker: str) -> optic.Odd:
    return optic.Odd(
        id=oid,
        market_id="map_handicap",
        grouping_key="default",
        source_ids={"Polymarket (USA)": {"market_id": ticker}},
    )


