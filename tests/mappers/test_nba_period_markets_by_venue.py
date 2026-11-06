"""NBA period winners and second-half lines, on every venue (2026-10-21/23).

Rule (owner 2026-10-23): map only what settles like Optic, from data.

- Optic's grader settles 1st_half / Nth_quarter_moneyline_3-way on the period
  alone (a tied period: Draw won, both teams lost) and its 2nd_half_* winner,
  spread and total, and 4th_quarter_*, on regulation.
- Polymarket US: 1H and Q1-Q4 winners settle like that (36/36 outcomes on
  2026-10-22, the venue's 4Q excludes overtime). Its 2H lines count overtime:
  held, Optic's passthrough stripped.
- Kalshi: a basketball 2H / 4Q market maps only when its rules exclude
  overtime (NBA 2H counts it: held; NBA Q4 and WNBA exclude it; NBA Q4
  winner 39/39 settled outcomes agree with Optic).
- DKEX: a tied period settles 50/50, its H2 counts overtime: winners and H2
  held.
- Underdog: 1H and Q1-Q4 winners and the 1H team total map (the filings keep
  overtime out of a named quarter or half); the 2H winner says "second half
  and overtime"; the TIE leg reads "beat ... by exactly 0 points".

Polymarket US payload trimmed from gateway ``/v1/events/147254`` (ATL Hawks vs.
ORL Magic, 2026-10-21): three markets per period (away, Tie, home).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from fetch.polymarket_usa import market_record
from mappers.exchanges import kalshi, kalshi_regulation, optic
from mappers.exchanges import polymarket_usa_structured as pus
from mappers.exchanges.optic_passthrough_crosscheck import CrosscheckLedger
from mappers.exchanges.underdog import build_rows, parse_contract
from mappers.market_types import MarketType
from mappers.pipeline import _strip_unverified_usa_passthrough, row_key
from mappers.shared import TIE_SIDE, CanonicalRow
from mappers.sport import Sport
from mappers.vocab import dkex_markets
from mappers.vocab.basketball_markets import BASKETBALL_OPTIC_TABLE_TYPES
from mappers.vocab.poly_usa_smt import not_equivalent_types, smt_spec
from mappers.vocab.underdog_markets import market_types_for_sport

_START = "2026-10-21T23:00:00Z"
_EVENT: dict[str, Any] = {
    "id": "147254", "slug": "nba-atl-orl-2026-10-21", "startTime": _START,
    "teams": [
        {"id": 25, "abbreviation": "atl", "name": "Hawks"},
        {"id": 28, "abbreviation": "orl", "name": "Magic"},
    ],
}
_PERIODS = {
    "fh": ("basketball_team_first_half_winner", "1h_winner_3way"),
    "sh": ("basketball_team_second_half_winner", None),
    "q1": ("basketball_team_first_quarter_winner", "1q_winner_3way"),
    "q2": ("basketball_team_second_quarter_winner", "2q_winner_3way"),
    "q3": ("basketball_team_third_quarter_winner", "3q_winner_3way"),
    "q4": ("basketball_team_fourth_quarter_winner", "4q_winner_3way"),
}
_TEAM_IDS = {"atl": 25, "orl": 28, "draw": None}


def _gateway_market(period: str, outcome: str) -> dict[str, Any]:
    team_id = _TEAM_IDS[outcome]
    team = {"id": team_id} if team_id is not None else None
    slug = f"atc-nba-atl-orl-2026-10-21-{period}-{outcome}"
    return {
        "id": f"{period}{outcome}", "slug": slug, "sportsMarketType": _PERIODS[period][0],
        "metadata": {"teamId": team_id} if team_id is not None else None,
        "marketSides": [
            {"id": f"{slug}-y", "long": True, "description": "Yes", "team": team},
            {"id": f"{slug}-n", "long": False, "description": "No", "team": team},
        ],
    }


def _group(period: str) -> list[pus.UsMarket]:
    out = []
    for outcome in ("atl", "draw", "orl"):
        record = market_record(_gateway_market(period, outcome), _EVENT, 2)
        assert record is not None
        market = pus.parse_market(record)
        assert market is not None
        out.append(market)
    return out


def _bind() -> pus.EventBind:
    fx = SimpleNamespace(start_date=_START, home="ORL", away="ATL")
    return pus.EventBind(fixture=fx, team_sides={"25": "ATL", "28": "ORL"})


# === Polymarket US ===


@pytest.mark.parametrize("period", ["fh", "q1", "q2", "q3", "q4"])
def test_polyus_period_winner_maps_away_tie_home(period: str):
    mt = _PERIODS[period][1]
    group = _group(period)
    draws = pus.draw_market_ids(group)
    assert [pus.market_bets(m, _bind(), draws) for m in group] == [
        [(mt, None, None, "ATL")], [(mt, None, None, TIE_SIDE)], [(mt, None, None, "ORL")],
    ]


def test_polyus_second_half_lines_are_held():
    for smt in ("basketball_team_second_half_winner", "basketball_team_second_half_spread",
                "basketball_team_second_half_total"):
        assert smt_spec(smt) is None
    group = _group("sh")
    draws = pus.draw_market_ids(group)
    assert all(pus.market_bets(m, _bind(), draws) == [] for m in group)
    assert not_equivalent_types("basketball") == frozenset(
        {"2h_winner_3way", "2h_point_spread", "2h_total"},
    )
    # Football 2H maps despite its OT difference (ruled 2026-09-26).
    assert not_equivalent_types("football") == frozenset()


def test_every_polyus_period_winner_has_an_optic_market():
    optic_types = {mt.value for mt in BASKETBALL_OPTIC_TABLE_TYPES.values()}
    for _smt, mt in _PERIODS.values():
        assert mt is None or mt in optic_types
    assert BASKETBALL_OPTIC_TABLE_TYPES["4th_quarter_moneyline_3-way"] is (
        MarketType.FOURTH_QUARTER_WINNER_3WAY
    )


def _row(market_type: str, side: str) -> CanonicalRow:
    return CanonicalRow(
        league="nba", start_date=_START, home="ORL", away="ATL",
        market_type=market_type, side=side, optic_id="o",
    )


def _strip(
    row: CanonicalRow, slug: str, markets: list[pus.UsMarket],
    computed: list[CanonicalRow] | None = None,
    ledger: CrosscheckLedger | None = None,
) -> int:
    odd = optic.Odd(
        id="o", market_id="x", grouping_key="default",
        source_ids={"Polymarket (USA)": {"market_id": slug}},
    )
    return _strip_unverified_usa_passthrough(
        {row_key(row): row}, {"o": odd}, markets, {"147254": _bind()},
        {slug: computed} if computed else {}, ledger,
        held_types=not_equivalent_types("basketball"),
    )


def test_polyus_second_half_passthrough_is_stripped():
    """Optic hangs the venue's 2H (OT included) on its regulation 2H 3-way."""
    ledger = CrosscheckLedger()
    sh_orl = _group("sh")[2]
    assert _strip(_row("2h_winner_3way", "ORL"), sh_orl.slug, [sh_orl], ledger=ledger) == 1
    assert [r["detail"] for r in ledger.disagreements] == ["not_equivalent"]


