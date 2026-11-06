"""Underdog UDX contracts and canonical rows, read from typed fields only.

A UDX catalogue row carries the contract sentence, an opaque ``ticker`` (the
RFQ key, never parsed), and ``external_ids.optic_odds`` naming the Optic
fixture and market. Everything the mapper needs comes from those:

* market and period: the Optic ``market_id`` (``2nd_quarter_point_spread``);
* teams, kickoff, YES side, line, player: the sentence;
* league membership: the Optic ``fixture_id`` belongs to the league's fixtures;
* a second kickoff: ``expires_at`` less three days (see ``expiry_kickoff``).

Integer lines are dropped: a UDX "at least 3" wins on exactly 3, and an Optic
integer line pushes.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from mappers.fight_props import (
    METHOD_DECISION,
    METHOD_KO_TKO_DQ,
    METHOD_SUBMISSION,
    canonicalize_fight_prop_key,
)
from mappers.exchanges.underdog_margin_race import RACE_RE, margin_rows, race_rows
from mappers.market_types import MarketType, Scope, Shape
from mappers.shared import TIE_SIDE, CanonicalRow, correct_score_line

_ET = ZoneInfo("America/New_York")

# Team sports write "between the X and the Y"; tennis and UFC drop the
# articles. Strict first, so "Brighton and Hove Albion" keeps its "and".
_BETWEEN_THE_RE = re.compile(
    r"between the (.+?) and the (.+?) originally scheduled", re.IGNORECASE,
)
_BETWEEN_RE = re.compile(
    r"between (.+?) and (.+?) originally scheduled", re.IGNORECASE,
)
# NHL names the pair as "<away> (away) at <home> (home)": after "... result of" on team
# contracts, right after "Will NHL" on game totals. The "of" form goes first: on a team
# contract the question head also precedes an "(away)", with the YES team's claim between.
_OF_AWAY_AT_HOME_RE = re.compile(
    r"\bof (?:the )?([^()]+?) \(away\) at (?:the )?([^()]+?) \(home\)", re.IGNORECASE,
)
_Q_AWAY_AT_HOME_RE = re.compile(
    r"^Will \S+ (?:the )?([^()]+?) \(away\) at (?:the )?([^()]+?) \(home\)", re.IGNORECASE,
)
# NBA props are not "Resolves Yes if": "<player> to record over 11.5 points in the
# <away> (away) vs the <home> (home) game."
_AWAY_VS_HOME_RE = re.compile(
    r"\bin the ([^()]+?) \(away\) vs the ([^()]+?) \(home\) game", re.IGNORECASE,
)
_PLAYER_RE = re.compile(
    r"(?:if (.+?) records above|^(.+?) to record over)", re.IGNORECASE,
)
# NCAAF drops "the" before the YES team; soccer and NFL "score more", others
# "win"/"beat". NHL asks a question: "Will NHL Minnesota Wild score above 1.5 more
# goals ...", "Will NHL Boston Bruins record above 0.5 goals ...".
_YES_TEAM_RE = re.compile(
    r"^(?:Resolves Yes if|Will \S+) (?:the )?(.+?) (?:wins?|beats?|scores?|records? above)\b",
    re.IGNORECASE,
)
# Win contracts also say "Will NHL Anaheim Ducks score more ...".
_WINNER_RE = re.compile(
    r"^(?:Resolves Yes if|Will \S+) (?:the )?(.+?) (?:wins?|score more) ", re.IGNORECASE,
)
_LINE_RE = re.compile(r"\b(?:at least|above|over) (\d+(?:\.\d+)?)\b", re.IGNORECASE)
# NBA period TIE legs name a team: "the X beat the Y by exactly 0 points".
_DRAW_RE = re.compile(
    r"\b(?:ends in a (?:draw|tie)|is level|score the same number of|by exactly 0 points)\b",
    re.IGNORECASE,
)
# Soccer exact score, winner first: "is exactly Atlas FC to win 4–2" / "is exactly 0–0
# draw" (Liga MX, Brazil) and "has a score of ACF Fiorentina to win 3–2" (Serie A).
_SCORE_RE = re.compile(
    r"\b(?:is exactly|has a score of) "
    r"(?:(?P<team>.+?) to win (?P<won>\d+)[–-](?P<lost>\d+)|(?P<level>\d+)[–-](?P<level2>\d+) draw)\b",
)
# Tennis exact score: "Resolves Yes if Ben Shelton wins the ATP Tour match between ... by a
# final set score of 2\u20131" (UDXATPSCORE / UDXATPCHLSCORE / UDXWTASCORE); winner's sets first.
_SET_SCORE_RE = re.compile(
    r"^Resolves Yes if (?P<team>.+?) wins .+ by a final set score of (?P<won>\d+)[\u2013-](?P<lost>\d+)\.$",
)
# "originally scheduled for 5:00pm ET on October 10, 2026." and the NHL form
# "originally scheduled for October 9, 2026 at 8:00pm ET?".
_TIME_THEN_DATE_RE = re.compile(
    r"scheduled for (\d{1,2}):(\d{2})([ap]m) ET on ([A-Z][a-z]+) (\d{1,2}), (\d{4})",
)
_DATE_THEN_TIME_RE = re.compile(
    r"scheduled for ([A-Z][a-z]+) (\d{1,2}), (\d{4}) at (\d{1,2}):(\d{2})([ap]m) ET",
)
_NORM_RE = re.compile(r"[^a-z0-9]+")

# UFC, MLB inning and overtime contracts: UDX's Optic market id names the
# market a contract is priced from, not one it equals (``UDXUFCEXACTTOTAL``
# "concludes during Round 2" carries ``to_start_round_2``, so round counts are
# not mapped). The outcome these rows settle on is read from the sentence, and
# must agree with that id.
_FIGHT_METHOD_RE = re.compile(
    r" by (KO, TKO or disqualification|submission|decision)\.$", re.IGNORECASE,
)
_FIGHT_METHODS = {
    "ko, tko or disqualification": METHOD_KO_TKO_DQ,
    "submission": METHOD_SUBMISSION,
    "decision": METHOD_DECISION,
}
_EITHER_FIGHTER_RE = re.compile(r"^Resolves Yes if either fighter wins ", re.IGNORECASE)
_WIN_IN_ROUND_RE = re.compile(r" during Round (\d)\.$")
_DISTANCE_RE = re.compile(r" concludes during all scheduled rounds\.$")
_OVERTIME_RE = re.compile(
    r"(?:records at least 1 kickoffs during overtime only|actually enters an overtime period\.$)",
)
_FIRST_INNINGS_RE = re.compile(r"during the first (\d) innings")
_INNINGS_OF = {
    MarketType.FIRST_FIVE_MONEYLINE_3WAY: 5,
    MarketType.FIRST_FIVE_POINT_SPREAD: 5,
    MarketType.FIRST_FIVE_TOTAL: 5,
    MarketType.FIRST_THREE_MONEYLINE_3WAY: 3,
}


@dataclass(frozen=True)
class UnderdogConfig:
    """League label plus the Optic-market-id crosswalk for that league's sport.

    ``player_id_markets``: market ids that map only through
    ``underdog_player_props`` (whole sentence + the venue's player id).
    """

    league: str
    market_types: dict[str, MarketType]
    player_id_markets: frozenset[str] = frozenset()

    def market_type(self, contract: UnderdogContract) -> MarketType | None:
        """Canonical type, or None when this Optic market id is not mapped."""
        return self.market_types.get(contract.market_id)


@dataclass(frozen=True)
class UnderdogContract:
    """One catalogue row, read from its typed fields and sentence."""

    ticker: str
    description: str
    market_id: str
    fixture_id: str
    start: datetime | None
    expiry_kickoff: datetime | None
    sides: tuple[str, str]
    line: float | None
    yes_team: str
    player: str | None
    is_draw: bool
    # Exact score (winner goals, loser goals); the winner is ``yes_team``, "" for a draw.
    score: tuple[int, int] | None = None
    rules: str = ""


def norm_name(value: str) -> str:
    """Lowercase name with punctuation collapsed, for fixture matching."""
    return _NORM_RE.sub(" ", value.lower()).strip()


def optic_block(row: Mapping) -> Mapping:
    """``external_ids.optic_odds`` of a catalogue row, or an empty mapping."""
    block = (row.get("external_ids") or {}).get("optic_odds") or {}
    return block if isinstance(block, Mapping) else {}


def sentence_teams(description: str) -> tuple[str, str] | None:
    """(away, home) display names from the venue sentence."""
    match = (
        _BETWEEN_THE_RE.search(description)
        or _BETWEEN_RE.search(description)
        or _OF_AWAY_AT_HOME_RE.search(description)
        or _Q_AWAY_AT_HOME_RE.search(description.strip())
        or _AWAY_VS_HOME_RE.search(description)
    )
    if match is None:
        return None
    return match.group(1).strip(), match.group(2).strip()


def sentence_yes_team(description: str) -> str:
    """Display name the sentence puts YES on, or "" when the head does not name one."""
    match = RACE_RE.search(description.strip()) or _YES_TEAM_RE.search(description.strip())
    return match.group(1).strip() if match else ""


def sentence_player(description: str) -> str | None:
    """Player display name from a prop sentence, when one is present."""
    match = _PLAYER_RE.search(description)
    if match is None:
        return None
    return (match.group(1) or match.group(2)).strip()


def sentence_winner(description: str) -> str | None:
    """Team a win contract resolves Yes on, read from its own sentence."""
    match = _WINNER_RE.search(description)
    if match is None:
        return None
    return match.group(1).strip()


def sentence_line(description: str) -> float | None:
    """The threshold a spread, total or prop sentence states, or None."""
    match = _LINE_RE.search(description)
    return float(match.group(1)) if match else None


def sentence_score(description: str) -> tuple[str, int, int] | None:
    """Exact-score sentence: (winner, winner goals, loser goals); winner "" for a draw."""
    sets = _SET_SCORE_RE.search(description.strip())
    if sets is not None:
        return sets.group("team"), int(sets.group("won")), int(sets.group("lost"))
    match = _SCORE_RE.search(description)
    if match is None:
        return None
    if match.group("team"):
        return match.group("team"), int(match.group("won")), int(match.group("lost"))
    return "", int(match.group("level")), int(match.group("level2"))


def sentence_start(description: str) -> datetime | None:
    """Kickoff the sentence states, in UTC."""
    match = _TIME_THEN_DATE_RE.search(description)
    if match is not None:
        hour, minute, meridiem, month, day, year = match.groups()
    else:
        match = _DATE_THEN_TIME_RE.search(description)
        if match is None:
            return None
        month, day, year, hour, minute, meridiem = match.groups()
    try:
        local = datetime.strptime(
            f"{month} {day} {year} {hour}:{minute}{meridiem}", "%B %d %Y %I:%M%p",
        ).replace(tzinfo=_ET)
    except ValueError:
        return None
    return local.astimezone(UTC)


# UDX sets a game market's ``expires_at`` three days after kickoff. Measured on
# the 2026-10-10 open catalogue against the Optic fixture each row names, it is
# exact where the sentence's "originally scheduled" time is stale: every MLB
# row (830 off by hours), NCAAF placeholders at 12:00am ET (TAM @ MIZ, SC @ FLA)
# and NFL games moved after listing. It is not exact for every product (NHL
# expires on another rule), so it only ever confirms the fixture UDX's own
# Optic id names.
_EXPIRY_AFTER_KICKOFF = timedelta(days=3)


def expiry_kickoff(row: Mapping) -> datetime | None:
    """Kickoff implied by the typed ``expires_at``, in UTC, or None when absent."""
    raw = str(row.get("expires_at") or "").strip()
    if not raw:
        return None
    try:
        expires = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if expires.tzinfo is None:
        return None
    return expires.astimezone(UTC) - _EXPIRY_AFTER_KICKOFF


def parse_contract(row: Mapping) -> UnderdogContract | None:
    """Typed view of one catalogue row, or None when a required field is missing.

    ``start`` is None for sentences that state no kickoff (NBA props); the pass
    then resolves the fixture from the venue's Optic fixture id, names permitting.
    """
    description = str(row.get("description") or "")
    ticker = str(row.get("ticker") or "")
    optic = optic_block(row)
    market_id = str(optic.get("market_id") or "").strip()
    fixture_id = str(optic.get("fixture_id") or "").strip()
    sides = sentence_teams(description)
    start = sentence_start(description)
    if not (ticker and market_id and fixture_id and sides):
        return None
    score = sentence_score(description)
    return UnderdogContract(
        ticker=ticker, description=description, market_id=market_id,
        fixture_id=fixture_id, start=start, expiry_kickoff=expiry_kickoff(row), sides=sides,
        line=sentence_line(description),
        yes_team=score[0] if score else (sentence_winner(description) or sentence_yes_team(description)),
        player=sentence_player(description),
        is_draw=bool(_DRAW_RE.search(description)),
        score=score[1:] if score else None,
        rules=str(row.get("rules") or ""),
    )


def needs_team(mt: MarketType) -> bool:
    """True when the contract's YES side is a team the sentence must name."""
    if mt.shape in {Shape.MONEYLINE, Shape.THREE_WAY, Shape.SPREAD}:
        return True
    if mt is MarketType.WINNING_MARGIN:
        return True
    return mt.shape is Shape.TOTAL and mt.scope is Scope.TEAM


def _integer_line(line: float | None) -> bool:
    return line is not None and float(line).is_integer()


_LINE_SHAPES = frozenset({Shape.SPREAD, Shape.TOTAL, Shape.OVER_UNDER})


def _row_factory(
    contract: UnderdogContract, mt: MarketType, *,
    home: str, away: str, start_date: str, league: str,
) -> Callable[..., CanonicalRow]:
    def row(side: str, *, entity: str | None, row_line: float | None,
            udx_side: str, grouping_key: str | None = None,
            market_type: MarketType | None = None) -> CanonicalRow:
        return CanonicalRow(
            league=league, start_date=start_date, home=home, away=away,
            market_type=(market_type or mt).value, entity=entity, line=row_line, side=side,
            grouping_key=grouping_key,
            underdog_ticker=contract.ticker, underdog_side=udx_side,
        )
    return row


def _rows_for_market_shape(
    row: Callable[..., CanonicalRow],
    mt: MarketType,
    *,
    home: str,
    away: str,
    team: str | None,
    line: float | None,
    player_name: str | None,
) -> list[CanonicalRow]:
    shape = mt.shape
    if shape is Shape.MONEYLINE and team in {home, away}:
        opp = away if team == home else home
        return [
            row(team, entity=None, row_line=None, udx_side="yes"),
            row(opp, entity=None, row_line=None, udx_side="no"),
        ]
    if shape is Shape.THREE_WAY and team in {home, away}:
        return [row(team, entity=None, row_line=None, udx_side="yes")]
    if shape is Shape.SPREAD and team in {home, away} and line is not None:
        opp = away if team == home else home
        return [
            row(team, entity=None, row_line=-line, udx_side="yes"),
            row(opp, entity=None, row_line=line, udx_side="no"),
        ]
    if shape is Shape.TOTAL and line is not None:
        entity = team if mt.scope is Scope.TEAM else None
        if mt.scope is Scope.TEAM and entity is None:
            return []
        return [
            row("over", entity=entity, row_line=line, udx_side="yes"),
            row("under", entity=entity, row_line=line, udx_side="no"),
        ]
    if shape is Shape.OVER_UNDER and player_name and line is not None:
        return [
            row("over", entity=player_name, row_line=line, udx_side="yes"),
            row("under", entity=player_name, row_line=line, udx_side="no"),
        ]
    if shape is Shape.YES_NO and player_name:
        return [
            row("yes", entity=player_name, row_line=None, udx_side="yes"),
            row("no", entity=player_name, row_line=None, udx_side="no"),
        ]
    return []


def _game_level_rows(
    row: Callable[..., CanonicalRow], mt: MarketType, *,
    is_draw: bool, player_name: str | None,
) -> list[CanonicalRow] | None:
    """3-way draw and game-scope yes/no rows, keyed the way Optic writes them.

    Optic's draw leg is side ``TIE_SIDE``; a game yes/no (BTTS, goes the
    distance) is side ``yes``/``no`` with no entity. None: not one of these.
    """
    if mt.shape is Shape.THREE_WAY and is_draw:
        return [row(TIE_SIDE, entity=None, row_line=None, udx_side="yes")]
    if mt.shape is Shape.YES_NO and mt.scope is Scope.GAME and not player_name:
        return [
            row("yes", entity=None, row_line=None, udx_side="yes"),
            row("no", entity=None, row_line=None, udx_side="no"),
        ]
    return None


def _fight_method_rows(
    row: Callable[..., CanonicalRow], description: str, team: str | None,
) -> list[CanonicalRow]:
    """Method of victory, keyed like Optic: affirmative leg, method in grouping_key.

    "<fighter> wins ... by decision" is the fighter's method of victory;
    "either fighter wins ... by decision" is the fight's method of finish.
    """
    match = _FIGHT_METHOD_RE.search(description)
    if match is None:
        return []
    method = _FIGHT_METHODS[match.group(1).casefold()]
    if _EITHER_FIGHTER_RE.search(description):
        return [row("yes", entity=None, row_line=None, udx_side="yes",
                    grouping_key=method, market_type=MarketType.METHOD_OF_FINISH)]
    if team is None:
        return []
    return [row("yes", entity=team, row_line=None, udx_side="yes", grouping_key=method)]


def _round_betting_rows(
    row: Callable[..., CanonicalRow], description: str, fighter: str,
) -> list[CanonicalRow]:
    """"<fighter> wins ... during Round N" as Optic's round_betting outcome key."""
    match = _WIN_IN_ROUND_RE.search(description)
    if match is None or not fighter or fighter.casefold() == "either fighter":
        return []
    key = canonicalize_fight_prop_key(f"{fighter} to win in Round {match.group(1)}")
    return [row("yes", entity=None, row_line=None, udx_side="yes", grouping_key=key)]


def _correct_score_rows(
    row: Callable[..., CanonicalRow], contract: UnderdogContract, team: str | None, *,
    home: str, away: str,
) -> list[CanonicalRow]:
    """Exact score keyed like Optic's: the winner (``TIE_SIDE`` level), winner-first line.

    Only YES maps: NO is every other scoreline, which no single Optic odd prices.
    """
    if contract.score is None:
        return []
    won, lost = contract.score
    line = correct_score_line(won, lost)
    if not contract.yes_team:
        return [row(TIE_SIDE, entity=None, row_line=line, udx_side="yes")] if won == lost else []
    if team in {home, away} and won > lost:
        return [row(team, entity=None, row_line=line, udx_side="yes")]
    return []


def _sentence_confirms(mt: MarketType, description: str) -> bool:
    """False when a priced-from Optic id is not the contract the sentence states."""
    if mt is MarketType.FIGHT_GOES_DISTANCE:
        return _DISTANCE_RE.search(description) is not None
    if mt is MarketType.WILL_THERE_BE_OVERTIME:
        return _OVERTIME_RE.search(description) is not None
    innings = _INNINGS_OF.get(mt)
    if innings is not None:
        match = _FIRST_INNINGS_RE.search(description)
        return match is not None and int(match.group(1)) == innings
    return True


def build_rows(
    contract: UnderdogContract,
    mt: MarketType,
    *,
    home: str, away: str, start_date: str, league: str,
    team: str | None,
    player_name: str | None = None,
) -> list[CanonicalRow]:
    """Both canonical sides of one contract, or [] when the line is integer.

    ``team`` is the fixture side the sentence puts YES on (None for contracts
    that name no team).
    """
    line = contract.line
    if mt.shape in _LINE_SHAPES and _integer_line(line):
        return []
    if not _sentence_confirms(mt, contract.description):
        return []
    row = _row_factory(
        contract, mt, home=home, away=away, start_date=start_date, league=league,
    )
    if mt.shape is Shape.CORRECT_SCORE:
        return _correct_score_rows(row, contract, team, home=home, away=away)
    if mt is MarketType.METHOD_OF_VICTORY:
        return _fight_method_rows(row, contract.description, team)
    if mt is MarketType.ROUND_BETTING:
        return _round_betting_rows(row, contract.description, contract.yes_team)
    if mt is MarketType.RACE_TO_POINTS:
        return race_rows(row, contract.market_id, contract.description, home=home, away=away, team=team)
    if mt is MarketType.WINNING_MARGIN:
        return margin_rows(row, contract.description, team)
    game_rows = _game_level_rows(row, mt, is_draw=contract.is_draw, player_name=player_name)
    if game_rows is not None:
        return game_rows
    return _rows_for_market_shape(
        row, mt, home=home, away=away, team=team, line=line, player_name=player_name,
    )
