"""Kalshi market type from Kalshi's own typed scope, per sport.

Every Kalshi event carries ``product_metadata.competition_scope`` ("Spread",
"Total Games", "Passing Yards", ...) and every series carries
``product_metadata.scope``. Those are Kalshi's statement of what a market
is, so the market type comes from them and never from the series ticker.
Nothing here is keyed by league: every league of a sport maps the same.

A scope that is not listed stays unmapped. Kalshi sometimes files a market
under a scope that does not tell it apart from another (KXWCADVANCE events
say "Game", like KXWCGAME); such a market is refused downstream, never
guessed (a 3-way group without a tie leg is dropped).

Built from the 2026-09-30 survey of every series the mapper priced: each
scope below named exactly one market type within its sport.
"""

from __future__ import annotations

import re

from mappers.market_types import MarketType
from mappers.sport import Sport

def _ordinal(n: int) -> str:
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n, 'th') }"


# Points targets Kalshi races to ("Race to 21 Points").
_RACE_TARGETS = range(1, 201)


# Scopes that mean the same market in every sport.
_ANY_SPORT: dict[str, MarketType] = {
    "Game": MarketType("moneyline"),
    "Spread": MarketType("point_spread"),
    "Point Total": MarketType("game_total"),
    "Team Total": MarketType("team_total"),
    "1st Half Winner": MarketType("1h_winner_3way"),
    "1st Half Spread": MarketType("1h_point_spread"),
    "1st Half Total": MarketType("1h_total"),
    "2nd Half Winner": MarketType("2h_winner_3way"),
    "2nd Half Spread": MarketType("2h_point_spread"),
    "2nd Half Total": MarketType("2h_total"),
    "1st Quarter Winner": MarketType("1q_winner_3way"),
    "1st Quarter Spread": MarketType("1q_point_spread"),
    "1st Quarter Total": MarketType("1q_total"),
    # Quarter winners map Yes only (the THREE_WAY shape): Optic has no
    # quarter double chance for the No side to land on.
    **{
        f"{_ordinal(n)} Quarter {name}": MarketType(f"{n}q_{kind}")
        for n in (2, 3, 4)
        for name, kind in (
            ("Winner", "winner_3way"),
            ("Spread", "point_spread"),
            ("Total", "total"),
        )
    },
    "1st Half Team Total": MarketType("1h_team_total"),
    "2nd Half Team Total": MarketType("2h_team_total"),
    "BTTS": MarketType("btts"),
    "1st Half BTTS": MarketType("1h_btts"),
    "To Advance": MarketType("to_advance"),
    # "Race to N Points": home, away, or "Neither team" (the third
    # outcome's strike id is neither side); N is the row's line.
    **{f"Race to {n} Points": MarketType("race_to_points") for n in _RACE_TARGETS},
}

