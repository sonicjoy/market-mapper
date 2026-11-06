"""Shared combat Optic + Polymarket taxonomy for MMA and boxing.

The Polymarket recognizers live here rather than in
``mappers/exchanges/polymarket.py``: that module is the bridge engine
(question parsing, name matching, row building) and stays sport-agnostic,
while every sport owns its own question grammar.
"""

import re

from mappers.exchanges.polymarket import (
    MarketRule,
    ParsedMarket,
    PolymarketConfig,
    SideMode,
    _norm_name,
)
from mappers.market_types import MarketType

# Optic method_of_victory / method_of_ending are parsed only as the
# pricing counterpart for Kalshi MOV / MOF.  Draw and non-whitelist
# Optic buckets are skipped (Kalshi draw_or_nc ≠ Optic Draw).  crypto.com
# MoV/MoF stay unmapped (bucket labels unverified vs Kalshi).
UFC_OPTIC_TABLE_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "method_of_victory": MarketType.METHOD_OF_VICTORY,
    "method_of_ending": MarketType.METHOD_OF_FINISH,
    "round_betting": MarketType.ROUND_BETTING,
    "total_rounds": MarketType.TOTAL_ROUNDS,
    "team_to_win_by_knockout_submission_dq": MarketType.WIN_BY_KO_SUB_DQ,
    "fight_to_go_the_distance": MarketType.FIGHT_GOES_DISTANCE,
    "go_the_distance": MarketType.FIGHT_GOES_DISTANCE,
    "win_by_ko_tko": MarketType.GAME_WIN_BY_KOTKO,
    "to_start_round_2": MarketType.TO_START_ROUND_2,
    "to_start_round_3": MarketType.TO_START_ROUND_3,
    "to_start_round_4": MarketType.TO_START_ROUND_4,
    "to_start_round_5": MarketType.TO_START_ROUND_5,
}

BOXING_OPTIC_TABLE_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
}

UFC_POLY_TEAM_NAME_ALIASES: dict[str, str] = {
    _norm_name("Magomed Zaynukov", "tennis_prefix"): _norm_name(
        "Magomed Zayunokov", "tennis_prefix"
    ),
    _norm_name("Seokhyeon Ko", "tennis_prefix"): _norm_name(
        "Seok Hyun Ko", "tennis_prefix"
    ),
}

_Q_UFC_MONEYLINE = re.compile(r"^UFC.*?:\s*(.+?)\s+vs\.?\s+(.+?)\s*\(", re.I)


def ufc_moneyline_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """UFC fighter moneyline: "UFC <Event>: <A> vs. <B> (<Weightclass>, <Card>)"
    -> TEAM_LABEL (GAME), reusing MarketType.MONEYLINE verbatim (no new
    constant -- exact same (Scope.GAME, Shape.MONEYLINE) tennis's moneyline
    reuses). Both fighters are named, so this resolves in Phase A exactly
    like every other sport's moneyline -- no pipeline changes needed for this
    form. The trailing "(Weightclass, Card)" parenthetical (unseen in tennis)
    is stripped by anchoring group 2 on the literal "(" rather than
    end-of-string.
    """
    q = (question or "").strip()
    m = _Q_UFC_MONEYLINE.match(q)
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


_Q_UFC_TOTAL_ROUNDS = re.compile(r"^O/U\s*([\d.]+)\s*Rounds\s*$", re.I)


def ufc_total_rounds_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """UFC total rounds: "O/U N Rounds" -> OVER_UNDER (GAME), exact analog of
    tennis_total_sets_rule. NO fighter is named in the question (team_a/
    team_b stay None) -- pipeline._resolve_poly_markets defers this to Phase B,
    resolving via the slug-team-token key seeded by the same fight's
    ufc_moneyline_rule market (see that function's Phase-A note).
    """
    q = (question or "").strip()
    m = _Q_UFC_TOTAL_ROUNDS.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("total_rounds")
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


def ufc_go_the_distance_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """UFC "Fight to Go the Distance?" (literal, no fighter names) -> YESNO
    (GAME), same shape as soccer's BTTS. Deferred to Phase B like
    ufc_total_rounds_rule (zero competitors named).
    """
    q = (question or "").strip()
    if q != "Fight to Go the Distance?":
        return None
    mt = cfg.market_types.get("go_the_distance")
    if mt is None:
        return None
    return ParsedMarket(
        market_type=mt,
        team_a=None,
        team_b=None,
        side_mode=SideMode.YESNO,
    )


def ufc_game_win_by_kotko_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """UFC "Will the fight be won by KO or TKO?" (literal, GAME-scoped, no
    fighter names) -> YESNO (GAME) -> optic's win_by_ko_tko. Distinct from the
    per-fighter "Will <Fighter> win by KO or TKO?" question (FIGHTER_WIN_BY_
    KOTKO), which this rule must NOT match -- anchored on the exact literal
    game-level phrasing (no fighter-name group at all), so the fighter-scoped
    question (which always contains a name before "win by") never matches
    here. Deferred to Phase B like the two rules above.
    """
    q = (question or "").strip()
    if q != "Will the fight be won by KO or TKO?":
        return None
    mt = cfg.market_types.get("game_win_by_kotko")
    if mt is None:
        return None
    return ParsedMarket(
        market_type=mt,
        team_a=None,
        team_b=None,
        side_mode=SideMode.YESNO,
    )


# Shared market_types dict for UFC's PolymarketConfig.
UFC_MARKET_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "total_rounds": MarketType.TOTAL_ROUNDS,
    "go_the_distance": MarketType.FIGHT_GOES_DISTANCE,
    "game_win_by_kotko": MarketType.GAME_WIN_BY_KOTKO,
    # Path 2 US ticker keys (no official-Poly question rules).
    "method_of_victory": MarketType.METHOD_OF_VICTORY,
    "method_of_finish": MarketType.METHOD_OF_FINISH,
}


# Ordered UFC recognizer tuple (the combat parser profile wires this into
# its PolymarketConfig.market_rules). The two literal Yes/No forms and the
# anchored O/U-Rounds form are ordered before the moneyline catch-all
# defensively (mirrors the tennis convention of specific-before-general),
# though none of the four can actually mis-fire on another's questions --
# each is anchored on a mutually exclusive literal/prefix ("O/U ... Rounds",
# the two exact Yes/No question strings, "UFC ...: A vs. B (").
ufc_market_rules: tuple[MarketRule, ...] = (
    ufc_total_rounds_rule,
    ufc_go_the_distance_rule,
    ufc_game_win_by_kotko_rule,
    ufc_moneyline_rule,
)

__all__ = [
    "BOXING_OPTIC_TABLE_TYPES",
    "UFC_MARKET_TYPES",
    "UFC_OPTIC_TABLE_TYPES",
    "UFC_POLY_TEAM_NAME_ALIASES",
    "ufc_game_win_by_kotko_rule",
    "ufc_go_the_distance_rule",
    "ufc_market_rules",
    "ufc_moneyline_rule",
    "ufc_total_rounds_rule",
]
