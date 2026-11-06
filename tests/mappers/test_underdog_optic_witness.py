"""UDX external_ids.optic_odds witness checks."""

from __future__ import annotations

from types import SimpleNamespace

from mappers.exchanges.optic import Odd
from mappers.exchanges.underdog import UnderdogConfig
from mappers.exchanges.underdog_pass import run_pass
from mappers.exchanges.underdog_udx_optic_witness import check_udx_optic_witness, format_witness_alert
from mappers.market_types import MarketType
from mappers.shared import CanonicalRow
from mappers.sport import Sport
from mappers.vocab.underdog_markets import market_types_for_sport


def _fx(*, fixture_id: str = "FIX1", home: str = "CHI", away: str = "PHI", team_map: dict | None = None, odds=None):
    return SimpleNamespace(
        fixture_id=fixture_id,
        home=home,
        away=away,
        home_name="Chicago Bears",
        away_name="Philadelphia Eagles",
        team_map=team_map or {"7108F48884ED": home, "AAAA": away},
        odds=odds or [],
    )


def _yes_row(
    *,
    side: str = "CHI",
    entity: str | None = None,
    market_type: str = MarketType.MONEYLINE.value,
) -> CanonicalRow:
    return CanonicalRow(
        league="nfl",
        start_date="2026-09-29T00:15:00Z",
        home="CHI",
        away="PHI",
        market_type=market_type,
        entity=entity,
        line=None,
        side=side,
        underdog_ticker="UDXNFLGAMEWIN_PHICHI26SEP282015_CHI",
        underdog_side="yes",
    )


def test_missing_optic_block_passes() -> None:
    out = check_udx_optic_witness({}, _fx(), [_yes_row()])
    assert out.reject == ""


def test_fixture_mismatch_rejects() -> None:
    row = {"external_ids": {"optic_odds": {"fixture_id": "OTHER", "market_id": "moneyline"}}}
    out = check_udx_optic_witness(row, _fx(), [_yes_row()])
    assert out.reject == "optic_fixture"
    assert out.reject_line


def test_team_mismatch_rejects_when_id_maps_to_other_side() -> None:
    row = {
        "external_ids": {
            "optic_odds": {
                "fixture_id": "FIX1",
                "market_id": "moneyline",
                "team_id": "AAAA",
            },
        },
    }
    out = check_udx_optic_witness(row, _fx(), [_yes_row()])
    assert out.reject == "optic_team"


def test_unknown_team_id_does_not_reject() -> None:
    row = {
        "external_ids": {
            "optic_odds": {
                "fixture_id": "FIX1",
                "market_id": "moneyline",
                "team_id": "UNKNOWN_COMPETITOR",
            },
        },
    }
    out = check_udx_optic_witness(row, _fx(), [_yes_row()])
    assert out.reject == ""


def test_team_total_checks_team_id_against_entity() -> None:
    row = {
        "ticker": "UDXNFLTEAMTOTAL_PHICHI26SEP282015_CHI10.5",
        "external_ids": {
            "optic_odds": {
                "fixture_id": "FIX1",
                "market_id": "team_total",
                "team_id": "AAAA",
            },
        },
    }
    yes = _yes_row(side="over", entity="CHI", market_type=MarketType.TEAM_TOTAL.value)
    out = check_udx_optic_witness(row, _fx(), [yes])
    assert out.reject == "optic_team"


def test_player_prop_accepts_matching_optic_odd_player_id() -> None:
    row = {
        "ticker": "UDXNFLRECYDS_PHICHI26SEP282015COLEKMET_14.5",
        "external_ids": {
            "optic_odds": {
                "fixture_id": "FIX1",
                "market_id": "player_receiving_yards",
                "player_id": "10A863C5D176",
            },
        },
    }
    odds = [
        Odd(
            id="1",
            market_id="player_receiving_yards",
            selection="Cole Kmet",
            player_id="10A863C5D176",
            grouping_key="g",
        ),
    ]
    yes = _yes_row(side="over", entity="cole_kmet", market_type=MarketType.PLAYER_RECEIVING_YARDS.value)
    out = check_udx_optic_witness(row, _fx(odds=odds), [yes])
    assert out.reject == ""


