"""Underdog soccer exact score (UDXBRASILASCORE / SERIEASCORE / LIGAMXSCORE / LIGUE1SCORE, 2026-10-29).

Live wording from the prod catalogue, 2026-10-29 14:15Z. Each contract is one
winner-first scoreline over the 90 minutes ("during the entire game excluding
extra time"); Brazil states that only in ``rules``. Optic's correct_score is the
same scoreline, keyed by winner and ``correct_score_line``, so only YES maps.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from mappers.exchanges.underdog import UnderdogConfig, build_rows, parse_contract, sentence_score
from mappers.exchanges.underdog_pass import run_pass, soccer_basis_stated
from mappers.market_types import MarketType
from mappers.shared import TIE_SIDE
from mappers.sport import Sport
from mappers.vocab.underdog_markets import market_types_for_sport

_BRA_FX = "2026103056226A18"
_BRA_GAME = (
    "Brazil Série A match between Grêmio FB Porto Alegrense and Club Athletico Paranaense "
    "originally scheduled for 8:30pm ET on October 29, 2026"
)
_BRA_RULES = (
    "The Underlying is the ordered pair of final goal totals credited to the two participating "
    f"teams during the entire game excluding extra time of {_BRA_GAME}, as published under the "
    "Source Agency hierarchy. Goals outside the entire game excluding extra time do not count."
)
_ITA_FX = "2026102981437737"


def _row(ticker: str, description: str, fixture_id: str, rules: str = "", team_id: str | None = None) -> dict[str, Any]:
    optic = {"fixture_id": fixture_id, "market_id": "correct_score"}
    if team_id:
        optic["team_id"] = team_id
    return {
        "ticker": ticker,
        "description": description,
        "rules": rules,
        "external_ids": {"optic_odds": optic},
        "expires_at": "2026-11-01T15:00:00.000000Z",
    }


_BRA_AWAY = _row(
    "UDXBRASILASCORE_CAPGRE26OCT29_CAP4_2",
    f"Resolves Yes if the score of {_BRA_GAME} is exactly Club Athletico Paranaense to win 4–2.",
    _BRA_FX,
    _BRA_RULES,
    "01A839E37148",
)
_BRA_DRAW = _row(
    "UDXBRASILASCORE_CAPGRE26OCT29_DRAW0_0",
    f"Resolves Yes if the score of {_BRA_GAME} is exactly 0–0 draw.",
    _BRA_FX,
    _BRA_RULES,
)
_MEX_AWAY = _row(
    "UDXLIGAMXSCORE_ATSASL26OCT30_ATS4_2",
    "Resolves Yes if the score of the Mexican Liga MX game between the Atlas FC and the Atlético "
    "de San Luis originally scheduled for 9:00pm ET on October 30, 2026 during the entire game "
    "excluding extra time is exactly Atlas FC to win 4–2.",
    "20261031C7B82617",
)
_ITA_HOME = _row(
    "UDXSERIEASCORE_ATAFIO26OCT29_FIO3_2",
    "Resolves Yes if Italian Serie A match between ACF Fiorentina and Atalanta Bergamasca Calcio "
    "originally scheduled for 3:45pm ET on October 29, 2026 has a score of ACF Fiorentina to win "
    "3–2 during the entire game excluding extra time.",
    _ITA_FX,
)
_ITA_DRAW = _row(
    "UDXSERIEASCORE_ATAFIO26OCT29_DRAW1_1",
    "Resolves Yes if Italian Serie A match between ACF Fiorentina and Atalanta Bergamasca Calcio "
    "originally scheduled for 3:45pm ET on October 29, 2026 has a score of 1–1 draw during the "
    "entire game excluding extra time.",
    _ITA_FX,
)
_FRA_AWAY = _row(
    "UDXLIGUE1SCORE_PSGHAC26OCT30_HAC20",
    "Resolves Yes if the score of the entire game excluding extra time of match between Le Havre AC "
    "and Paris Saint-Germain FC originally scheduled for 2:00pm ET on October 30, 2026 is exactly "
    "Le Havre AC to win 2–0.",
    "2026103006894AF0",
)
_FRA_DRAW = _row(
    "UDXLIGUE1SCORE_PSGHAC26OCT30_DRAW11",
    "Resolves Yes if the score of the entire game excluding extra time of match between Le Havre AC "
    "and Paris Saint-Germain FC originally scheduled for 2:00pm ET on October 30, 2026 is exactly "
    "1–1 draw.",
    "2026103006894AF0",
)


def test_crosswalk_maps_correct_score():
    assert market_types_for_sport(Sport.SOCCER)["correct_score"] is MarketType.CORRECT_SCORE


@pytest.mark.parametrize(
    "row,expected",
    [
        (_BRA_AWAY, ("Club Athletico Paranaense", 4, 2)),
        (_BRA_DRAW, ("", 0, 0)),
        (_MEX_AWAY, ("Atlas FC", 4, 2)),
        (_ITA_HOME, ("ACF Fiorentina", 3, 2)),
        (_ITA_DRAW, ("", 1, 1)),
        (_FRA_AWAY, ("Le Havre AC", 2, 0)),
        (_FRA_DRAW, ("", 1, 1)),
    ],
)
def test_sentence_score_reads_winner_first(row: dict[str, Any], expected: tuple):
    assert sentence_score(row["description"]) == expected
    contract = parse_contract(row)
    assert contract is not None
    assert contract.score is not None
    assert (contract.yes_team, *contract.score) == expected


def _rows(row: dict[str, Any], *, home: str, away: str, team: str | None) -> list[tuple]:
    contract = parse_contract(row)
    assert contract is not None
    built = build_rows(
        contract,
        MarketType.CORRECT_SCORE,
        home=home,
        away=away,
        start_date="2026-10-30T00:30:00Z",
        league="brazil_serie_a",
        team=team,
    )
    return [(r.side, r.entity, r.line, r.underdog_side) for r in built]


def test_a_win_is_the_winner_and_the_winner_first_line_yes_only():
    assert _rows(_BRA_AWAY, home="GRE", away="CAP", team="CAP") == [("CAP", None, 4.02, "yes")]
    assert _rows(_ITA_HOME, home="FIO", away="ATA", team="FIO") == [("FIO", None, 3.02, "yes")]


def test_a_draw_is_the_tie_side():
    assert _rows(_BRA_DRAW, home="GRE", away="CAP", team=None) == [(TIE_SIDE, None, 0.0, "yes")]
    assert _rows(_ITA_DRAW, home="FIO", away="ATA", team=None) == [(TIE_SIDE, None, 1.01, "yes")]


def test_an_unresolved_winner_maps_nothing():
    assert _rows(_BRA_AWAY, home="GRE", away="CAP", team=None) == []


def test_liga_mx_and_serie_a_state_the_basis_in_the_sentence():
    assert soccer_basis_stated(MarketType.CORRECT_SCORE, _MEX_AWAY["description"], "liga_mx")
    assert soccer_basis_stated(MarketType.CORRECT_SCORE, _ITA_HOME["description"], "italy_serie_a")


def test_ligue_1_states_the_basis_as_the_score_of_the_entire_game():
    assert soccer_basis_stated(MarketType.CORRECT_SCORE, _FRA_AWAY["description"], "france_ligue_1")
    assert soccer_basis_stated(MarketType.CORRECT_SCORE, _FRA_DRAW["description"], "france_ligue_1")
    extra_time = _FRA_AWAY["description"].replace("excluding extra time", "including extra time")
    assert not soccer_basis_stated(MarketType.CORRECT_SCORE, extra_time, "france_ligue_1")


def test_brazil_states_the_basis_only_in_the_rules():
    assert not soccer_basis_stated(MarketType.CORRECT_SCORE, _BRA_AWAY["description"], "brazil_serie_a")
    assert soccer_basis_stated(
        MarketType.CORRECT_SCORE,
        _BRA_AWAY["description"],
        "brazil_serie_a",
        _BRA_RULES,
    )


def test_a_sentence_naming_another_basis_is_not_overridden_by_the_rules():
    extra_time = _ITA_HOME["description"].replace("excluding extra time", "including extra time")
    assert not soccer_basis_stated(MarketType.CORRECT_SCORE, extra_time, "italy_serie_a", _BRA_RULES)


def test_other_types_never_read_the_rules():
    sentence = "Resolves Yes if Grêmio FB Porto Alegrense record above 0.5 goals of " + _BRA_GAME
    assert not soccer_basis_stated(MarketType.TEAM_TOTAL, sentence, "brazil_serie_a", _BRA_RULES)


def _run(catalogue: list[dict[str, Any]]):
    stamped: list = []

    def attach(_index, _alt, _rows, item) -> str:
        stamped.append(item)
        return "stamped"

    entry = SimpleNamespace(
        fixture=SimpleNamespace(
            fixture_id=_BRA_FX,
            away="CAP",
            home="GRE",
            away_name="Club Athletico Paranaense",
            home_name="Grêmio FB Porto Alegrense",
            start_date="2026-10-30T00:30:00Z",
            team_map={},
            odds=[],
        )
    )
    cfg = UnderdogConfig(league="BRASILA", market_types=market_types_for_sport(Sport.SOCCER))
    tally = run_pass(catalogue, cfg, [entry], league="brazil_serie_a", attach=attach, row_index={}, all_rows=[])
    return tally, stamped


def test_pass_stamps_brazil_scores_and_holds_one_without_rules():
    no_rules = dict(
        _BRA_AWAY,
        ticker="UDXBRASILASCORE_CAPGRE26OCT29_CAP3_1",
        rules="",
        description=_BRA_AWAY["description"].replace("4–2", "3–1"),
    )
    tally, stamped = _run([_BRA_AWAY, _BRA_DRAW, no_rules])
    assert tally["stamped"] == 2
    assert tally["basis_unstated"] == 1
    assert sorted((r.side, r.line, r.underdog_side) for r in stamped) == [
        ("CAP", 4.02, "yes"),
        (TIE_SIDE, 0.0, "yes"),
    ]
    assert {r.market_type for r in stamped} == {"correct_score"}
