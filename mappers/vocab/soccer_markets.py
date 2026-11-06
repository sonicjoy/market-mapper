"""Shared soccer Optic taxonomy and Polymarket question grammar."""

from __future__ import annotations

import re

from mappers.exchanges.polymarket import (
    MarketRule,
    ParsedMarket,
    PolymarketConfig,
    SideMode,
    _active_team_aliases,
    _norm_name,
    _player_prop_rule,
)
from mappers.market_types import MarketType
from mappers.shared import normalize_player_name
from mappers.vocab.soccer_question import _Q_SOCCER_ML_DRAW

# Every market Optic prices for soccer that we map, for EVERY soccer league.
SOCCER_OPTIC_TABLE_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE_3WAY,
    "double_chance": MarketType.DOUBLE_CHANCE,
    "asian_handicap": MarketType.POINT_SPREAD,
    "total_goals": MarketType.GAME_TOTAL,
    "team_total": MarketType.TEAM_TOTAL,
    "both_teams_to_score": MarketType.BTTS,
    "correct_score": MarketType.CORRECT_SCORE,
    "1st_half_correct_score": MarketType.FIRST_HALF_CORRECT_SCORE,
    "first_team_to_score": MarketType.FIRST_TEAM_TO_SCORE,
    "1st_half_moneyline": MarketType.FIRST_HALF_WINNER_3WAY,
    "1st_half_double_chance": MarketType.FIRST_HALF_DOUBLE_CHANCE,
    "1st_half_asian_handicap": MarketType.FIRST_HALF_POINT_SPREAD,
    "1st_half_total_goals": MarketType.FIRST_HALF_TOTAL,
    "1st_half_team_total": MarketType.FIRST_HALF_TEAM_TOTAL,
    "1st_half_both_teams_to_score": MarketType.FIRST_HALF_BTTS,
    "2nd_half_moneyline": MarketType.SECOND_HALF_WINNER_3WAY,
    "2nd_half_total_goals": MarketType.SECOND_HALF_TOTAL,
    "2nd_half_team_total": MarketType.SECOND_HALF_TEAM_TOTAL,
    "total_corners": MarketType.TOTAL_CORNERS,
    "team_total_corners": MarketType.TEAM_TOTAL_CORNERS,
    "player_goals": MarketType.PLAYER_GOALS,
    "player_assists": MarketType.PLAYER_ASSISTS,
    "player_shots": MarketType.PLAYER_SHOTS,
    "player_shots_on_target": MarketType.PLAYER_SHOTS_ON_TARGET,
    "player_goals_+_assists": MarketType.PLAYER_GOALS_OR_ASSIST,
    "player_saves": MarketType.PLAYER_SAVES,
    "first_goal_scorer": MarketType.FIRST_GOAL_SCORER,
    "2nd_half_asian_handicap": MarketType.SECOND_HALF_POINT_SPREAD,
    "2nd_half_both_teams_to_score": MarketType.SECOND_HALF_BTTS,
    "1st_half_first_team_to_score": MarketType.FIRST_HALF_FIRST_TEAM_TO_SCORE,
    "2nd_half_first_team_to_score": MarketType.SECOND_HALF_FIRST_TEAM_TO_SCORE,
}

SOCCER_OPTIC_CUP_TABLE_TYPES: dict[str, MarketType] = {
    **SOCCER_OPTIC_TABLE_TYPES,
    "to_advance": MarketType.TO_ADVANCE,
}

# Soccer question forms (probe: .superpowers/sdd/wave-4-probe-findings.md
# section C, byte-exact against live mls/mex/ucl bridge rows). These are
# "reuse-mode" forms: same SideModes MLB already exercises (OVER_UNDER,
# SPREAD_TEAM), just a different sport's question templates.

# Full-game total: "<A> vs. <B>: O/U <N>". Anchored exactly like MLB's
# _Q_TOTAL: the colon must be followed only by whitespace then "o/u", so
# backtracking team_b never lands on a split that also swallows the
# team-total form ("<A> vs. <B>: <Team> O/U <N>") or either half form
# ("...: 1st/2nd Half O/U <N>") -- there's only one ":" in these questions
# and it's never immediately followed by "o/u" in those other forms.
_Q_SOCCER_TOTAL = re.compile(r"^(.+?)\s+vs\.?\s+(.+?):\s*o/u\s*([\d.]+)\s*$", re.I)

# Team total: "<A> vs. <B>: <Team> O/U <N>". Unlike the full-total form
# above, this shape's non-greedy `team` group WOULD also swallow the
# team-half-total variant ("<A> vs. <B>: <Team> 1st/2nd Half O/U <N>") whole
# (team = "<Team> 1st Half"), so soccer_team_total_rule explicitly rejects
# any team capture containing "half".
_Q_SOCCER_TEAM_TOTAL = re.compile(
    r"^(?P<team_a>.+?)\s+vs\.?\s+(?P<team_b>.+?):\s*(?P<team>.+?)\s+o/u\s*(?P<line>[\d.]+)\s*$",
    re.I,
)

# Game spread: "Spread: <Team> (-N)" / "(+N)" -- identical shape to MLB's
# _Q_SPREAD (see mlb_spread_rule); soccer has no F5-style prefixed variant to
# guard against.
_Q_SOCCER_SPREAD = re.compile(r"^spread:\s*(?P<team>.+?)\s*\(\s*([+-]?[\d.]+)\s*\)\s*$", re.I)

# 1st-half total: "<A> vs. <B>: 1st Half O/U <N>". Anchored on the literal
# "1st Half" directly after the colon (no team group at all in this
# pattern), so the team-half-total form ("<A> vs. <B>: <Team> 1st Half O/U
# <N>") never matches -- there's no way for a named team to appear before
# the required literal "1st".
_Q_SOCCER_FIRST_HALF_TOTAL = re.compile(
    r"^(.+?)\s+vs\.?\s+(.+?):\s*1st\s+half\s+o/u\s*([\d.]+)\s*$", re.I
)

# BTTS: "<A> vs. <B>: Both Teams to Score". Anchored with a trailing `$`
# directly after "score" (only whitespace allowed after), so the 1st-half
# variant ("...Both Teams to Score in First Half") never matches -- there's
# no way for "in first half" to satisfy the `\s*$` tail.
_Q_SOCCER_BTTS = re.compile(
    r"^(.+?)\s+vs\.?\s+(.+?):\s*both teams to score\s*$", re.I
)