_BY_SPORT: dict[Sport, dict[str, MarketType]] = {
    Sport.SOCCER: {
        # Soccer's game winner settles on 90 minutes with a draw outcome.
        "Game": MarketType("moneyline_3way"),
        "Regulation Time Moneyline": MarketType("moneyline_3way"),
        "Goalscorer": MarketType("player_goals"),
        "1st Goalscorer": MarketType("first_goal_scorer"),
        "Team Corners": MarketType("team_total_corners"),
        "Total Corners": MarketType("total_corners"),
        "2nd Half BTTS": MarketType("2h_btts"),
        # "No Goal" is the third outcome: its strike id is neither team.
        "First Team to Score": MarketType("first_team_to_score"),
        # Scoreline from custom_strike home/away score; Yes side only.
        "Correct Score": MarketType("correct_score"),
        "1st Half Correct Score": MarketType("1h_correct_score"),
    },
    Sport.TENNIS: {
        "Game Spread": MarketType("point_spread"),
        "Total Games": MarketType("match_total_games"),
        # Kalshi types the set per event; the series scope is "Set Winner".
        "Set 1 Winner": MarketType("1st_set_winner"),
        "Set 2 Winner": MarketType("2nd_set_winner"),
        # Set score from custom_strike "Set Score"; Yes side only.
        "Exact Match Score": MarketType("correct_score"),
    },
    Sport.ESPORTS: {
        "Total Maps": MarketType("total_maps"),
        # Kalshi types the map per event; the series scope is "Map Winner".
        **{
            f"Map {n} Winner": MarketType(f"map_{n}_winner")
            for n in range(1, 6)
        },
    },
    Sport.BASEBALL: {
        "First 3 Innings Winner": MarketType("f3_moneyline_3way"),
        "First 7 Innings Winner": MarketType("f7_moneyline_3way"),
        # 2nd-8th inning totals; the 1st is "1st Inning Total" above, and
        # the 9th stays out (the home half may not be played).
        **{
            f"{_ordinal(n)} Inning Total": MarketType(f"i{n}_total")
            for n in range(2, 9)
        },
        "First 5 Innings Winner": MarketType("f5_moneyline_3way"),
        "First 5 Innings Spread": MarketType("f5_point_spread"),
        "First 5 Innings Total": MarketType("f5_total"),
        "Hits": MarketType("player_hits"),
        "Home Runs": MarketType("player_home_runs"),
        "RBIs": MarketType("player_rbis"),
        "Hits + Runs + RBIs": MarketType("player_hits_runs_rbis"),
        "Total Bases": MarketType("player_bases"),
        "Stolen Bases": MarketType("player_stolen_bases"),
        "Strikeouts": MarketType("player_strikeouts"),
        "Outs Recorded": MarketType("player_outs"),
        "Hits Allowed": MarketType("player_hits_allowed"),
        "Earned Runs": MarketType("player_earned_runs"),
        # KXMLBWA; the pitcher's walks allowed, as Optic player_walks.
        "Walks": MarketType("player_walks_allowed"),
        "Extra Innings": MarketType("extra_innings"),
        # Any run in the first inning: Kalshi's strike is 1+ runs.
        "YRFI/NRFI": MarketType("first_inning_total"),
        "1st Inning Total": MarketType("first_inning_total"),
        # Kalshi types the inning per event; the series scope is
        # "Inning Winner".  The tie leg's strike id is neither team.
        **{
            f"{_ordinal(n)} Inning Winner": MarketType(f"i{n}_winner_3way")
            for n in range(1, 9)
        },
    },
    Sport.BASKETBALL: {
        "Player Points": MarketType("player_points"),
        "Player Rebounds": MarketType("player_rebounds"),
        "Player Assists": MarketType("player_assists"),
        "Player Threes": MarketType("player_threes"),
        "Player Steals": MarketType("player_steals"),
        "Player Blocks": MarketType("player_blocks"),
        # Optic player_points_+_rebounds_+_assists / player_steals_+_blocks.
        "Pts + Reb + Ast": MarketType("player_pts_reb_ast"),
        "Steals + Blocks": MarketType("player_steals_blocks"),
        "Double Double": MarketType("player_double_double"),
        "Triple Double": MarketType("player_triple_double"),
        # "(Protected)" series (KXNBAPTSPROT, ...): the base prop with insurance.
        **{
            f"{scope} (Protected)": MarketType(f"{mt}_insurance")
            for scope, mt in (
                ("Player Points", "player_points"),
                ("Player Rebounds", "player_rebounds"),
                ("Player Assists", "player_assists"),
                ("Player Threes", "player_threes"),
            )
        },
        "Overtime": MarketType("will_there_be_overtime"),
    },
    Sport.FOOTBALL: {
        "Anytime Touchdowns": MarketType("player_touchdowns"),
        "First TD": MarketType("first_touchdown_scorer"),
        "Passing Yards": MarketType("player_passing_yards"),
        # KXNFLPASSYDSPRECISE: same "N+" greater/floor_strike market, series scope "Stat Range".
        "Passing Yards Range": MarketType("player_passing_yards"),
        "Passing Touchdowns": MarketType("player_passing_touchdowns"),
        "Passing Attempts": MarketType("player_passing_attempts"),
        "Passing Completions": MarketType("player_passing_completions"),
        "Passing Interceptions": MarketType("player_interceptions"),
        "Rushing Yards": MarketType("player_rushing_yards"),
        "Rushing Attempts": MarketType("player_rushing_attempts"),
        "Longest Rush": MarketType("player_longest_rush"),
        "Receiving Yards": MarketType("player_receiving_yards"),
        "Receptions": MarketType("player_receptions"),
        "Longest Reception": MarketType("player_longest_reception"),
        "Team Touchdowns": MarketType("team_total_touchdowns"),
        # KXNCAAFTEAMRECTD; the team's receiving touchdowns.
        # KXNCAAFTEAMRECYDS; overtime counts on both sides.
        "Team Receiving Yards": MarketType("team_total_receiving_yards"),
        "Receiving Touchdowns": MarketType("team_total_receiving_touchdowns"),
        "Team Field Goals": MarketType("team_total_field_goals"),
        "Team Total Yards": MarketType("team_total_yards"),
        # Sacks the team records.  "Sacks" alone also names player series.
        "Team Sacks": MarketType("team_total_sacks"),
        "Rushing + Receiving Yards": MarketType("player_rushing_+_receiving_yards"),
        # "(Protected)" series (KXNFLPASSYDSPROT, ...): the base prop with insurance.
        **{
            f"{scope} (Protected)": MarketType(f"{mt}_insurance")
            for scope, mt in (
                ("Anytime Touchdowns", "player_touchdowns"),
                ("Passing Yards", "player_passing_yards"),
                ("Passing Touchdowns", "player_passing_touchdowns"),
                ("Receiving Yards", "player_receiving_yards"),
                ("Receptions", "player_receptions"),
                ("Rushing Yards", "player_rushing_yards"),
            )
        },
        "Overtime": MarketType("will_there_be_overtime"),
        # Yes per (first-half result, full-time result), overtime counts.
        "First Half / Fulltime": MarketType("halftime_fulltime"),
        "Safety": MarketType("will_there_be_a_safety"),
        # KXNFLFIRSTTD: one Yes per player; the game-level "No Touchdown" leg stays unmapped.
        "First TD": MarketType("first_touchdown_scorer"),
        # KXNFLWINMARGIN: Team by 1 to 6 / 7 to 14 / 15 or more, and tie.
        "Winning Margin": MarketType("winning_margin_5-way"),
        # Per-quarter "both teams score": Kalshi's BTTS in that quarter.
        **{
            f"BTTS in {_ordinal(n)} Quarter": MarketType(f"{n}q_both_teams_score")
            for n in (1, 2, 3, 4)
        },
        # "No team" is the third outcome: its strike id is neither team.
        "First Team to Score a TD": MarketType("first_team_touchdown"),
    },
    Sport.HOCKEY: {
        # Skater props: overtime counts, the shootout never does (as Optic).
        "Goalscorer": MarketType("player_goals"),
        "1st Goalscorer": MarketType("first_goal_scorer"),
        "Points": MarketType("player_points"),
        "Assists": MarketType("player_assists"),
        "Overtime": MarketType("will_there_be_overtime"),
        # Either team scores 1+ before 10:00 of the 1st period.
        "Goal in First 10 Minutes": MarketType("first_10_minutes_total"),
        # Winners map Yes only: Optic has no period double chance.
        **{
            f"{_ordinal(n)} Period {name}": MarketType(f"p{n}_{kind}")
            for n in (1, 2, 3)
            for name, kind in (
                ("Winner", "winner_3way"),
                ("Spread", "point_spread"),
                ("Total", "total"),
            )
        },
    },
    Sport.MMA: {
        "Method of Victory": MarketType("method_of_victory"),
        "Method of Finish": MarketType("method_of_finish"),
        "Round of Victory": MarketType("round_betting"),
        # "Fight ends before round N": the round comes from Kalshi's own
        # wording, and the parser picks to_start_round_N for that N.
        "Round of Finish": MarketType("to_start_round_2"),
        "Go the Distance": MarketType("fight_goes_distance"),
    },
}

