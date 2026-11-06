"""Shared tennis Optic + Polymarket taxonomy."""

from __future__ import annotations

import re

from mappers.exchanges.polymarket import (
    _Q_MONEYLINE,
    MarketRule,
    ParsedMarket,
    PolymarketConfig,
    SideMode,
    _norm_name,
)
from mappers.market_types import MarketType


def tennis_moneyline_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Tennis match-winner: "<Tournament>: <A> vs <B>" -> TEAM_LABEL.

    Players are taken after the LAST colon. Doubles (slash-joined names),
    completed/settled matches, and totals/sets markets return None (dropped).
    """
    q = (question or "").strip()
    if "/" in q or re.search(r"(?i)\bcompleted\b", q):
        return None
    if re.search(r"(?i)o/u|total|\bsets?\b|games", q):
        return None
    players = q.rsplit(":", 1)[-1].strip() if ":" in q else q
    m = _Q_MONEYLINE.match(players)
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


# Tennis total sets: "<A> vs. <B>: Total Sets O/U <N>" (probe:
# .superpowers/sdd/wave-tennis-probe-findings.md section B.3, byte-exact).
# Unlike tennis_moneyline_rule, there is NO tournament prefix here -- the
# fixture names come first, exactly like MLB/soccer's own total forms -- and
# both names are FULL names (not the surname-only forms scoped out of this
# task). Line is always 2.5 on tour-level best-of-3 tennis, but parsed
# generically like every other total rule.
_Q_TENNIS_TOTAL_SETS = re.compile(
    r"^(.+?)\s+vs\.?\s+(.+?):\s*total sets\s+o/u\s*([\d.]+)\s*$", re.I
)


def tennis_total_sets_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Tennis total sets: "<A> vs. <B>: Total Sets O/U N" -> OVER_UNDER (GAME).

    Mirrors soccer_total_rule's structure (no team-total/half variant to guard
    against here -- tennis has no such form). The outcome_label bakes the line
    in ("Over 2.5"/"Under 2.5", not bare "Over"/"Under"); that's handled by the
    build_rows OVER_UNDER branch's startswith fix (GOTCHA-1), not here.
    """
    q = (question or "").strip()
    m = _Q_TENNIS_TOTAL_SETS.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("total_sets")
    if mt is None:
        return None
    try:
        line = float(m.group(3))
    except ValueError:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group(1), style),
        team_b=_norm_name(m.group(2), style),
        side_mode=SideMode.OVER_UNDER,
        line=line,
    )


# === Tier 2 (task TN3): the 4 SURNAME-only forms ===
# wave-tennis-probe-findings.md sections B.2/B.4/B.5/B.6 (byte-exact templates)
# + section C (mapping matrix). Unlike moneyline/total_sets, poly's names here
# are the LAST WHITESPACE TOKEN of the full name ("Luca Van Assche" ->
# "Assche"), so every ParsedMarket below sets name_granularity="surname" --
# consumed by build_rows' TEAM_LABEL/SPREAD_TEAM branches and by
# pipeline._match_poly_fixture (task TN2's mechanism; unchanged here).

# Match total games: "<A> vs. <B>: Match O/U <N>" -- NO tournament prefix,
# anchored on the literal "Match O/U" (not just "O/U") so it can never collide
# with tennis_total_sets_rule's "Total Sets O/U" or tennis_set_games_rule's
# "Set K Games O/U" -- all three contain the substring "O/U" but differ on the
# word immediately preceding it.
_Q_TENNIS_MATCH_TOTAL_GAMES = re.compile(
    r"^(.+?)\s+vs\.?\s+(.+?):\s*match o/u\s*([\d.]+)\s*$", re.I
)

# Set games: "<A> vs. <B>: Set <K> Games O/U <N>", K in {1,2,3,4}. K in {3,4}
# is the best-of-5 tail (Grand-Slam-only, low volume, Optic ceiling
# unconfirmed live -- section C's best-of-3-vs-5 quirk) and is deferred, not
# built: the rule returns None for it.
_Q_TENNIS_SET_GAMES = re.compile(
    r"^(.+?)\s+vs\.?\s+(.+?):\s*set (\d+) games o/u\s*([\d.]+)\s*$", re.I
)