# 1st-half BTTS: "<A> vs. <B>: Both Teams to Score in First Half". The
# literal "in first half" is required, so the plain BTTS question never
# matches this rule.
_Q_SOCCER_FIRST_HALF_BTTS = re.compile(
    r"^(.+?)\s+vs\.?\s+(.+?):\s*both teams to score in first half\s*$", re.I
)

# 3-way ML -- team win: "Will <Team> win on <YYYY-MM-DD>?" (byte-exact per
# wave-4 probe section C). Only ONE team is named; anchored on the literal
# " win on " + exact YYYY-MM-DD + trailing "?" so the draw form ("Will <A> vs.
# <B> end in a draw?", which has no " win on <date>" substring at all) never
# matches here.
_Q_SOCCER_ML_TEAM_WIN = re.compile(
    r"^will\s+(?P<team>.+?)\s+win on\s+\d{4}-\d{2}-\d{2}\?\s*$", re.I
)

# 3-way ML -- draw: "Will <A> vs. <B> end in a draw?". Names BOTH teams
# (unlike the team-win form above), so the fixture resolves the same way
# every other GAME-scope two-team form does. The pattern lives in
# soccer_question.py so gap harvest binds the same two names.

# 1st-half winner: "<Team> leading at halftime?" (byte-exact per wave-4 probe
# section C). Only ONE team is named; anchored on the literal "leading at
# halftime?" trailer so the 1st-half draw form ("<A> vs. <B>: Draw at
# halftime?", which has no "leading at halftime" substring at all) never
# matches here.
_Q_SOCCER_FIRST_HALF_LEADER = re.compile(
    r"^(?P<team>.+?)\s+leading at halftime\?\s*$", re.I
)

# 1st-half winner -- draw: "<A> vs. <B>: Draw at halftime?". Names BOTH teams.
_Q_SOCCER_FIRST_HALF_DRAW = re.compile(
    r"^(.+?)\s+vs\.?\s+(.+?):\s*draw at halftime\?\s*$", re.I
)

# Player goals ladder: "<Player>: N+ goals" (byte-exact per wave-4 probe
# section C; confirmed WORLD-CUP-only in poly -- 0/8,330 mls/mex/ucl rows,
# present for fifwc, e.g. "Alexander Sørloth: 1+ goals"). Anchored so "goals"
# must be the literal final word (only trailing whitespace allowed after it):
# this rejects "<Player>: 1+ assists" / "<Player>: 1+ shots" (no "goals"
# literal at all) AND "<Player>: 1+ goals + assists" (has "goals", but it's
# followed by " + assists", not just whitespace, so the trailing anchor
# fails) -- optic doesn't price player_assists/player_shots/goals_+_assists
# in this wave, so this rule must not fire on any of them.
_Q_SOCCER_PLAYER_GOALS = re.compile(r"^(?P<player>.+?):\s*(?P<n>\d+)\+\s*goals\s*$", re.I)


# === Rescue-tier soccer forms (probe: .superpowers/sdd/wave-rescue-probe-
# findings.md sections A/C). All reuse EXISTING SideModes (OVER_UNDER /
# YESNO_AS_OU / THREE_WAY_FIXED); build_rows is untouched. ===

# 2nd-half game total: "<A> vs. <B>: 2nd Half O/U <N>". Mirrors
# _Q_SOCCER_FIRST_HALF_TOTAL byte-for-byte ("1st"->"2nd"): anchored on the
# literal "2nd Half" directly after the colon (no team group), so the
# team-half-total form ("<A> vs. <B>: <Team> 2nd Half O/U <N>") never matches
# -- there's no way for a named team to appear before the required literal
# "2nd".
_Q_SOCCER_SECOND_HALF_TOTAL = re.compile(
    r"^(.+?)\s+vs\.?\s+(.+?):\s*2nd\s+half\s+o/u\s*([\d.]+)\s*$", re.I
)

# 1st/2nd-half team totals: "<A> vs. <B>: <Team> 1st/2nd Half O/U <N>".
# Byte-identical structure to _Q_SOCCER_TEAM_TOTAL, just with a "1st Half"/
# "2nd Half" literal inserted before "O/U" -- so `team` here captures the
# actual team name (never "half"), unlike the plain team-total form's guard.
_Q_SOCCER_FIRST_HALF_TEAM_TOTAL = re.compile(
    r"^(?P<team_a>.+?)\s+vs\.?\s+(?P<team_b>.+?):\s*(?P<team>.+?)\s+1st\s+half\s+o/u\s*(?P<line>[\d.]+)\s*$",
    re.I,
)
_Q_SOCCER_SECOND_HALF_TEAM_TOTAL = re.compile(
    r"^(?P<team_a>.+?)\s+vs\.?\s+(?P<team_b>.+?):\s*(?P<team>.+?)\s+2nd\s+half\s+o/u\s*(?P<line>[\d.]+)\s*$",
    re.I,
)

# 2nd-half winner -- team win: "<Team> to win the second half?". Mirrors
# _Q_SOCCER_FIRST_HALF_LEADER's shape exactly ("leading at halftime?" ->
# "to win the second half?"). Only ONE team is named.
_Q_SOCCER_SECOND_HALF_WINNER = re.compile(
    r"^(?P<team>.+?)\s+to win the second half\?\s*$", re.I
)

# 2nd-half winner -- draw: "<A> vs. <B>: Second half draw?". Names BOTH teams
# (mirrors _Q_SOCCER_FIRST_HALF_DRAW's shape, "Draw at halftime?" -> "Second
# half draw?").
_Q_SOCCER_SECOND_HALF_DRAW = re.compile(
    r"^(.+?)\s+vs\.?\s+(.+?):\s*second half draw\?\s*$", re.I
)

# First-to-score -- team: "<Team> to score first vs. <Opp>?". BOTH teams are
# named (unlike the single-team ml/half-leader forms), so both team_a/team_b
# are captured for direct Phase-A fixture resolution (see
# pipeline._resolve_poly_markets: THREE_WAY_FIXED only defers to Phase B when
# team_b is None). The complementary "<A> vs. <B>: Neither team to score
# first?" leg is a disjoint template (colon-prefixed, no "to score first vs."
# substring) that this pattern structurally cannot match -- see
# soccer_first_to_score_rule's docstring for why that leg is intentionally
# left unmapped rather than guarded against here.
_Q_SOCCER_FIRST_TO_SCORE = re.compile(
    r"^(?P<team>.+?)\s+to score first vs\.?\s+(?P<opp>.+?)\?\s*$", re.I
)

