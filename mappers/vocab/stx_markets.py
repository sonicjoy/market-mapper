"""STX market vocabulary: ``(sport, rules, stat)`` -> Optic market id, and which families map today.

Every Optic id here is one mmmapper already maps for that sport (``*_OPTIC_TABLE_TYPES``; a test pins it), so the
canonical ``MarketType`` comes from that table, never from this file. YES / NO per market is in
``mappers/exchanges/stx.py``; this file decides only WHICH Optic market and WHETHER it maps.

Safe now (owner, 2026-10-28; evidence workspace ``docs/stx/MAPPING_FEASIBILITY.md`` §3-§6): NFL / NBA / NHL / NCAAF
winners; NFL / NBA / NCAAF spreads and totals; NFL team touchdown and field-goal totals; Serie A / ISL full-time
3-way; NFL / NBA player props. Everything else is emitted unmapped with a reason:

* ``family_held`` -- a known rules gap that needs STX's answer first (named per entry below).
* ``family_not_reviewed`` -- an Optic market exists but the STX rules text was not compared with it.
* ``no_optic_market`` -- the STX statistic has no Optic market at all.

Pricing caveat, not a mapping one: a 2-way winner settles a level game at HALF for both teams (``concepts__market-shape
.md:266-268``), which is neither the sportsbook void nor draw-no-bet. The row carries the flag ``tie_pays_half`` (in
``market_mapping.source_ids.tie_pays_half``, ``stx_attach.stx_source_ids``); until the pricer prices
P(win) + 0.5 * P(tie), the maker REFUSES every leg whose row carries it. Only the 2-way winner can settle at half:
totals and handicaps are half-number lines and cannot end level (``:346-347``).
"""

from __future__ import annotations

from dataclasses import dataclass

from mappers.exchanges.stx import StxMarket
from mappers.exchanges.stx_leagues import StxCompetition
from mappers.market_types import MarketType
from mappers.vocab.baseball_markets import BASEBALL_OPTIC_TABLE_TYPES
from mappers.vocab.basketball_markets import BASKETBALL_OPTIC_TABLE_TYPES
from mappers.vocab.football_markets import FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES
from mappers.vocab.hockey_markets import HOCKEY_OPTIC_TABLE_TYPES
from mappers.vocab.soccer_markets import SOCCER_OPTIC_TABLE_TYPES

TIE_PAYS_HALF = "tie_pays_half"

#: STX ``rules`` -> market family.
FAMILY_BY_RULES: dict[str, str] = {
    "home_winner": "winner",
    "away_winner": "winner",
    "spread": "spread",
    "over_under": "total",
    "participant_stat_line": "team_total",
    "player_stat_line": "player_prop",
    "event_stat_line": "event_stat",
    "event_stat_line_r1": "event_stat",
    "home_winner_regulation_3way": "3way",
    "away_winner_regulation_3way": "3way",
    "draw_regulation_3way": "3way",
    "home_winner_regulation_3way_r1": "3way_1h",
    "away_winner_regulation_3way_r1": "3way_1h",
    "draw_regulation_3way_r1": "3way_1h",
    "home_winner_regulation_2way": "regulation_winner",
    "away_winner_regulation_2way": "regulation_winner",
    "home_winner_regulation": "regulation_winner",
    "away_winner_regulation": "regulation_winner",
    "division_winner": "future",
    "conference_winner": "future",
    "superbowl_champion": "future",
    "race_winner": "excluded",
    "ad_hoc_rule": "excluded",
    "combo_rule": "excluded",
}
#: Never legs we price: season futures, fields, hand-made markets, combos themselves (``:538-552``).
EXCLUDED_FAMILIES = frozenset({"future", "excluded"})