_RACE_LINES: dict[str, float] = {
    f"Race to {n} Points": float(n) for n in _RACE_TARGETS
}

# Kalshi's series tags (the catalog's ``tags``) naming each sport.
_SPORT_TAGS: dict[str, Sport] = {
    "Baseball": Sport.BASEBALL,
    "Basketball": Sport.BASKETBALL,
    "Boxing": Sport.BOXING,
    "Cricket": Sport.CRICKET,
    "Esports": Sport.ESPORTS,
    "Football": Sport.FOOTBALL,
    "Hockey": Sport.HOCKEY,
    "MMA": Sport.MMA,
    "UFC": Sport.MMA,
    "Soccer": Sport.SOCCER,
    "Tennis": Sport.TENNIS,
}


def sport_for_tags(tags: list[str] | None) -> Sport | None:
    """The one sport a Kalshi series' tags name, else None."""
    sports = {_SPORT_TAGS[t] for t in (tags or []) if t in _SPORT_TAGS}
    return sports.pop() if len(sports) == 1 else None


def scope_types(sport: Sport) -> dict[str, MarketType]:
    """Every Kalshi scope this sport maps, with its market type."""
    return {**_ANY_SPORT, **_BY_SPORT.get(sport, {})}


def market_type_for_scope(sport: Sport, scope: str | None) -> MarketType | None:
    """Market type for one Kalshi scope in this sport, else None."""
    if not scope:
        return None
    return scope_types(sport).get(scope.strip())