# Set handicap: "Set Handicap: <A> (-N) vs <B> (+N)" -- a FIXED LITERAL
# PREFIX (not a tournament name), unlike every "A vs B: ..." suffix form
# above. Only the first (named, negative-signed in every live sample) team +
# its own signed line is captured -- mirrors mlb_spread_rule's one-team
# convention; team_a/team_b stay None so the pipeline resolves the fixture
# from the two outcome labels (both surnames per B.5), same as mlb_spread_rule.
_Q_TENNIS_SET_HANDICAP = re.compile(
    r"^set handicap:\s*(?P<team>.+?)\s*\(\s*(?P<line>[+-]?[\d.]+)\s*\)\s*"
    r"vs\.?\s*.+?\s*\(\s*[+-]?[\d.]+\s*\)\s*$",
    re.I,
)

# Set winner: "Set <K> Winner: <A> vs <B>", K in {1,2,3,4}. K in {3,4} is the
# same best-of-5 tail deferred above. Fixed literal prefix, strictly 2-way (no
# Draw -- section A confirms 1st/2nd_set_moneyline never lists one).
_Q_TENNIS_SET_WINNER = re.compile(
    r"^set (\d+) winner:\s*(.+?)\s+vs\.?\s+(.+?)\s*$", re.I
)


def tennis_match_total_games_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Tennis match total games: "<A> vs. <B>: Match O/U N" -> OVER_UNDER (GAME).

    Surname-only names (section B.2) -> name_granularity="surname".
    """
    q = (question or "").strip()
    m = _Q_TENNIS_MATCH_TOTAL_GAMES.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("match_total_games")
    if mt is None:
        return None
    try:
        line = float(m.group(3))
    except ValueError:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group(1), style),
        team_b=_norm_name(m.group(2), style),
        side_mode=SideMode.OVER_UNDER,
        line=line,
        name_granularity="surname",
    )


def tennis_set_games_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Tennis set games: "<A> vs. <B>: Set K Games O/U N" -> OVER_UNDER (GAME).

    K=1 -> FIRST_SET_TOTAL_GAMES, K=2 -> SECOND_SET_TOTAL_GAMES; K in {3,4}
    (best-of-5 tail) returns None -- deferred per section C. Surname-only
    names, same convention as tennis_match_total_games_rule.
    """
    q = (question or "").strip()
    m = _Q_TENNIS_SET_GAMES.match(q)
    if not m:
        return None
    set_num = m.group(3)
    if set_num == "1":
        kind = "1st_set_total_games"
    elif set_num == "2":
        kind = "2nd_set_total_games"
    else:
        return None  # 3rd/4th-set best-of-5 tail -- deferred, not built
    mt = cfg.market_types.get(kind)
    if mt is None:
        return None
    try:
        line = float(m.group(4))
    except ValueError:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group(1), style),
        team_b=_norm_name(m.group(2), style),
        side_mode=SideMode.OVER_UNDER,
        line=line,
        name_granularity="surname",
    )


def tennis_set_handicap_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Tennis set handicap: "Set Handicap: A (-N) vs B (+N)" -> SPREAD_TEAM (GAME).

    Mirrors mlb_spread_rule: the question names ONE team + its signed line
    (put in entity, sign preserved as written -- always negative in live
    samples, but parsed generically); both outcome labels are the two
    surnames, so the pipeline resolves the fixture from those labels (same as
    mlb_spread_rule). Surname-only -> name_granularity="surname".
    """
    q = (question or "").strip()
    m = _Q_TENNIS_SET_HANDICAP.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("set_handicap")
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
        name_granularity="surname",
    )


def tennis_set_winner_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Tennis set winner: "Set K Winner: A vs B" -> TEAM_LABEL (GAME), 2-way.

    K=1 -> FIRST_SET_WINNER, K=2 -> SECOND_SET_WINNER; K in {3,4} (best-of-5
    tail) returns None -- deferred, same as tennis_set_games_rule. Strictly
    2-way (no Draw, section A). Surname-only names.
    """
    q = (question or "").strip()
    m = _Q_TENNIS_SET_WINNER.match(q)
    if not m:
        return None
    set_num = m.group(1)
    if set_num == "1":
        kind = "1st_set_winner"
    elif set_num == "2":
        kind = "2nd_set_winner"
    else:
        return None  # 3rd/4th-set best-of-5 tail -- deferred, not built
    mt = cfg.market_types.get(kind)
    if mt is None:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group(2), style),
        team_b=_norm_name(m.group(3), style),
        side_mode=SideMode.TEAM_LABEL,
        name_granularity="surname",
    )