def test_polyus_held_passthrough_is_stripped_when_snapshot_lacks_the_symbol():
    """No gateway snapshot (harvest failed): the held types still go."""
    assert _strip(_row("2h_winner_3way", "ORL"), "atc-nba-atl-orl-2026-10-21-sh-orl", []) == 1
    assert _strip(_row("2h_point_spread", "ORL"), "asc-nba-atl-orl-2026-10-21-sh-pos-1pt5", []) == 1
    # Any other unknown symbol is still kept.
    assert _strip(_row("1h_winner_3way", "ORL"), "atc-nba-never-seen", []) == 0


def test_polyus_first_half_passthrough_agreeing_with_our_row_is_kept():
    fh_orl = _group("fh")[2]
    row = _row("1h_winner_3way", "ORL")
    assert _strip(row, fh_orl.slug, [fh_orl], computed=[row]) == 0
    other = _row("1h_winner_3way", "ATL")
    assert _strip(row, fh_orl.slug, [fh_orl], computed=[other]) == 1


# === Kalshi ===

_NBA_2H = ("If Cleveland wins by more than 10.5 points in the 2nd half (including overtime) of the "
           "Cleveland vs Philadelphia Pro Basketball game originally scheduled for Oct 22, 2026, "
           "then the market resolves to Yes.")