# World Cup player props (fifwc-only, byte-exact per findings section A.6).
# Each mirrors _Q_SOCCER_PLAYER_GOALS's shape (N+ ladder, YESNO_AS_OU, N-0.5
# line transform), differing only in the stat word.

# Goals-or-assists: "<Player>: N+ goals + assists". Ordered/anchored so this
# does NOT collide with the plain "goals" or "assists" ladders -- the literal
# "+ assists" tail after "goals" is required, which _Q_SOCCER_PLAYER_GOALS's
# own trailing anchor (bare "goals$") already rejects (see that regex's
# comment); this pattern requires the opposite (goals must be followed by
# "+ assists", not just whitespace).
_Q_SOCCER_PLAYER_GOALS_ASSISTS = re.compile(
    r"^(?P<player>.+?):\s*(?P<n>\d+)\+\s*goals\s*\+\s*assists\s*$", re.I
)

# Shots-on-target: "<Player>: N+ shots on target". Must be recognized BEFORE
# the plain shots ladder is even considered (see _Q_SOCCER_PLAYER_SHOTS'S
# comment for why the reverse direction is already anchor-safe).
_Q_SOCCER_PLAYER_SHOTS_ON_TARGET = re.compile(
    r"^(?P<player>.+?):\s*(?P<n>\d+)\+\s*shots on target\s*$", re.I
)

# Plain shots: "<Player>: N+ shots". Anchored so "shots" must be the literal
# final word (only trailing whitespace allowed after it) -- this rejects
# "<Player>: N+ shots on target" (the trailing anchor `shots\s*$` fails
# against "shots on target", since "on target" isn't whitespace), the same
# technique _Q_SOCCER_PLAYER_GOALS already uses against "goals + assists".
_Q_SOCCER_PLAYER_SHOTS = re.compile(r"^(?P<player>.+?):\s*(?P<n>\d+)\+\s*shots\s*$", re.I)

# Assists: "<Player>: N+ assists".
_Q_SOCCER_PLAYER_ASSISTS = re.compile(r"^(?P<player>.+?):\s*(?P<n>\d+)\+\s*assists\s*$", re.I)

# Exact score: "Exact Score: <A> N1 - N2 <B>?" (byte-exact per
# wave-rescue-probe-findings.md section A.1: " - " space-hyphen-space
# between the digits, no space before the trailing "?"). Uniquely anchored
# on the literal "Exact Score:" prefix, disjoint from every other soccer
# form. The catch-all sibling "Exact Score: Any Other Score?" has no digit
# group at all, so it structurally fails this pattern (never invented) --
# see soccer_exact_score_rule's docstring.
_Q_SOCCER_EXACT_SCORE = re.compile(
    r"^Exact Score:\s*(?P<a>.+?)\s+(?P<sa>\d+)\s*-\s*(?P<sb>\d+)\s+(?P<b>.+?)\?\s*$",
    re.I,
)


# Full-game total corners: "<A> vs. <B>: O/U <N> Total Corners". Anchored on
# the literal "o/u <N> total corners" running to `$`, directly after the colon:
#   - the plain game total ("...: O/U <N>") can't match here -- it has no
#     "total corners" tail;
#   - conversely _Q_SOCCER_TOTAL / _Q_SOCCER_TEAM_TOTAL can't match THIS form,
#     because both anchor `$` immediately after their line group and this
#     question carries a " Total Corners" tail;
#   - the half-corners variants ("...: 1st/2nd Half O/U <N> Total Corners")
#     never match, since "o/u" is required immediately after the colon and
#     there is only one ":" in these questions for team_b to backtrack over.
#     (Optic prices no 1st/2nd-half corners market, so those stay unmapped.)
#   - the two non-O/U corners forms poly also lists ("Total Corners Odd or
#     Even?", "Team to Take First Corner") have no "o/u <N>" at all.
# Optic target: `total_corners`, priced across every wired soccer league (BQ
# census 2026-07-27, 14d: mls 284k / ucl 584k / liga_mx 153k / bra 113k /
# arg 355k ticks, plus every soccer-expansion league). Line semantics match
# total_goals -- unsigned N.5 over/under (see world_cup.py's corners note on
# ET-inclusive settlement, which applies to knockout ties only).
_Q_SOCCER_TOTAL_CORNERS = re.compile(
    r"^(.+?)\s+vs\.?\s+(.+?):\s*o/u\s*([\d.]+)\s+total\s+corners\s*$", re.I
)

# Team total corners: "<A> vs. <B>: <Team> O/U <N> Corners". Requires a named
# team between the colon and o/u, and ends on bare "corners" (not "total
# corners") so the full-game form above never matches. Half-corners
# ("1st/2nd Half O/U N Total Corners") fail the same way -- no team between
# colon and o/u, and the "total corners" tail. Optic target: `team_total_corners`
# (wired in SOCCER_OPTIC_TABLE_TYPES; live on UCL 2026-08).
_Q_SOCCER_TEAM_TOTAL_CORNERS = re.compile(
    r"^(?P<a>.+?)\s+vs\.?\s+(?P<b>.+?):\s*(?P<team>.+?)\s+o/u\s*(?P<line>[\d.]+)\s+corners\s*$",
    re.I,
)

# Player saves ladder: "<Player>: N+ saves" -- same shape as the goals/shots/
# assists ladders, different stat word. Optic target: `player_saves` (live for
# fifwc 276k / mls / liga_mx / arg ticks over 14d).
_Q_SOCCER_PLAYER_SAVES = re.compile(r"^(?P<player>.+?):\s*(?P<n>\d+)\+\s*saves\s*$", re.I)