#: STX sport -> {rules -> Optic market id}.
GAME_LINE_MARKETS: dict[str, dict[str, str]] = {
    "Football": {
        "home_winner": "moneyline",
        "away_winner": "moneyline",
        "spread": "point_spread",
        "over_under": "total_points",
    },
    "Basketball": {
        "home_winner": "moneyline",
        "away_winner": "moneyline",
        "spread": "point_spread",
        "over_under": "total_points",
    },
    "Hockey": {
        "home_winner": "moneyline",
        "away_winner": "moneyline",
        "spread": "puck_line",
        "over_under": "total_goals",
    },
    "Baseball": {
        "home_winner": "moneyline",
        "away_winner": "moneyline",
        "spread": "run_line",
        "over_under": "total_runs",
    },
    # Soccer moneyline is Optic's 1X2; stoppage time counts on both sides, extra time on neither.
    "Soccer": {
        "home_winner_regulation_3way": "moneyline",
        "away_winner_regulation_3way": "moneyline",
        "draw_regulation_3way": "moneyline",
        "home_winner_regulation_3way_r1": "1st_half_moneyline",
        "away_winner_regulation_3way_r1": "1st_half_moneyline",
        "draw_regulation_3way_r1": "1st_half_moneyline",
    },
}

#: STX sport -> {``participant_stat_line`` stat -> Optic team-total market id}.
TEAM_STAT_MARKETS: dict[str, dict[str, str]] = {
    "Football": {"TOUCHDOWNS": "team_total_touchdowns", "FIELD_GOALS": "team_total_field_goals"},
}

#: STX sport -> {``player_stat_line`` stat -> Optic player market id}. Read against ``stat_display_name``.
PLAYER_STAT_MARKETS: dict[str, dict[str, str]] = {
    "Football": {
        "TD_SCORE": "player_touchdowns",
        "PASS_YDS": "player_passing_yards",  # nosec B105 -- a stat code, not a password
        "PASS_TD": "player_passing_touchdowns",  # nosec B105
        "RECV_YDS": "player_receiving_yards",
        "REC": "player_receptions",
        "RUSH_YDS": "player_rushing_yards",
    },
    "Basketball": {
        "POINTS": "player_points",
        "ASSISTS": "player_assists",
        "REBOUNDS": "player_rebounds",
        "THREE_POINTS": "player_made_threes",
        "POINTS_REBOUNDS_ASSISTS": "player_points_+_rebounds_+_assists",
    },
    # GOAL_SO is Shots on Goal (stat_display_name), not shootout goals.
    "Hockey": {
        "GOALS": "player_goals",
        "ASSISTS": "player_assists",
        "POINTS": "player_points",
        "GOAL_SO": "player_shots_on_goal",
    },
    "Baseball": {"BASES": "player_bases", "HIT_RUN_RBI": "player_hits_+_runs_+_rbis"},
}

#: ``event_stat_line`` stats Optic has a market for (none mapped yet) and those it has none for.
EVENT_STAT_OPTIC: dict[str, str] = {
    "OVERTIME": "will_there_be_overtime",
    "RACE_TO_POINTS": "race_to_N_points",
    "FIRST_SCORE": "first_team_to_score",
    "LAST_SCORE": "last_team_to_score",
    "EXTRA_INNINGS": "will_there_be_extra_innings",
    "HITS": "total_hits",
    "RUN_SCORED": "1st_inning_to_score",
}
EVENT_STAT_NO_OPTIC = frozenset(
    {
        "FIRST_SCORE_TOUCHDOWN",
        "ANY_SCORE",
        "BOTH_SCORE",
        "FIRST_SCORE_WINS",
        "LAST_SCORE_WINS",
        "RUN_EVERY_INNING",
    }
)

