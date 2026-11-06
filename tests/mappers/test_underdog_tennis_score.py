"""Underdog tennis exact set score (UDXATPSCORE / UDXATPCHLSCORE / UDXWTASCORE, 2026-11-05).

Live wording from the 2026-11-05 catalogue. Optic prices tennis correct_score as the
winner's player with a winner-first "2:1" line, so only YES maps, keyed like soccer.
"""

from __future__ import annotations

from mappers.exchanges.underdog import build_rows, parse_contract, sentence_score
from mappers.market_types import MarketType
from mappers.shared import correct_score_line
from mappers.vocab.underdog_markets import market_types_for_sport
from mappers.sport import Sport

_SENT = (
    "Resolves Yes if Ben Shelton wins the ATP Tour match between Arthur Rinderknech and "
    "Ben Shelton originally scheduled for 5:00am ET on November 5, 2026 by a final set score of 2–1."
)
_ROW = {
    "ticker": "UDXATPSCORE_RINSHE26NOV05_BENSHELTO21",
    "description": _SENT,
    "external_ids": {"optic_odds": {"fixture_id": "F1", "market_id": "correct_score", "player_id": "P"}},
    "expires_at": "2026-11-08T10:00:00.000000Z",
}


def test_vocab_maps_tennis_correct_score() -> None:
    assert market_types_for_sport(Sport.TENNIS)["correct_score"] is MarketType.CORRECT_SCORE


def test_sentence_score_reads_winner_and_sets() -> None:
    assert sentence_score(_SENT) == ("Ben Shelton", 2, 1)


def test_build_rows_is_single_yes_row_on_the_winner() -> None:
    contract = parse_contract(_ROW)
    assert contract is not None and contract.score == (2, 1)
    rows = build_rows(
        contract, MarketType.CORRECT_SCORE, home="RIN", away="SHE",
        start_date="2026-11-05T10:00:00Z", league="atp", team="SHE",
    )
    assert [(r.side, r.line, r.underdog_side, r.market_type) for r in rows] == [
        ("SHE", correct_score_line(2, 1), "yes", "correct_score")]


def test_unnamed_winner_maps_nothing() -> None:
    contract = parse_contract(_ROW)
    assert contract is not None
    assert build_rows(
        contract, MarketType.CORRECT_SCORE, home="RIN", away="SHE",
        start_date="2026-11-05T10:00:00Z", league="atp", team=None,
    ) == []