def soccer_total_corners_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Full-game total corners: "<A> vs. <B>: O/U N Total Corners" ->
    OVER_UNDER (GAME), line=N.

    Structurally identical to soccer_total_rule bar the market_types key and
    the "Total Corners" tail its regex requires (see _Q_SOCCER_TOTAL_CORNERS
    for why neither form can match the other's questions).
    """
    q = (question or "").strip()
    m = _Q_SOCCER_TOTAL_CORNERS.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("total_corners")
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


def soccer_team_total_corners_rule(
    question: str, cfg: PolymarketConfig
) -> ParsedMarket | None:
    """Team corners: "<A> vs. <B>: <Team> O/U N Corners" -> OVER_UNDER (TEAM).

    Mirrors soccer_team_total_rule with a corners tail; rejects half-bearing
    team captures the same way so half forms cannot land here.
    """
    q = (question or "").strip()
    m = _Q_SOCCER_TEAM_TOTAL_CORNERS.match(q)
    if not m:
        return None
    team_raw = m.group("team")
    if re.search(r"(?i)\bhalf\b", team_raw):
        return None
    mt = cfg.market_types.get("team_total_corners")
    if mt is None:
        return None
    try:
        line = float(m.group("line"))
    except ValueError:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group("a"), style),
        team_b=_norm_name(m.group("b"), style),
        side_mode=SideMode.OVER_UNDER,
        entity=_norm_name(team_raw, style),
        line=line,
    )


def soccer_player_saves_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Player saves ladder: "<Player>: N+ saves" -> YESNO_AS_OU (PLAYER),
    line=N-0.5. Mirrors soccer_player_shots_rule with a different stat word.
    """
    return _player_prop_rule(
        question,
        cfg,
        _Q_SOCCER_PLAYER_SAVES,
        "player_saves",
        side_mode=SideMode.YESNO_AS_OU,
        line_transform=lambda n: n - 0.5,
    )


def soccer_total_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Full-game total: "<A> vs. <B>: O/U N" -> OVER_UNDER (GAME).

    Mirrors mlb_total_rule's anchoring guard: the team-total and both half
    forms never match here (see _Q_SOCCER_TOTAL comment).
    """
    q = (question or "").strip()
    m = _Q_SOCCER_TOTAL.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("total")
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


def soccer_team_total_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Team total: "<A> vs. <B>: <Team> O/U N" -> OVER_UNDER (TEAM), entity=<Team>.

    entity is the TEAM-scope normalized team name (build_rows resolves it to
    the fixture abbrev). Explicitly rejects a team capture containing "half"
    so the team-half-total form doesn't slip through (see _Q_SOCCER_TEAM_TOTAL
    comment).
    """
    q = (question or "").strip()
    m = _Q_SOCCER_TEAM_TOTAL.match(q)
    if not m:
        return None
    team_raw = m.group("team")
    if re.search(r"(?i)\bhalf\b", team_raw):
        return None
    mt = cfg.market_types.get("team_total")
    if mt is None:
        return None
    try:
        line = float(m.group("line"))
    except ValueError:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group("team_a"), style),
        team_b=_norm_name(m.group("team_b"), style),
        side_mode=SideMode.OVER_UNDER,
        entity=_norm_name(team_raw, style),
        line=line,
    )


def soccer_spread_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Game spread: "Spread: <Team> (-N)" -> SPREAD_TEAM (GAME).

    Identical parsing to mlb_spread_rule: one named team + its signed line in
    entity; both outcome labels are the two team names, resolved by build_rows.
    """
    q = (question or "").strip()
    m = _Q_SOCCER_SPREAD.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("spread")
    if mt is None:
        return None
    try:
        line = float(m.group(2))
    except ValueError:
        return None
    return ParsedMarket(
        market_type=mt,
        team_a=None,
        team_b=None,
        side_mode=SideMode.SPREAD_TEAM,
        entity=_norm_name(m.group("team"), cfg.question_style),
        line=line,
    )


def soccer_first_half_total_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """1st-half total: "<A> vs. <B>: 1st Half O/U N" -> OVER_UNDER (GAME).

    Anchored on the literal "1st Half" directly after the colon, so the
    team-half-total form never matches (see _Q_SOCCER_FIRST_HALF_TOTAL comment).
    """
    q = (question or "").strip()
    m = _Q_SOCCER_FIRST_HALF_TOTAL.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("first_half_total")
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


def soccer_btts_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """BTTS: "<A> vs. <B>: Both Teams to Score" -> YESNO (GAME).

    First live SideMode.YESNO recognizer (build_rows' YESNO branch was
    implemented for this exact shape but never yet driven by a real rule).
    Anchored so the "in First Half" variant is rejected -- see
    _Q_SOCCER_BTTS comment (ordering guard).
    """
    q = (question or "").strip()
    m = _Q_SOCCER_BTTS.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("btts")
    if mt is None:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group(1), style),
        team_b=_norm_name(m.group(2), style),
        side_mode=SideMode.YESNO,
    )


def soccer_first_half_btts_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """1st-half BTTS: "<A> vs. <B>: Both Teams to Score in First Half" -> YESNO (GAME).

    Anchored on the literal "in first half" tail, so the plain BTTS question
    never matches here (see _Q_SOCCER_FIRST_HALF_BTTS comment).
    """
    q = (question or "").strip()
    m = _Q_SOCCER_FIRST_HALF_BTTS.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("first_half_btts")
    if mt is None:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group(1), style),
        team_b=_norm_name(m.group(2), style),
        side_mode=SideMode.YESNO,
    )


def soccer_ml_team_win_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """3-way ML -- team win: "Will <Team> win on <YYYY-MM-DD>?" ->
    THREE_WAY_FIXED (GAME), fixed_side_team=<Team>.

    First live THREE_WAY_FIXED exercise. Poly encodes soccer 3-way ML as
    THREE separate Yes/No markets per fixture; this rule owns only the
    team-win shape (the draw shape is soccer_ml_draw_rule's).

    Only ONE team is named in the question, so team_b stays None (mirrors
    the single-team MLB spread/prop rules) -- verified this is safe for
    build_rows' THREE_WAY_FIXED branch (frozen), which reads
    parsed.fixed_side_team plus the caller-supplied home_name/away_name and
    never parsed.team_a/team_b for this SideMode.
    """
    q = (question or "").strip()
    m = _Q_SOCCER_ML_TEAM_WIN.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("moneyline_3way")
    if mt is None:
        return None
    team = _norm_name(m.group("team"), cfg.question_style)
    return ParsedMarket(
        market_type=mt,
        team_a=team,
        team_b=None,
        side_mode=SideMode.THREE_WAY_FIXED,
        fixed_side_team=team,
    )


def soccer_ml_draw_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """3-way ML -- draw: "Will <A> vs. <B> end in a draw?" -> THREE_WAY_FIXED
    (GAME), fixed_side_team=None (-> _TIE in build_rows).

    Both teams are named in the question (unlike the team-win form), so
    team_a/team_b are both set here.
    """
    q = (question or "").strip()
    m = _Q_SOCCER_ML_DRAW.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("moneyline_3way")
    if mt is None:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group(1), style),
        team_b=_norm_name(m.group(2), style),
        side_mode=SideMode.THREE_WAY_FIXED,
        fixed_side_team=None,
    )


def soccer_first_half_leader_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """1st-half winner: "<Team> leading at halftime?" -> THREE_WAY_FIXED
    (GAME), fixed_side_team=<Team>.

    Only ONE team is named; team_b stays None -- same rationale as
    soccer_ml_team_win_rule.
    """
    q = (question or "").strip()
    m = _Q_SOCCER_FIRST_HALF_LEADER.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("first_half_winner_3way")
    if mt is None:
        return None
    team = _norm_name(m.group("team"), cfg.question_style)
    return ParsedMarket(
        market_type=mt,
        team_a=team,
        team_b=None,
        side_mode=SideMode.THREE_WAY_FIXED,
        fixed_side_team=team,
    )


def soccer_first_half_draw_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """1st-half winner -- draw: "<A> vs. <B>: Draw at halftime?" ->
    THREE_WAY_FIXED (GAME), fixed_side_team=None (-> _TIE in build_rows).

    Both teams are named in the question.
    """
    q = (question or "").strip()
    m = _Q_SOCCER_FIRST_HALF_DRAW.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("first_half_winner_3way")
    if mt is None:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group(1), style),
        team_b=_norm_name(m.group(2), style),
        side_mode=SideMode.THREE_WAY_FIXED,
        fixed_side_team=None,
    )


def soccer_player_goals_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Player goals ladder: "<Player>: N+ goals" -> YESNO_AS_OU (PLAYER),
    line=N-0.5 (i.e. "1+ goals" -> over 0.5, "2+ goals" -> over 1.5).

    Reuses _player_prop_rule with the Yes/No side_mode + the N-0.5 line
    transform: poly's Yes/No ladder threshold is the anytime-goalscorer line
    optic already prices as player_goals over N-0.5 (MarketType.PLAYER_GOALS).
    Matches ONLY "goals" -- see _Q_SOCCER_PLAYER_GOALS's anchoring comment for
    why assists/shots/"goals + assists" never match here.
    """
    return _player_prop_rule(
        question,
        cfg,
        _Q_SOCCER_PLAYER_GOALS,
        "player_goals",
        side_mode=SideMode.YESNO_AS_OU,
        line_transform=lambda n: n - 0.5,
    )


# === Rescue-tier recognizers (probe: .superpowers/sdd/wave-rescue-probe-
# findings.md). Every one reuses an EXISTING SideMode (OVER_UNDER /
# YESNO_AS_OU / THREE_WAY_FIXED) -- build_rows (frozen) is not touched. ===


def soccer_second_half_total_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """2nd-half total: "<A> vs. <B>: 2nd Half O/U N" -> OVER_UNDER (GAME).

    Mirrors soccer_first_half_total_rule byte-for-byte ("1st"->"2nd").
    Anchored on the literal "2nd Half" directly after the colon, so the
    team-half-total form never matches (see _Q_SOCCER_SECOND_HALF_TOTAL
    comment).
    """
    q = (question or "").strip()
    m = _Q_SOCCER_SECOND_HALF_TOTAL.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("second_half_total")
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


def soccer_first_half_team_total_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """1st-half team total: "<A> vs. <B>: <Team> 1st Half O/U N" ->
    OVER_UNDER (TEAM), entity=<Team>.

    Mirrors soccer_team_total_rule's shape with a "1st Half" literal inserted
    before O/U (see _Q_SOCCER_FIRST_HALF_TEAM_TOTAL comment).
    """
    q = (question or "").strip()
    m = _Q_SOCCER_FIRST_HALF_TEAM_TOTAL.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("first_half_team_total")
    if mt is None:
        return None
    try:
        line = float(m.group("line"))
    except ValueError:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group("team_a"), style),
        team_b=_norm_name(m.group("team_b"), style),
        side_mode=SideMode.OVER_UNDER,
        entity=_norm_name(m.group("team"), style),
        line=line,
    )