#: STX competition -> the families that map today.
SAFE_NOW: dict[str, frozenset[str]] = {
    "NFL": frozenset({"winner", "spread", "total", "team_total", "player_prop"}),
    "NBA": frozenset({"winner", "spread", "total", "player_prop"}),
    "NCAAF": frozenset({"winner", "spread", "total"}),
    "NHL": frozenset({"winner"}),
    "Serie A": frozenset({"3way"}),
    "ISL": frozenset({"3way"}),
}
_NHL_SHOOTOUT = (
    "family_held: STX excludes shootout goals from NHL spreads and totals; Optic's {} grading is "
    "not verified (STX question Q6)"
)
#: (competition, family) -> why it waits.
FAMILY_HOLDS: dict[tuple[str, str], str] = {
    ("NCAAF", "player_prop"): (
        "family_held: NCAAF props use STX's short rules template, no DNP / postponement clause (STX question Q4)"
    ),
    ("NHL", "spread"): _NHL_SHOOTOUT.format("puck_line"),
    ("NHL", "total"): _NHL_SHOOTOUT.format("total_goals"),
}
#: Competitions whose 2-way winner is flagged ``tie_pays_half``; STX then pays half on both markets. Evidence per
#: mapped competition (rules templates: ``docs/stx/data_samples/2026-10-28-mapping-trial/description_templates.json``):
#: NFL "If the game ends in a tie, the market will resolve to $X for each team" (flag); NBA carries a second template
#: "In case of a draw we result into a push" (flag, conservative: an NBA game cannot end level, but the venue text
#: allows a push, so the maker refuses until STX answers); NCAAF "A college football game is played to a winner, so
#: this market cannot end in a tie" and NHL "including overtime and any shootout" state a winner (no flag).
TIE_PAYS_HALF_COMPETITIONS = frozenset({"NFL", "NBA"})

_OPTIC_TABLES: dict[str, dict[str, MarketType]] = {
    "Football": FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES,
    "Basketball": BASKETBALL_OPTIC_TABLE_TYPES,
    "Hockey": HOCKEY_OPTIC_TABLE_TYPES,
    "Soccer": SOCCER_OPTIC_TABLE_TYPES,
    "Baseball": BASEBALL_OPTIC_TABLE_TYPES,
}


@dataclass(frozen=True)
class StxMarketRule:
    """Where one STX market lands: its family, the Optic market id and mmmapper's canonical type for it."""

    family: str
    optic_market_id: str
    market_type: MarketType
    flags: tuple[str, ...] = ()


def _event_stat_reason(stat: str | None) -> str:
    if stat in EVENT_STAT_NO_OPTIC:
        return f"no_optic_market: event stat {stat}"
    if stat in EVENT_STAT_OPTIC:
        return f"family_not_reviewed: event stat {stat} (Optic {EVENT_STAT_OPTIC[stat]})"
    return f"unknown_stat: event stat {stat}"


def _optic_market_id(m: StxMarket, family: str) -> str | None:
    if family == "team_total":
        return TEAM_STAT_MARKETS.get(m.sport, {}).get(m.stat or "")
    if family == "player_prop":
        return PLAYER_STAT_MARKETS.get(m.sport, {}).get(m.stat or "")
    return GAME_LINE_MARKETS.get(m.sport, {}).get(m.rules)


def rule_for(m: StxMarket, comp: StxCompetition | None) -> StxMarketRule | str:
    """The mapping rule for ``m``, or the reason it is not mapped (``"<code>: <detail>"``)."""
    family = FAMILY_BY_RULES.get(m.rules)
    if family is None:
        return f"unknown_rules: {m.rules}"
    if family in EXCLUDED_FAMILIES:
        return f"excluded_family: {m.rules}"
    if comp is None:
        return f"unknown_competition: {m.competition} ({m.sport})"
    if comp.hold:
        return comp.hold
    if family == "event_stat":
        return _event_stat_reason(m.stat)
    if family not in SAFE_NOW.get(comp.name, frozenset()):
        return FAMILY_HOLDS.get((comp.name, family), f"family_not_reviewed: {comp.name} {family}")
    optic_id = _optic_market_id(m, family)
    if optic_id is None:
        return f"unknown_stat: {comp.name} {m.rules} {m.stat}"
    market_type = _OPTIC_TABLES.get(m.sport, {}).get(optic_id)
    if market_type is None:
        return f"optic_market_not_in_vocab: {m.sport} {optic_id}"
    flags = (TIE_PAYS_HALF,) if family == "winner" and comp.name in TIE_PAYS_HALF_COMPETITIONS else ()
    return StxMarketRule(family, optic_id, market_type, flags)