_NBA_4Q = ("If over 46.5 total points are scored in the 4th quarter (excluding overtime)  of the "
           "Cleveland vs Philadelphia Pro Basketball game originally scheduled for Oct 22, 2026, "
           "then the market resolves to Yes.")
_WNBA_2H = ("If Atlanta is the winner of the second half (not including overtime) of regulation time "
            "in the Golden State vs Atlanta women's Pro Basketball game originally scheduled for "
            "Oct 24, 2026, then the market resolves to Yes.")


def _kalshi(scope: str, rules: str) -> kalshi.Market:
    return kalshi.Market.model_validate({
        "event_ticker": "E", "ticker": "T", "title": "t",
        "series_scope": scope, "competition_scope": scope, "rules_primary": rules,
    })


@pytest.mark.parametrize("scope,rules,expected", [
    # NBA 2nd half counts overtime: held.
    ("2nd Half Winner", _NBA_2H, None),
    ("2nd Half Spread", _NBA_2H, None),
    ("2nd Half Total", _NBA_2H, None),
    # WNBA 2nd half and NBA 4th quarter exclude it, as Optic: mapped.
    ("2nd Half Winner", _WNBA_2H, "2h_winner_3way"),
    ("4th Quarter Winner", _NBA_4Q, "4q_winner_3way"),
    ("4th Quarter Total", _NBA_4Q, "4q_total"),
    # Rules that state no basis: held.
    ("2nd Half Total", "", None),
    # Periods overtime cannot reach: unaffected.
    ("1st Half Winner", "", "1h_winner_3way"),
])
def test_kalshi_basketball_period_maps_only_on_a_regulation_basis(
    scope: str, rules: str, expected: str | None,
):
    mt = kalshi.scoped_market_type(_kalshi(scope, rules), kalshi.KalshiConfig(sport=Sport.BASKETBALL))
    assert (mt.value if mt else None) == expected


def test_kalshi_football_second_half_is_unaffected():
    mt = kalshi.scoped_market_type(
        _kalshi("2nd Half Winner", _NBA_2H), kalshi.KalshiConfig(sport=Sport.FOOTBALL),
    )
    assert mt is MarketType("2h_winner_3way")


def test_kalshi_missing_rules_primary_is_held_and_reported(capsys: pytest.CaptureFixture[str]):
    kalshi_regulation.report_missing_rules()  # drain misses from earlier tests
    capsys.readouterr()
    cfg = kalshi.KalshiConfig(sport=Sport.BASKETBALL)
    market = kalshi.Market.model_validate({
        "event_ticker": "E", "ticker": "T-NOPRIM", "title": "t",
        "series_scope": "2nd Half Total", "competition_scope": "2nd Half Total",
    })
    assert kalshi.scoped_market_type(market, cfg) is None
    kalshi_regulation.report_missing_rules()
    err = capsys.readouterr().err
    assert err.count("ALERT") == 1 and "T-NOPRIM" in err
    kalshi_regulation.report_missing_rules()
    assert capsys.readouterr().err == ""


# === DKEX ===


def test_dkex_basketball_winners_and_second_half_are_held():
    table = dkex_markets.BASKETBALL
    for period in ("H1", "Q1", "Q2", "Q3", "Q4", "H2"):
        assert ("WIN", period) not in table
    for product in ("MOVY", "TPTS", "TMPTS"):
        assert (product, "H2") not in table
    assert table[("MOVY", "H1")] is MarketType.FIRST_HALF_POINT_SPREAD
    assert table[("TPTS", "Q3")] is MarketType.THIRD_QUARTER_TOTAL


# === Underdog ===


def _udx(period: str, sel: str, description: str, market_id: str) -> dict[str, Any]:
    return {
        "ticker": f"UDXNBAGAMEWIN{period}_CLEPHI26OCT22_{sel}",
        "description": description,
        "external_ids": {"optic_odds": {"fixture_id": "20261022205C4E07", "market_id": market_id}},
        "expires_at": "2026-10-25T23:00:00.000000Z",
    }


_WHEN = "originally scheduled for 7:00pm ET on October 22, 2026."
_GAME = "of the National Basketball Association game between the Cleveland Cavaliers and the Philadelphia 76ers"