def soccer_second_half_team_total_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """2nd-half team total: "<A> vs. <B>: <Team> 2nd Half O/U N" ->
    OVER_UNDER (TEAM), entity=<Team>. Mirrors soccer_first_half_team_total_rule
    ("1st"->"2nd") -- see _Q_SOCCER_SECOND_HALF_TEAM_TOTAL comment.
    """
    q = (question or "").strip()
    m = _Q_SOCCER_SECOND_HALF_TEAM_TOTAL.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("second_half_team_total")
    if mt is None:
        return None
    try:
        line = float(m.group("line"))
    except ValueError:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group("team_a"), style),
        team_b=_norm_name(m.group("team_b"), style),
        side_mode=SideMode.OVER_UNDER,
        entity=_norm_name(m.group("team"), style),
        line=line,
    )


def soccer_second_half_winner_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """2nd-half winner: "<Team> to win the second half?" -> THREE_WAY_FIXED
    (GAME), fixed_side_team=<Team>.

    Mirrors soccer_first_half_leader_rule byte-for-byte ("leading at
    halftime?" -> "to win the second half?"). Only ONE team is named;
    team_b stays None -- same rationale as soccer_first_half_leader_rule.
    """
    q = (question or "").strip()
    m = _Q_SOCCER_SECOND_HALF_WINNER.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("second_half_winner_3way")
    if mt is None:
        return None
    team = _norm_name(m.group("team"), cfg.question_style)
    return ParsedMarket(
        market_type=mt,
        team_a=team,
        team_b=None,
        side_mode=SideMode.THREE_WAY_FIXED,
        fixed_side_team=team,
    )


def soccer_second_half_draw_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """2nd-half winner -- draw: "<A> vs. <B>: Second half draw?" ->
    THREE_WAY_FIXED (GAME), fixed_side_team=None (-> _TIE in build_rows).

    Mirrors soccer_first_half_draw_rule ("Draw at halftime?" -> "Second half
    draw?"). Both teams are named in the question.
    """
    q = (question or "").strip()
    m = _Q_SOCCER_SECOND_HALF_DRAW.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("second_half_winner_3way")
    if mt is None:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group(1), style),
        team_b=_norm_name(m.group(2), style),
        side_mode=SideMode.THREE_WAY_FIXED,
        fixed_side_team=None,
    )


