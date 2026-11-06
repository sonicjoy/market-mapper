"""Polymarket cricket moneyline recognizer (tip-only factory)."""

from mappers.exchanges import polymarket as pm
from mappers.exchanges.polymarket import PolymarketConfig
from mappers.market_types import MarketType
from mappers.vocab.cricket_markets import CRICKET_MARKET_TYPES

CFG = PolymarketConfig(
    slug_prefix="cricupt20",
    optic_league_id="india_-_uttar_pradesh_t20_league",
    market_types=dict(CRICKET_MARKET_TYPES),
    question_style="mlb_suffix",
    market_rules=pm.cricket_market_rules,
)

LIVE_MONEYLINES: list[tuple[str, str, str]] = [
    (
        "Uttar Pradesh T20: Gorakhpur Lions vs Kanpur Superstars",
        "gorakhpur lions",
        "kanpur superstars",
    ),
    (
        "Metro Bank One Day Cup Women: Hampshire Women vs Lancashire Women",
        "hampshire women",
        "lancashire women",
    ),
    (
        "South Africa and Zimbabwe Tour of Namibia T20s: Namibia vs Zimbabwe",
        "namibia",
        "zimbabwe",
    ),
]

UNMAPPABLE = [
    "Namibia vs Zimbabwe: Draw",
    "Will there be a draw?",
]


def test_cricket_moneyline_parses_live_titles() -> None:
    for question, want_a, want_b in LIVE_MONEYLINES:
        parsed = pm.parse_question(question, CFG)
        assert parsed is not None, question
        assert parsed.market_type is MarketType.MONEYLINE
        assert (parsed.team_a, parsed.team_b) == (want_a, want_b)


def test_cricket_draw_questions_stay_unrecognized() -> None:
    for question in UNMAPPABLE:
        assert pm.parse_question(question, CFG) is None, question
