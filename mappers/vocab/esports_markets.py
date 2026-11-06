"""Shared esports Optic taxonomy and Polymarket question grammar."""

from __future__ import annotations

import re

from mappers.exchanges.polymarket import (
    MarketRule,
    ParsedMarket,
    PolymarketConfig,
    SideMode,
    _norm_name,
)
from mappers.handicap_name_crumb import is_esports_map_winner
from mappers.market_types import MarketType
from mappers.vocab.esports_question import _Q_ESPORTS_MONEYLINE

ESPORTS_OPTIC_TABLE_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "map_handicap": MarketType.MAP_HANDICAP,
    "total_maps": MarketType.TOTAL_MAPS,
    "1st_map_moneyline": MarketType.MAP_1_WINNER,
    "2nd_map_moneyline": MarketType.MAP_2_WINNER,
    "3rd_map_moneyline": MarketType.MAP_3_WINNER,
    "4th_map_moneyline": MarketType.MAP_4_WINNER,
    "5th_map_moneyline": MarketType.MAP_5_WINNER,
    **{f"{o}_map_round_handicap": MarketType[f"MAP_{n}_ROUND_HANDICAP"]
       for n, o in enumerate(("1st", "2nd", "3rd"), 1)},
    **{f"{o}_map_total_rounds": MarketType[f"MAP_{n}_TOTAL_ROUNDS"]
       for n, o in enumerate(("1st", "2nd", "3rd"), 1)},
    **{f"{o}_map_team_first_blood": MarketType[f"MAP_{n}_FIRST_BLOOD"]
       for n, o in enumerate(("1st", "2nd", "3rd", "4th", "5th"), 1)},
    **{f"{o}_map_total_kills_odd_even": MarketType[f"MAP_{n}_KILLS_ODD"]
       for n, o in enumerate(("1st", "2nd", "3rd", "4th", "5th"), 1)},
}

# Title grammar lives in esports_question.py so gap harvest can parse the same
# series moneyline (and skip map winners) without importing this matcher.


def esports_moneyline_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Esports series winner: "<Game>: <A> vs <B> (BO3) - <Event>" -> TEAM_LABEL.

    Reuses MarketType.MONEYLINE verbatim (2-way, no draw — an esports series
    always has a winner), exactly as UFC and tennis reuse it. Both teams are
    named, so this resolves in Phase A like every other sport's moneyline; no
    pipeline changes are needed for this form.

    Per-map winners are rejected outright — see is_esports_map_winner.
    """
    q = (question or "").strip()
    if is_esports_map_winner(q):
        return None
    m = _Q_ESPORTS_MONEYLINE.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("moneyline")
    if mt is None:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group(1), style),
        team_b=_norm_name(m.group(2), style),
        side_mode=SideMode.TEAM_LABEL,
    )


# Retained name — leagues/lol.py and its tests referenced this before CS2 and
# Dota 2 joined; the rule is game-agnostic now, not LoL-specific.
lol_moneyline_rule = esports_moneyline_rule


# Series map handicap: "Map Handicap: <A> (-1.5) vs <B> (+1.5)" (CS2) or
# "Game Handicap: <A> (-1.5) vs <B> (+1.5)" (LoL/Dota 2) — the same optic
# market_id (`map_handicap`) under two poly titles, so one regex takes both.
#
# WHICH team is captured is the whole subtlety here. Like tennis's structurally
# identical "Set Handicap: A (-N) vs B (+N)", only ONE team goes in `entity`
# (build_rows binds that team's signed line and negates the other), and the
# fixture itself is resolved from the two outcome LABELS, not from this regex.
# But unlike tennis, the esports questions ABBREVIATE the first team while the
# outcome labels carry full names — across every one of 23 live samples
# (2026-08-11) the pattern is invariant:
#
#   "Map Handicap: GZ (-1.5) vs Abyssal (+1.5)"   labels: Ground Zero | Abyssal
#   "Game Handicap: FEC (-1.5) vs mCon esports (+1.5)"
#                                        labels: Frites Esports Club | mCon esports
#   "Game Handicap: TS.A (-1.5) vs No Hoodwink (+1.5)"
#                                        labels: Spirit Academy | No Hoodwink
#
# — first name abbreviated ("GZ", "FEC", "TS.A", "Na`Vi", "paiN.A"), second
# name spelled out and matching its outcome label. So this captures the SECOND
# pair, not the first: an abbreviation would fail _match_name against both
# fixture sides and build_rows would drop the market whole.
#
# Sign safety does NOT depend on that ordering claim, only match RATE does: the
# captured team and the captured line come from the SAME parenthetical, so
# whichever side we bind, its line is the one written next to it. If Polymarket
# ever flips which side it abbreviates, the worst case is `entity` failing to
# match and the market dropping (build_rows' `return []`) — never a flipped
# handicap.
_Q_ESPORTS_MAP_HANDICAP = re.compile(
    r"^(?:map|game) handicap:\s*.+?\s*\(\s*[+-]?[\d.]+\s*\)\s*"
    r"vs\.?\s*(?P<team>.+?)\s*\(\s*(?P<line>[+-]?[\d.]+)\s*\)\s*$",
    re.I,
)

# Series total maps: "Games Total: O/U 2.5" (LoL/Dota 2) / "Maps Total: O/U 2.5"
# (CS2). Names ZERO competitors — the exact shape UFC's "O/U N Rounds" already
# has, so it defers to the pipeline's Phase B slug-key lookup (seeded by this
# same fixture's moneyline market, which names both teams and resolves in
# Phase A). Anchored on end-of-string after the number so it cannot swallow the
# per-map round totals ("Map 1 Total Rounds: Over/Under 21.5"), which Optic
# prices no market for and which must keep falling through unrecognized.
_Q_ESPORTS_TOTAL_MAPS = re.compile(
    r"^(?:games|maps) total:\s*o/u\s*([\d.]+)\s*$", re.I
)


def esports_map_handicap_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Esports map handicap: "Map/Game Handicap: A (-N) vs B (+N)" -> SPREAD_TEAM.

    Mirrors tennis_set_handicap_rule (same question shape, same SideMode); see
    _Q_ESPORTS_MAP_HANDICAP on why the SECOND team+line pair is the one bound.
    """
    q = (question or "").strip()
    m = _Q_ESPORTS_MAP_HANDICAP.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("map_handicap")
    if mt is None:
        return None
    try:
        line = float(m.group("line"))
    except ValueError:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=None,
        team_b=None,
        side_mode=SideMode.SPREAD_TEAM,
        entity=_norm_name(m.group("team"), style),
        line=line,
    )