def soccer_first_to_score_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """First-to-score: "<Team> to score first vs. <Opp>?" -> THREE_WAY_FIXED
    (GAME), fixed_side_team=<Team> (the FIRST-named team, the one before
    " to score first").

    Both teams are named in the question (unlike soccer_ml_team_win_rule/
    soccer_first_half_leader_rule's single-team forms), so team_a/team_b are
    both set here -- this lets the market resolve its fixture directly in
    Phase A (pipeline._resolve_poly_markets only defers a THREE_WAY_FIXED
    market to Phase B when team_b is None).

    This rule binds only the TEAM legs. The complementary "<A> vs. <B>: Neither
    team to score first?" question is now handled by its own rule --
    soccer_neither_scores_first_rule, which binds the _TIE side (optic's "Draw"
    selection of the same first_team_to_score market). It used to be left
    unrecognized on the belief that optic had no clean selection for it; a BQ
    census disproved that, and the reasoning is documented on that rule.

    This rule's own anchor (requiring the literal "to score first vs."
    substring) structurally cannot match the colon-prefixed neither form, so the
    two never compete regardless of tuple order.
    """
    q = (question or "").strip()
    m = _Q_SOCCER_FIRST_TO_SCORE.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("first_team_to_score")
    if mt is None:
        return None
    style = cfg.question_style
    team = _norm_name(m.group("team"), style)
    return ParsedMarket(
        market_type=mt,
        team_a=team,
        team_b=_norm_name(m.group("opp"), style),
        side_mode=SideMode.THREE_WAY_FIXED,
        fixed_side_team=team,
    )


# "<A> vs. <B>: Neither team to score first?" (labels Yes/No, n_outcomes=2).
_Q_SOCCER_NEITHER_SCORES_FIRST = re.compile(
    r"^(.+?)\s+vs\.?\s+(.+?):\s*neither team to score first\?\s*$", re.I
)


def soccer_neither_scores_first_rule(
    question: str, cfg: PolymarketConfig
) -> ParsedMarket | None:
    """Neither-scores-first: "<A> vs. <B>: Neither team to score first?" ->
    THREE_WAY_FIXED (GAME) on the _TIE side, i.e. optic's "Draw" selection of
    first_team_to_score.

    REVERSES an earlier deliberate exclusion. soccer_first_to_score_rule's
    docstring used to state that this leg "has no clean optic selection under
    THREE_WAY_FIXED's binary team/_TIE vocabulary (_TIE means Draw, not 'no goal
    scored')" and left it unrecognized under the never-invent-a-mapping mandate.
    A BQ census (14d of opticodds_prices, 2026-07-27) shows that premise is
    wrong on both counts:

      - optic DOES price the leg: market_id=first_team_to_score ships a third
        selection literally named "Draw" -- 16,921 ticks across 588 fixtures,
        present in all 7 wired soccer leagues -- with a null/empty team_id,
        which optic.build_rows' THREE_WAY branch maps to TIE_SIDE. So there is
        exactly ONE optic selection for this question, and nothing is invented.
      - within THIS market "Draw" can only mean "no goal was scored". It cannot
        mean the match-result draw: if either side scored first, that side wins
        the market regardless of the final score, so a 1-1 match already belongs
        to a team selection. Reading "Draw" as the match result would make
        optic's three selections overlapping and non-exhaustive.

    Both teams are named, so this resolves its fixture in Phase A exactly like
    soccer_first_to_score_rule. fixed_side_team=None is what selects the _TIE
    side (see ParsedMarket.fixed_side_team), and only the affirmative "Yes"
    outcome emits -- poly's "No" leg is the union of the two team selections and
    correctly has no single optic counterpart, so THREE_WAY_FIXED drops it.
    """
    q = (question or "").strip()
    m = _Q_SOCCER_NEITHER_SCORES_FIRST.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("first_team_to_score")
    if mt is None:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group(1), style),
        team_b=_norm_name(m.group(2), style),
        side_mode=SideMode.THREE_WAY_FIXED,
        fixed_side_team=None,   # -> _TIE, optic's "Draw" selection
    )


# "<Player>: Anytime Goalscorer" (labels Yes/No). No line in the question -- the
# line is synthesized as 0.5 (see soccer_anytime_goalscorer_rule).
_Q_SOCCER_ANYTIME_GOALSCORER = re.compile(
    r"^(?P<player>.+?):\s*anytime goalscorer\s*$", re.I
)


def soccer_anytime_goalscorer_rule(
    question: str, cfg: PolymarketConfig
) -> ParsedMarket | None:
    """Anytime goalscorer: "<Player>: Anytime Goalscorer" -> YESNO_AS_OU
    (PLAYER) on PLAYER_GOALS @ line 0.5; CanonicalRow then canonicalises
    that 0.5 rung as ANYTIME_GOAL_SCORER (mappers/anytime_scorer.py), the
    same for every venue.  Older notes below predate that fold.

    This is the mapping world_cup.py's `player_goals` comment already
    prescribes. Optic ships a separate `anytime_goal_scorer` market, and it is
    ignored BY DESIGN: on the probed fixture every book quoting it also quoted
    player_goals over 0.5 for the identical player set, so giving it its own
    MarketType would double-count one real-world question across two rows. That
    comment's stated remedy is exactly this -- "if a book ever shows up
    anytime-only, fold it in by synthesizing line=0.5/side=over onto the same
    row" -- so poly's anytime question folds onto the player_goals 0.5 row
    instead of getting a MarketType of its own. No new MarketType, no
    double-count, and it merges with the Kalshi/crypto anytime legs already
    living on that row.

    "Anytime goalscorer" and "1+ goals" are the same bet, so this rule and
    soccer_player_goals_rule can both produce (player_goals, 0.5, over). A
    census of the live bridge found ZERO (fixture, player) pairs carrying both
    forms, so no row is contested today; were poly to list both for one player,
    the two tokens would collide on the row key and only one would stamp. That
    is a coverage limit, not a flip-safety one -- both tokens denote the
    identical outcome, so whichever stamps is correctly priced.
    """
    q = (question or "").strip()
    m = _Q_SOCCER_ANYTIME_GOALSCORER.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("player_goals")
    if mt is None:
        return None
    entity = normalize_player_name(m.group("player"))
    if _active_team_aliases:
        entity = _active_team_aliases.get(entity, entity)
    return ParsedMarket(
        market_type=mt,
        team_a=None,
        team_b=None,
        side_mode=SideMode.YESNO_AS_OU,
        entity=entity,
        line=0.5,
    )