# KXNFLTEAMFIRSTTD: one Yes per player, one event per team. The series scope is the generic
# "Touchdowns" (KXNFLFIRSTTD shares it) and the event scope names the team ("First Chicago TD"),
# so it cannot be a literal key above.
_TEAM_FIRST_TD_SERIES_SCOPE = "Touchdowns"
_TEAM_FIRST_TD_EVENT_SCOPE = re.compile(r"First .+ TD")

# Player yes/no types whose No leg is not a mapped contract: "not the first scorer" is every other
# outcome, and no single Optic odd prices it.
YES_ONLY_PLAYER_TYPES = frozenset(
    {
        MarketType("first_touchdown_scorer"),
        MarketType("team_first_touchdown_scorer"),
    }
)


def team_first_td_scope(sport: Sport, series_scope: str | None, competition_scope: str | None) -> bool:
    """True for a Kalshi team-first-TD event: football, series "Touchdowns", event "First <team> TD".

    The event-level test, shared by the fetch (which events to download) and the parser (which type a
    market gets), so the two cannot disagree. Callers try the literal scopes first, so "First Team to
    Score a TD" never lands here.
    """
    return (
        sport == Sport.FOOTBALL
        and (series_scope or "").strip() == _TEAM_FIRST_TD_SERIES_SCOPE
        and _TEAM_FIRST_TD_EVENT_SCOPE.fullmatch((competition_scope or "").strip()) is not None
    )


def team_first_td_type(
    sport: Sport,
    series_scope: str | None,
    competition_scope: str | None,
    custom_strike: object,
) -> MarketType | None:
    """team_first_touchdown_scorer for a Kalshi team-first-TD market, else None.

    Needs the event scope (team_first_td_scope) and the typed football_player and football_team ids
    in the market's custom_strike.
    """
    if not team_first_td_scope(sport, series_scope, competition_scope):
        return None
    if not (
        isinstance(custom_strike, dict) and custom_strike.get("football_player") and custom_strike.get("football_team")
    ):
        return None
    return MarketType("team_first_touchdown_scorer")


def scope_line(scope: str | None) -> float | None:
    """The line a scope itself states ("Race to 21 Points" -> 21), else None."""
    if not scope:
        return None
    return _RACE_LINES.get(scope.strip())