# Shared `market_types` dict for every tennis league's PolymarketConfig (ATP/WTA
# wire this in verbatim). Tier 1 of the tennis rescue (wave-tennis-probe-findings.md)
# adds "total_sets" alongside the already-shipped "moneyline"; Tier 2 (task TN3)
# adds the 4 surname-only forms.
TENNIS_MARKET_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "total_sets": MarketType.TOTAL_SETS,
    "match_total_games": MarketType.MATCH_TOTAL_GAMES,
    "1st_set_total_games": MarketType.FIRST_SET_TOTAL_GAMES,
    "2nd_set_total_games": MarketType.SECOND_SET_TOTAL_GAMES,
    "set_handicap": MarketType.SET_HANDICAP,
    "1st_set_winner": MarketType.FIRST_SET_WINNER,
    "2nd_set_winner": MarketType.SECOND_SET_WINNER,
}


# Ordered tennis recognizer tuple (ATP/WTA wire this into their
# PolymarketConfig.market_rules). tennis_total_sets_rule is ordered first
# defensively -- tennis_moneyline_rule already self-guards against totals/sets
# questions via its own regex (see its docstring), so ordering isn't
# correctness-critical, but specific-before-general mirrors every other
# league's convention here. The 4 Tier 2 rules are anchored on mutually
# exclusive literals ("Match O/U", "Set K Games O/U", "Set Handicap:",
# "Set K Winner:") so none mis-fires on another's questions; the two
# fixed-prefix forms (set_handicap/set_winner) are ordered before the two
# "A vs B: ..." suffix forms (match_total_games/set_games), and all four sit
# before the bare-"A vs B" moneyline catch-all.
tennis_market_rules: tuple[MarketRule, ...] = (
    tennis_total_sets_rule,
    tennis_set_handicap_rule,
    tennis_set_winner_rule,
    tennis_match_total_games_rule,
    tennis_set_games_rule,
    tennis_moneyline_rule,
)

TENNIS_OPTIC_TABLE_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
    "total_sets": MarketType.TOTAL_SETS,
    "total_games": MarketType.MATCH_TOTAL_GAMES,
    # The GAMES handicap -- tennis's POINT_SPREAD, the same contract Kalshi
    # posts as GSPREAD and Novig as SPREAD. Absent here until now, so no
    # Optic row for it ever existed: every tennis point_spread row was
    # Kalshi-only with `optic_odds: null`, and load_mappings drops any record
    # with no Optic block (198 stamped Novig game-handicap outcomes went
    # nowhere on 2026-08-26). Optic prices it heavily -- 2,087 odds that day
    # -- and its own source_ids already carry Novig/SX/Polymarket (USA), so
    # those book on the passthrough path as soon as the row exists.
    "game_spread": MarketType.POINT_SPREAD,
    # Games won by ONE named player; Optic ships player_id on it, and Novig's
    # PLAYER_GAMES_WON carries player.opticOddsId, so the entity is the usual
    # id join. Optic's source_ids are empty here, so this row only exists
    # because the Novig matcher builds it. The set-scoped siblings
    # (1st_set_game_spread, 1st_set_player_games_won) settle differently and
    # stay unmapped.
    "player_games_won": MarketType.PLAYER_GAMES_WON,
    "1st_set_total_games": MarketType.FIRST_SET_TOTAL_GAMES,
    "2nd_set_total_games": MarketType.SECOND_SET_TOTAL_GAMES,
    "set_handicap": MarketType.SET_HANDICAP,
    "1st_set_moneyline": MarketType.FIRST_SET_WINNER,
    "2nd_set_moneyline": MarketType.SECOND_SET_WINNER,
    # Sets scoreline, winner-anchored ("2:1" on the winner's team_id); the
    # same CORRECT_SCORE row shape as soccer, never a draw.
    "correct_score": MarketType.CORRECT_SCORE,
}