def soccer_player_goals_or_assists_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Player goals-or-assists ladder: "<Player>: N+ goals + assists" ->
    YESNO_AS_OU (PLAYER), line=N-0.5.

    Reuses MarketType.PLAYER_GOALS_OR_ASSIST (already defined; previously
    wired only via crypto.com's binary "To Score Or Give Assist" market --
    see world_cup.py). Matches ONLY the "goals + assists" combined ladder --
    see _Q_SOCCER_PLAYER_GOALS_ASSISTS comment for why the plain goals/
    assists ladders never collide with this one.
    """
    return _player_prop_rule(
        question,
        cfg,
        _Q_SOCCER_PLAYER_GOALS_ASSISTS,
        "player_goals_or_assists",
        side_mode=SideMode.YESNO_AS_OU,
        line_transform=lambda n: n - 0.5,
    )


def soccer_player_shots_on_target_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Player shots-on-target ladder: "<Player>: N+ shots on target" ->
    YESNO_AS_OU (PLAYER), line=N-0.5. Ordered before soccer_player_shots_rule
    (see _Q_SOCCER_PLAYER_SHOTS_ON_TARGET / _Q_SOCCER_PLAYER_SHOTS comments).
    """
    return _player_prop_rule(
        question,
        cfg,
        _Q_SOCCER_PLAYER_SHOTS_ON_TARGET,
        "player_shots_on_target",
        side_mode=SideMode.YESNO_AS_OU,
        line_transform=lambda n: n - 0.5,
    )


def soccer_player_shots_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Player shots ladder: "<Player>: N+ shots" -> YESNO_AS_OU (PLAYER),
    line=N-0.5. Anchored so "N+ shots on target" never matches here (see
    _Q_SOCCER_PLAYER_SHOTS comment) -- soccer_player_shots_on_target_rule
    owns that shape.
    """
    return _player_prop_rule(
        question,
        cfg,
        _Q_SOCCER_PLAYER_SHOTS,
        "player_shots",
        side_mode=SideMode.YESNO_AS_OU,
        line_transform=lambda n: n - 0.5,
    )


def soccer_player_assists_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Player assists ladder: "<Player>: N+ assists" -> YESNO_AS_OU (PLAYER),
    line=N-0.5. World-Cup-only (fifwc); mirrors soccer_player_goals_rule with
    a different stat word.
    """
    return _player_prop_rule(
        question,
        cfg,
        _Q_SOCCER_PLAYER_ASSISTS,
        "player_assists",
        side_mode=SideMode.YESNO_AS_OU,
        line_transform=lambda n: n - 0.5,
    )