def esports_total_maps_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Esports series map total: "Games/Maps Total: O/U N" -> OVER_UNDER (GAME).

    Zero competitors named, so team_a/team_b stay None and the pipeline resolves
    the fixture in Phase B off the slug's team tokens — identical treatment to
    UFC's ufc_total_rounds_rule.
    """
    q = (question or "").strip()
    m = _Q_ESPORTS_TOTAL_MAPS.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("total_maps")
    if mt is None:
        return None
    try:
        line = float(m.group(1))
    except ValueError:
        return None
    return ParsedMarket(
        market_type=mt,
        team_a=None,
        team_b=None,
        side_mode=SideMode.OVER_UNDER,
        line=line,
    )


# The three markets Optic prices for esports, verified live 2026-08-11 over 48h
# of opticodds_prices for league_id in (league_of_legends, cs2, dota_2): exactly
# `moneyline`, `total_maps` and `map_handicap`, and the SAME three for all three
# games. This supersedes the 2026-07-28 census that found moneyline alone.
#
# Per-map winners: Optic added Nth_map_moneyline (seen on cs2 / dota_2 /
# league_of_legends 2026-09-26); no Polymarket question rule maps them yet.
# Per-map round totals/handicaps stay absent (no Optic market).
ESPORTS_MARKET_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "map_handicap": MarketType.MAP_HANDICAP,
    "total_maps": MarketType.TOTAL_MAPS,
}

# Retained name — see lol_moneyline_rule above.
LOL_MARKET_TYPES = ESPORTS_MARKET_TYPES


# Most-specific-first: both handicap and total anchor on a fixed literal prefix
# ("map/game handicap:", "games/maps total:") that no moneyline question can
# carry, and the moneyline anchors on a leading game name that neither of them
# carries — so the ordering is defensive, not load-bearing.
esports_market_rules: tuple[MarketRule, ...] = (
    esports_map_handicap_rule,
    esports_total_maps_rule,
    esports_moneyline_rule,
)

# Retained name — see lol_moneyline_rule above.
lol_market_rules = esports_market_rules