def test_player_prop_unknown_id_does_not_reject() -> None:
    row = {
        "external_ids": {
            "optic_odds": {
                "fixture_id": "FIX1",
                "market_id": "player_receiving_yards",
                "player_id": "UNKNOWN",
            },
        },
    }
    yes = _yes_row(side="over", entity="cole_kmet", market_type=MarketType.PLAYER_RECEIVING_YARDS.value)
    out = check_udx_optic_witness(row, _fx(), [yes])
    assert out.reject == ""


def test_player_mismatch_rejects_on_matchwin() -> None:
    row = {
        "external_ids": {
            "optic_odds": {
                "fixture_id": "FIX1",
                "market_id": "moneyline",
                "player_id": "BBBB",
            },
        },
    }
    fx = _fx(home="EAGUIAR", away="ATM", team_map={"EC22BC642DAF49A1": "EAGUIAR", "BBBB": "ATM"})
    yes = _yes_row(side="EAGUIAR")
    yes.league = "atp_challenger"
    out = check_udx_optic_witness(row, fx, [yes])
    assert out.reject == "optic_player"


def _mov_row(player_id: str) -> dict:
    return {
        "ticker": "UDXUFCMOV_BONPRA26OCT101840_FPRADODEC",
        "external_ids": {
            "optic_odds": {"fixture_id": "FIX1", "market_id": "method_of_victory", "player_id": player_id},
        },
    }


def test_fighter_method_row_compares_optic_name_with_the_sides_full_name() -> None:
    fx = _fx(
        home="PRA", away="BON", team_map={"C1": "BON", "C2": "PRA"},
        odds=[
            Odd(id="1", market_id="method_of_victory", name="Francisco Prado - Decision",
                selection="Francisco Prado - Decision", player_id="P2", grouping_key="g"),
            Odd(id="2", market_id="moneyline", selection="Ismael Bonfim", player_id="P1", grouping_key="g"),
        ],
    )
    fx.home_name, fx.away_name = "Francisco Prado", "Ismael Bonfim"
    yes = _yes_row(side="yes", entity="PRA", market_type=MarketType.METHOD_OF_VICTORY.value)
    yes.league = "ufc"
    assert check_udx_optic_witness(_mov_row("P2"), fx, [yes]).reject == ""
    assert check_udx_optic_witness(_mov_row("P1"), fx, [yes]).reject == "optic_player"
    assert check_udx_optic_witness(_mov_row("UNKNOWN"), fx, [yes]).reject == ""


def test_format_witness_alert_lists_rejects() -> None:
    text = format_witness_alert("nfl", reject_lines=["reject one", "reject two"])
    assert "2 reject(s)" in text
    assert "reject one" in text


def test_run_pass_collects_reject_and_stamps_nothing() -> None:
    """UDX names the second game of a doubleheader; name + kickoff pick the first."""
    desc = (
        "Resolves Yes if the Chicago Bears win the National Football League game "
        "between the Philadelphia Eagles and the Chicago Bears originally scheduled "
        "for 8:15pm ET on September 28, 2026."
    )
    catalogue = [{
        "ticker": "T1",
        "description": desc,
        "status": "open",
        "external_ids": {
            "optic_odds": {
                "fixture_id": "FIX2",
                "market_id": "moneyline",
                "team_id": "7108F48884ED",
            },
        },
    }]

    def entry(fixture_id: str, start_date: str) -> SimpleNamespace:
        return SimpleNamespace(fixture=SimpleNamespace(
            fixture_id=fixture_id,
            away="PHI", home="CHI",
            away_name="Philadelphia Eagles", home_name="Chicago Bears",
            start_date=start_date,
            team_map={"7108F48884ED": "CHI", "AAAA": "PHI"},
            odds=[],
        ))

    stamped: list = []
    rejects: list[str] = []

    def attach(_index, _alt, _rows, item) -> str:
        stamped.append(item)
        return "stamped"

    cfg = UnderdogConfig(league="NFL", market_types=market_types_for_sport(Sport.FOOTBALL))
    tally = run_pass(
        catalogue, cfg,
        [entry("FIX1", "2026-09-29T00:15:00Z"), entry("FIX2", "2026-09-29T20:15:00Z")],
        league="nfl", attach=attach, row_index={}, all_rows=[],
        witness_reject_alerts=rejects,
    )
    assert tally["optic_fixture"] == 1
    assert tally["stamped"] == 0
    assert stamped == []
    assert rejects
