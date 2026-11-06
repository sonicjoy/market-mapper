"""Shared baseball Optic + Polymarket + PX + crypto.com taxonomy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from mappers.exchanges.crypto_com import CryptoConfig
from mappers.exchanges.polymarket import (
    PolymarketConfig,
    mlb_extra_innings_rule,
    mlb_f5_spread_rule,
    mlb_f5_tied_rule,
    mlb_f5_total_rule,
    mlb_f5_winner_rule,
    mlb_first_inning_rule,
    mlb_home_runs_rule,
    mlb_moneyline_rule,
    mlb_spread_rule,
    mlb_strikeouts_rule,
    mlb_total_rule,
)
from mappers.exchanges.px import PxConfig
from mappers.market_types import MarketType

BASEBALL_OPTIC_TABLE_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "run_line": MarketType.POINT_SPREAD,
    "total_runs": MarketType.GAME_TOTAL,
    "1st_inning_total_runs": MarketType.FIRST_INNING_TOTAL,
    "player_home_runs": MarketType.PLAYER_HOME_RUNS,
    "player_strikeouts": MarketType.PLAYER_STRIKEOUTS,
    "team_total": MarketType.TEAM_TOTAL,
    "player_hits": MarketType.PLAYER_HITS,
    "player_bases": MarketType.PLAYER_BASES,
    "player_hits_+_runs_+_rbis": MarketType.PLAYER_HITS_RUNS_RBIS,
    "player_rbis": MarketType.PLAYER_RBIS,
    "player_stolen_bases": MarketType.PLAYER_STOLEN_BASES,
    "player_outs": MarketType.PLAYER_OUTS,
    "1st_half_moneyline_3-way": MarketType.FIRST_FIVE_MONEYLINE_3WAY,
    "1st_3_innings_moneyline_3-way": MarketType.FIRST_THREE_MONEYLINE_3WAY,
    "1st_7_innings_moneyline_3-way": MarketType.FIRST_SEVEN_MONEYLINE_3WAY,
    "1st_half_run_line": MarketType.FIRST_FIVE_POINT_SPREAD,
    "1st_half_total_runs": MarketType.FIRST_FIVE_TOTAL,
    "will_there_be_extra_innings": MarketType.EXTRA_INNINGS,
    "player_hits_allowed": MarketType.PLAYER_HITS_ALLOWED,
    "player_earned_runs": MarketType.PLAYER_EARNED_RUNS,
    "player_walks": MarketType.PLAYER_WALKS_ALLOWED,
    "player_runs": MarketType.PLAYER_RUNS,
    "player_batting_strikeouts": MarketType.PLAYER_BATTING_STRIKEOUTS,
    "player_batting_walks": MarketType.PLAYER_BATTING_WALKS,
    "1st_inning_moneyline_3-way": MarketType.INNING_1_WINNER_3WAY,
    "2nd_inning_moneyline_3-way": MarketType.INNING_2_WINNER_3WAY,
    "3rd_inning_moneyline_3-way": MarketType.INNING_3_WINNER_3WAY,
    "4th_inning_moneyline_3-way": MarketType.INNING_4_WINNER_3WAY,
    "5th_inning_moneyline_3-way": MarketType.INNING_5_WINNER_3WAY,
    "6th_inning_moneyline_3-way": MarketType.INNING_6_WINNER_3WAY,
    "7th_inning_moneyline_3-way": MarketType.INNING_7_WINNER_3WAY,
    "8th_inning_moneyline_3-way": MarketType.INNING_8_WINNER_3WAY,
    "2nd_inning_total_runs": MarketType.INNING_2_TOTAL,
    "3rd_inning_total_runs": MarketType.INNING_3_TOTAL,
    "4th_inning_total_runs": MarketType.INNING_4_TOTAL,
    "5th_inning_total_runs": MarketType.INNING_5_TOTAL,
    "6th_inning_total_runs": MarketType.INNING_6_TOTAL,
    "7th_inning_total_runs": MarketType.INNING_7_TOTAL,
    "8th_inning_total_runs": MarketType.INNING_8_TOTAL,
    "9th_inning_total_runs": MarketType.INNING_9_TOTAL,
}

BASEBALL_MARKET_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "total": MarketType.GAME_TOTAL,
    "spread": MarketType.POINT_SPREAD,
    "first_inning": MarketType.FIRST_INNING_TOTAL,
    "home_runs": MarketType.PLAYER_HOME_RUNS,
    "strikeouts": MarketType.PLAYER_STRIKEOUTS,
    "extra_innings": MarketType.EXTRA_INNINGS,
    "f5_total": MarketType.FIRST_FIVE_TOTAL,
    "f5_spread": MarketType.FIRST_FIVE_POINT_SPREAD,
    "f5_moneyline_3way": MarketType.FIRST_FIVE_MONEYLINE_3WAY,
}

baseball_market_rules = (
    mlb_f5_total_rule,
    mlb_f5_spread_rule,
    mlb_f5_winner_rule,
    mlb_f5_tied_rule,
    mlb_total_rule,
    mlb_first_inning_rule,
    mlb_extra_innings_rule,
    mlb_spread_rule,
    mlb_home_runs_rule,
    mlb_strikeouts_rule,
    mlb_moneyline_rule,
)

MLB_PX = PxConfig(
    tournament_id=109,
    exact={
        "Moneyline": MarketType.MONEYLINE,
        "Run Line": MarketType.POINT_SPREAD,
        "Total Runs": MarketType.GAME_TOTAL,
    },
    suffix=[],
)


_CRYPTO_PROP_CONTRACT_TYPES: dict[str, MarketType] = {
    "Total Pitching Strikeouts": MarketType.PLAYER_STRIKEOUTS,
    "Total Pitching Strikeouts Milestones": MarketType.PLAYER_STRIKEOUTS,
    "Total Outs Recorded": MarketType.PLAYER_OUTS,
    "Total Bases": MarketType.PLAYER_BASES,
    "Total Bases Milestones": MarketType.PLAYER_BASES,
    "To Get A Hit": MarketType.PLAYER_HITS,
    "Total Hits": MarketType.PLAYER_HITS,
    "Total Hits Milestones": MarketType.PLAYER_HITS,
    "Total Hits, Runs, & RBIs": MarketType.PLAYER_HITS_RUNS_RBIS,
    "To Hit A Home Run": MarketType.PLAYER_HOME_RUNS,
    "Total Home Runs Milestones": MarketType.PLAYER_HOME_RUNS,
}


def baseball_crypto_config(
    league: str,
    settings: Mapping[str, Any],
) -> CryptoConfig | None:
    """Build crypto.com config for MLB grouping from tip settings."""
    grouping = str(settings.get("sport_grouping") or "").strip()
    if not league or not grouping:
        return None
    period = str(settings.get("period_type") or "Full-Game")
    return CryptoConfig(
        sport_grouping=grouping,
        league=league,
        period_type=period,
        contract_types={
            "Moneyline": MarketType.MONEYLINE,
            "Spread": MarketType.POINT_SPREAD,
            "Total Runs": MarketType.GAME_TOTAL,
        },
        period_contract_types={
            "1st-5th Inning": {
                "Moneyline": MarketType.FIRST_FIVE_MONEYLINE_3WAY,
                "Moneyline (3-Way)": MarketType.FIRST_FIVE_MONEYLINE_3WAY,
                "Spread": MarketType.FIRST_FIVE_POINT_SPREAD,
                "Total Runs": MarketType.FIRST_FIVE_TOTAL,
            },
            # F3 catalogue also lists Spread / Total Runs; Optic has no
            # 1st_3_innings run-line or total, so those stay unwired
            # (load drops crypto-only rows).
            "1st-3rd Inning": {
                "Moneyline (3-Way)": MarketType.FIRST_THREE_MONEYLINE_3WAY,
            },
        },
        prop_period_type="Full-Game",
        prop_contract_types=_CRYPTO_PROP_CONTRACT_TYPES,
        game_prop_period_type="1st Inning",
        game_prop_contract_types={
            "To Score A Run": MarketType.FIRST_INNING_TOTAL,
        },
    )


MLB_CRYPTO = cast(
    CryptoConfig,
    baseball_crypto_config("MLB", {"sport_grouping": "MLB", "period_type": "Full-Game"}),
)

MLB_POLYMARKET = PolymarketConfig(
    slug_prefix="mlb",
    optic_league_id="mlb",
    market_types=BASEBALL_MARKET_TYPES,
    market_rules=baseball_market_rules,
)