def soccer_exact_score_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Exact score: "Exact Score: <A> N1 - N2 <B>?" -> EXACT_SCORE (GAME).

    The single biggest dropped soccer form (~2,284 rows, 27% of poly soccer
    per wave-rescue-probe-findings.md) -- needs its own Shape/SideMode since
    none of the other 6 emit a scoreline-keyed row (see market_types.py's
    Shape.CORRECT_SCORE comment and build_rows' EXACT_SCORE branch).

    team_a_goals/team_b_goals are the two digits parsed straight from the
    question in the order they appear -- NOT yet resolved to home/away
    (build_rows does that by NAME match, flip-safe, mirroring
    soccer_first_to_score_rule's team_a/team_b convention).

    The catch-all sibling "Exact Score: Any Other Score?" has no digit group
    at all, so it structurally fails _Q_SOCCER_EXACT_SCORE and returns None
    here -- per the "never invent" mandate, that catch-all stays permanently
    unmapped (Optic's correct_score grid extends beyond poly's 0-3x0-3 cells,
    so "Any Other Score" has no single matching Optic selection; see the
    probe's section B.1 grid-boundary finding). No separate guard is needed
    for it: it simply never matches this pattern.
    """
    q = (question or "").strip()
    m = _Q_SOCCER_EXACT_SCORE.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("exact_score")
    if mt is None:
        return None
    try:
        sa = int(m.group("sa"))
        sb = int(m.group("sb"))
    except ValueError:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group("a"), style),
        team_b=_norm_name(m.group("b"), style),
        side_mode=SideMode.EXACT_SCORE,
        team_a_goals=sa,
        team_b_goals=sb,
    )


# Shared `market_types` dict for every soccer league's PolymarketConfig (Tasks
# 6/7 wire this in verbatim, one constant instead of a copy per league). 9
# distinct keys back the 11 soccer_market_rules recognizers below
# (moneyline_3way and first_half_winner_3way are each shared by two rules —
# team-win/leader vs. their draw sibling — same MarketType, differing only in
# fixed_side_team). A league whose OpticConfig doesn't price one of these
# MarketTypes is NOT protected by a missing-key drop here (every key always
# resolves, since this dict is shared) — the real gate is downstream, in
# pipeline.attach_polymarket_row: a poly row only stamps onto an ALREADY
# EXISTING optic row for the same (game, market_type, line, side); a
# MarketType optic never priced for that league has no such row, so the poly
# row is dropped there ("dropped_no_optic"), never invented standalone.
SOCCER_MARKET_TYPES: dict[str, MarketType] = {
    "total": MarketType.GAME_TOTAL,
    "team_total": MarketType.TEAM_TOTAL,
    "spread": MarketType.POINT_SPREAD,
    "first_half_total": MarketType.FIRST_HALF_TOTAL,
    "btts": MarketType.BTTS,
    "first_half_btts": MarketType.FIRST_HALF_BTTS,
    "moneyline_3way": MarketType.MONEYLINE_3WAY,
    "first_half_winner_3way": MarketType.FIRST_HALF_WINNER_3WAY,
    "player_goals": MarketType.PLAYER_GOALS,
    # Rescue tier (wave-rescue-probe-findings.md) -- 9 new keys backing the 10
    # new recognizers below (second_half_winner_3way is shared by the
    # winner/draw pair, same convention as moneyline_3way/first_half_winner_3way
    # above).
    "second_half_total": MarketType.SECOND_HALF_TOTAL,
    "first_half_team_total": MarketType.FIRST_HALF_TEAM_TOTAL,
    "second_half_team_total": MarketType.SECOND_HALF_TEAM_TOTAL,
    "second_half_winner_3way": MarketType.SECOND_HALF_WINNER_3WAY,
    "first_team_to_score": MarketType.FIRST_TEAM_TO_SCORE,
    "player_assists": MarketType.PLAYER_ASSISTS,
    "player_shots": MarketType.PLAYER_SHOTS,
    "player_shots_on_target": MarketType.PLAYER_SHOTS_ON_TARGET,
    "player_goals_or_assists": MarketType.PLAYER_GOALS_OR_ASSIST,
    # Task R4 (correct_score) -- see market_types.py's Shape.CORRECT_SCORE
    # comment; needs its own Shape/SideMode, not a config-only rescue.
    "exact_score": MarketType.CORRECT_SCORE,
    # Corners/saves parity (BQ census 2026-07-27): optic prices `total_corners`
    # and `player_saves` across the wired soccer leagues, and poly's
    # "O/U <N> Total Corners" was the single largest addressable soccer
    # market-type gap in the MAPPING_FAILED audit (~$3.5M declined stake over
    # 48h, top form for bra/mex/swe/nor/kor/uslc). Half-corners
    # ("1st/2nd Half O/U <N> Total Corners"), "Total Corners Odd or Even?" and
    # "Team to Take First Corner" are deliberately absent: optic prices no
    # corresponding market, so a key here would only manufacture rows that
    # attach_polymarket_row drops.
    "total_corners": MarketType.TOTAL_CORNERS,
    # Team corners: Optic prices `team_total_corners` (UCL live 2026-08);
    # poly form "<A> vs. <B>: <Team> O/U N Corners". Half-corners / odd-even /
    # first-corner stay absent -- Optic has no matching market_id.
    "team_total_corners": MarketType.TEAM_TOTAL_CORNERS,
    "player_saves": MarketType.PLAYER_SAVES,
}


# Ordered ALL-soccer recognizer tuple (Tasks 6/7 wire this into each league's
# PolymarketConfig.market_rules). Every rule above is already self-guarding
# via its regex anchor (see each rule's docstring), so this ordering is a
# DEFENSIVE belt-and-suspenders measure, not a correctness requirement -- kept
# most-specific-first throughout so a future anchoring regression fails safe
# (falls through to a more general rule, or drops the market) rather than
# silently mis-classifying it:
#   1. player_goals_or_assists -- most specific player-prop shape ("goals +
#                              assists"); ordered before the plain goals/shots
#                              ladders it could otherwise be confused with.
#   2. player_shots_on_target -- more specific than the plain shots ladder;
#                              must be considered before it (self-guarded via
#                              anchor too, but kept first defensively).
#   3. player_goals         -- distinct single-colon player-prop shape with no
#                              team names at all; ordered early so it can
#                              never be shadowed by any GAME-scope form.
#   4. player_shots         -- plain shots ladder (after shots_on_target).
#   5. player_assists       -- plain assists ladder.
#   6. first_half_team_total -- names ONE team + "1st Half"; must win over
#                              both the plain team-total and the game-scoped
#                              half-total forms.
#   7. second_half_team_total -- same as #6, "2nd Half".
#   8. team_total           -- names ONE team explicitly; must win over the
#                              full-game total (which names none).
#   9. first_half_total     -- half-scoped; must win over the full-game total.
#  10. second_half_total    -- half-scoped ("2nd Half"); must win over the
#                              full-game total.
#  11. total                -- full-game total, the most general O/U form,
#                              ordered last within the total family.
#  12. spread               -- disjoint "Spread:" prefix family (no overlap
#                              with the "<A> vs. <B>" forms above).
#  13. first_half_btts      -- half-scoped; must win over the plain BTTS form.
#  14. btts                 -- plain BTTS, most general of the BTTS family.
#  15. ml_draw              -- names BOTH teams ("... end in a draw?");
#                              ordered before the team-win form per the same
#                              specific-before-general principle.
#  16. ml_team_win           -- names ONE team ("Will <Team> win on <date>?").
#  17. first_half_draw       -- half-scoped draw; before the half-leader form.
#  18. first_half_leader     -- half-scoped single-team leader form.
#  19. second_half_draw      -- 2nd-half draw; before the 2nd-half winner form.
#  20. second_half_winner    -- 2nd-half single-team winner form.
#  21. first_to_score        -- disjoint "to score first vs." family (its own
#                              anchor never overlaps any form above); ordered
#                              last as it's the least game-line-like shape.
#  22. exact_score           -- disjoint "Exact Score:" prefix family (Task
#                              R4); uniquely anchored, never overlaps any
#                              form above, so its position in the tuple is
#                              not correctness-critical -- kept last.
#  23. total_corners        -- "...: O/U <N> Total Corners"; ordered ahead of
#                              the whole O/U family (team_total / half totals /
#                              total) so that even if one of their `$`-anchors
#                              regressed, the corners form still resolves to
#                              the corners market rather than silently landing
#                              on a goals total (a wrong-market mismap of the
#                              same class as the Wave-2 prefix-descriptor
#                              finding).
#  24. player_saves         -- plain saves ladder; sits with the other player
#                              ladders, anchored on its own stat word.
soccer_market_rules: tuple[MarketRule, ...] = (
    soccer_player_goals_or_assists_rule,
    soccer_player_shots_on_target_rule,
    soccer_player_goals_rule,
    soccer_player_shots_rule,
    soccer_player_assists_rule,
    soccer_player_saves_rule,
    # Anchored on the literal ": anytime goalscorer" tail with no N+ ladder, so
    # it cannot match any of the "<Player>: N+ <stat>" prop forms above (and
    # they cannot match it). Folds onto PLAYER_GOALS @ 0.5 -- see its docstring.
    soccer_anytime_goalscorer_rule,
    soccer_team_total_corners_rule,
    soccer_total_corners_rule,
    soccer_first_half_team_total_rule,
    soccer_second_half_team_total_rule,
    soccer_team_total_rule,
    soccer_first_half_total_rule,
    soccer_second_half_total_rule,
    soccer_total_rule,
    soccer_spread_rule,
    soccer_first_half_btts_rule,
    soccer_btts_rule,
    soccer_ml_draw_rule,
    soccer_ml_team_win_rule,
    soccer_first_half_draw_rule,
    soccer_first_half_leader_rule,
    soccer_second_half_draw_rule,
    soccer_second_half_winner_rule,
    soccer_first_to_score_rule,
    # Sibling of the rule above on the same optic market (first_team_to_score):
    # that one binds a named TEAM side, this one binds the _TIE ("Draw" = no goal
    # scored) side. Their anchors are structurally disjoint -- "to score first
    # vs." vs. the colon-prefixed ": neither team to score first?" -- so neither
    # can match the other's question regardless of order.
    soccer_neither_scores_first_rule,
    soccer_exact_score_rule,
)