def test_underdog_basketball_crosswalk_maps_periods_but_not_the_2h_winner():
    table = market_types_for_sport(Sport.BASKETBALL)
    assert table["1st_half_moneyline_3-way"] is MarketType.FIRST_HALF_WINNER_3WAY
    for q, mt in (("1st", "FIRST"), ("2nd", "SECOND"), ("3rd", "THIRD"), ("4th", "FOURTH")):
        assert table[f"{q}_quarter_moneyline_3-way"] is MarketType[f"{mt}_QUARTER_WINNER_3WAY"]
    assert table["1st_half_team_total"] is MarketType.FIRST_HALF_TEAM_TOTAL
    # "second half and overtime", tagged with Optic's regulation-only 2H 3-way.
    assert "2nd_half_moneyline_3-way" not in table


def test_underdog_tie_leg_is_the_draw_not_the_named_team():
    """Live 2026-10-22 wording: the TIE leg names a team "by exactly 0 points"."""
    tie = parse_contract(_udx(
        "1Q", "TIE",
        f"Resolves Yes if the Philadelphia 76ers beat the Cleveland Cavaliers by exactly 0 points "
        f"during the first quarter {_GAME} {_WHEN}",
        "1st_quarter_moneyline_3-way",
    ))
    assert tie is not None and tie.is_draw
    rows = build_rows(tie, MarketType.FIRST_QUARTER_WINNER_3WAY, home="PHI", away="CLE",
                      start_date="2026-10-22T23:00:00Z", league="nba", team="PHI")
    assert [(r.side, r.underdog_side) for r in rows] == [(TIE_SIDE, "yes")]


def test_underdog_team_leg_maps_its_yes_only():
    team = parse_contract(_udx(
        "1H", "CLE",
        f"Resolves Yes if the Cleveland Cavaliers beat the Philadelphia 76ers by above 0.5 points "
        f"during the first half {_GAME} {_WHEN}",
        "1st_half_moneyline_3-way",
    ))
    assert team is not None and not team.is_draw
    rows = build_rows(team, MarketType.FIRST_HALF_WINNER_3WAY, home="PHI", away="CLE",
                      start_date="2026-10-22T23:00:00Z", league="nba", team="CLE")
    assert [(r.side, r.underdog_side) for r in rows] == [("CLE", "yes")]


def test_underdog_q4_tie_leg_is_the_draw():
    """Live 2026-10-23 wording (UDXNBAGAMEWIN4Q_ATLCHA26OCT23_TIE)."""
    tie = parse_contract(_udx(
        "4Q", "TIE",
        f"Resolves Yes if the Philadelphia 76ers beat the Cleveland Cavaliers by exactly 0 points "
        f"during the fourth quarter {_GAME} {_WHEN}",
        "4th_quarter_moneyline_3-way",
    ))
    assert tie is not None and tie.is_draw
    rows = build_rows(tie, MarketType.FOURTH_QUARTER_WINNER_3WAY, home="PHI", away="CLE",
                      start_date="2026-10-22T23:00:00Z", league="nba", team="PHI")
    assert [(r.side, r.underdog_side) for r in rows] == [(TIE_SIDE, "yes")]


def test_underdog_first_half_team_total_is_over_yes_under_no():
    """Live 2026-10-23 wording (UDXNBATEAMTOTAL1H_ATLCHA26OCT23_ATLOVER48.5)."""
    row = {
        "ticker": "UDXNBATEAMTOTAL1H_ATLCHA26OCT23_ATLOVER48.5",
        "description": (
            "Resolves Yes if the Atlanta Hawks records above 48.5 points scored during the first "
            "half of the National Basketball Association game between the Atlanta Hawks and the "
            "Charlotte Hornets originally scheduled for 7:00pm ET on October 23, 2026."
        ),
        "external_ids": {"optic_odds": {
            "fixture_id": "20261023A66A27C8", "market_id": "1st_half_team_total",
            "team_id": "B59C1C735494",
        }},
        "expires_at": "2026-10-26T14:00:00.000000Z",
    }
    contract = parse_contract(row)
    assert contract is not None and contract.line == 48.5 and not contract.is_draw
    rows = build_rows(contract, MarketType.FIRST_HALF_TEAM_TOTAL, home="CHA", away="ATL",
                      start_date="2026-10-23T23:00:00Z", league="nba", team="ATL")
    assert [(r.side, r.entity, r.line, r.underdog_side) for r in rows] == [
        ("over", "ATL", 48.5, "yes"), ("under", "ATL", 48.5, "no"),
    ]
