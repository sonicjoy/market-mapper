"""Kalshi market parsing and canonical row building, from typed fields only.

Every fact about a Kalshi market comes from a field Kalshi types:

  market type  the event's product_metadata.competition_scope, else the
               series scope, looked up per sport (mappers.vocab.kalshi_scopes)
  game         the market's milestone (Optic fixture id, Sportradar id,
               structured-target ids), joined in mappers.pipeline
  side         custom_strike's team / competitor id against the milestone's
               home / away / tie ids
  line         strike_type + floor_strike
  method/round custom_strike "Method" / "Round"

Tickers are carried through as opaque ids (downstream trading places
orders by them) and are never read for meaning.
"""

import json
import re
import sys
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial

from pydantic import BaseModel

from mappers.fight_props import (
    canonicalize_fight_prop_key,
    kalshi_method_label_key,
    kalshi_vicround_other_key,
)
from mappers.exchanges.kalshi_regulation import regulation_basis, report_missing_rules
from mappers.market_types import MarketType, Scope, Shape
from mappers.shared import (
    TIE_SIDE,
    CanonicalRow,
    correct_score_line,
    normalize_player_name,
    opponent,
)
from mappers.sport import Sport
from mappers.vocab.kalshi_scopes import (
    YES_ONLY_PLAYER_TYPES,
    market_type_for_scope,
    scope_line,
    team_first_td_type,
)

# === League config ===


@dataclass(frozen=True)
class KalshiConfig:
    """A league's Kalshi coverage: its sport decides the scope vocabulary."""
    sport: Sport


# === Models ===

class Market(BaseModel):
    """A Kalshi market record as fetch.kalshi writes it."""
    model_config = {"extra": "allow"}

    event_ticker: str
    ticker: str
    title: str
    yes_sub_title: str = ""
    no_sub_title: str = ""
    expected_expiration_time: str = ""  # ISO 8601 UTC, ~game-end estimate
    rules_primary: str | None = None  # free-text settlement rules; basketball 2H/4Q basis
    # Kalshi's typed strike.  "greater" + floor_strike = "yes if the
    # value is more than floor_strike".  Absent on series with no numeric
    # strike.
    strike_type: str | None = None
    floor_strike: float | None = None
    cap_strike: float | None = None
    custom_strike: dict | None = None
    # Kalshi's sports milestone for this market's game, attached at fetch
    # (fetch.kalshi.compact_milestone): Optic fixture id, Sportradar id,
    # home/away/tie structured-target ids.  None on series without one
    # (futures, awards).
    milestone: dict | None = None
    # Side id the pipeline settled from Optic's source_ids when the strike
    # id is not one of the milestone's (a duplicate Kalshi entity).
    resolved_side_id: str | None = None
    # Kalshi's typed market kind: the event's
    # product_metadata.competition_scope ("Passing Yards") and the series'
    # product_metadata.scope ("Passing").
    competition_scope: str | None = None
    series_scope: str | None = None
    # The sport of the market's series (Kalshi's series tag).
    sport: str | None = None


# === Subtitle check ===

# Cosmetic phrasing variants Kalshi uses interchangeably between the
# yes_sub_title and no_sub_title of the same market.  We canonicalise
# both titles through this map before comparing, so a purely cosmetic
# difference doesn't fail the equality guard below.  Seen in the wild:
#     yes: "South Africa wins the 1H by more than 1.5 goals"
#     no:  "South Africa wins the 1H by over 1.5 goals"
#     yes: "Goal Difference: Spain wins the 1H by more than 1.5 goals"
#     no:  "Spain wins the 1H by more than 1.5 goals"
_SUBTITLE_SYNONYMS = {
    "by more than": "by over",
}
# Kalshi prefixes yes/no subtitles with cosmetic category labels
# ("Goal Difference: ", "Reg Time: ", "Goal Diff Reg Time: ", …).
# Strip any leading "Label: " segments before comparing propositions.
_SUBTITLE_LABEL_PREFIX = re.compile(r"^[^:]*:\s*")
# Football-only Kalshi display variants (verified 2026-08-25).  Other
# sports still require yes_sub_title == no_sub_title after normalize.
# GAME preseason: yes city vs no "CODE Nickname" (Tennessee / TEN Titans).
# SPREAD shared-city: yes keeps R/C/J/G, no drops it
#   ("Los Angeles C wins by over 20.5" / "Los Angeles wins by over 20.5").
_CODE_NICK = re.compile(r"^[A-Z]{2,3} \S")
_PROP_WORDS = re.compile(r"\b(wins|over|points|scored)\b", re.IGNORECASE)
_CITY_DISAMBIG = re.compile(r"^(.+?) [A-Z]( wins by .+)$")
# Football no-labels repeat the yes side and add the period the scope
# already names, and totals add "scored" (verified 2026-09-26):
#   1st Half Winner    "Philadelphia"       / "Philadelphia wins 1st Half"
#   1st Quarter Winner "Tie"                / "Tie 1st Quarter"
#   1st Half Spread    "PHI Eagles wins by over 7.5 points"
#                    / "PHI Eagles wins 1H by over 7.5 points"
#   1st Quarter Total  "Over 7.5 points"    / "Over 7.5 1Q points scored"
#   Point Total        "Over 59.5 points"   / "Over 59.5 points scored"
# The period words are only dropped when the scope is that period.
_PERIODS = {"1st Half": "1H", "1st Quarter": "1Q"}
_POINTS_SCORED = " points scored"


def _normalize_sub_title(s: str) -> str:
    for variant, canonical in _SUBTITLE_SYNONYMS.items():
        s = s.replace(variant, canonical)
    while _SUBTITLE_LABEL_PREFIX.match(s):
        s = _SUBTITLE_LABEL_PREFIX.sub("", s, count=1)
    return s


def _game_city_vs_code_nick(yes: str, no: str) -> bool:
    """True when yes is a city label and no is 'TEN Titans' style."""
    if _PROP_WORDS.search(yes) or _PROP_WORDS.search(no):
        return False
    if _CODE_NICK.match(yes):
        return False
    return bool(yes) and bool(_CODE_NICK.match(no))


def _spread_shared_city(yes: str, no: str) -> bool:
    """True when yes adds a one-letter city disambiguator that no omits."""
    match = _CITY_DISAMBIG.match(yes)
    return bool(match) and f"{match.group(1)}{match.group(2)}" == no


def _period(scope: str | None) -> tuple[str, str] | None:
    """(words, short form) of the period Kalshi's scope names, else None."""
    text = (scope or "").strip()
    return next(
        ((words, short) for words, short in _PERIODS.items()
         if text.startswith(words)),
        None,
    )


def _period_same_side(scope: str | None, yes: str, no: str) -> bool:
    """True when no is yes plus the scope's own period and/or 'scored'.

    A period word on a market of another period (or a full-game market)
    is a different bet and stays rejected.
    """
    if not yes:
        return False
    if no.endswith(_POINTS_SCORED):
        no = no[: -len(" scored")]
    period = _period(scope)
    if period is None:
        return no == yes
    words, short = period
    if no in (f"{yes} wins {words}", f"{yes} {words}"):
        return True
    return no.replace(f" {short} ", " ", 1) == yes


def _subtitles_compatible(market: "Market", yes: str, no: str) -> bool:
    """Whether eyeball can treat yes/no subtitles as the same proposition."""
    if yes == no:
        return True
    if market.sport != Sport.FOOTBALL:
        return False
    return (
        _game_city_vs_code_nick(yes, no)
        or _spread_shared_city(yes, no)
        or _period_same_side(market.competition_scope, yes, no)
    )


class SubtitleMismatchError(ValueError):
    """yes_sub_title and no_sub_title name different propositions."""

    def __init__(self, ticker: str, yes: str, no: str) -> None:
        self.ticker = ticker
        self.yes_sub_title = yes
        self.no_sub_title = no
        super().__init__(
            f"Kalshi {ticker}: yes_sub_title {yes!r} != "
            f"no_sub_title {no!r} — eyeball display assumes "
            f"they are equal")


def parse_market(line: str) -> Market:
    """Parse a Kalshi market from a JSONL line."""
    raw = json.loads(line)
    m = Market(**raw)
    yes = _normalize_sub_title(m.yes_sub_title)
    no = _normalize_sub_title(m.no_sub_title)
    if not _subtitles_compatible(m, yes, no):
        raise SubtitleMismatchError(m.ticker, m.yes_sub_title, m.no_sub_title)
    return m


def parse_market_line(line: str) -> Market | None:
    """Parse one Kalshi JSONL line, skipping a real subtitle divergence.

    Eyeball renders only yes_sub_title and assumes no_sub_title names the
    same bet.  Anything else is skipped so one bad contract does not zero
    the league.
    """
    try:
        return parse_market(line)
    except SubtitleMismatchError as exc:
        print(
            "ALERT: kalshi skip "
            f"{exc.ticker}: yes_sub_title {exc.yes_sub_title!r} != "
            f"no_sub_title {exc.no_sub_title!r}",
            file=sys.stderr,
        )
        return None


# === Parsed markets ===

# A side of the game, as the milestone ids say.  build_rows turns them
# into the fixture's canonical home / away.
HOME = "home"
AWAY = "away"


@dataclass(frozen=True)
class _ParsedBase:
    """Common fields shared by every parsed Kalshi market."""
    ticker: str
    scope: str
    market_type: MarketType


@dataclass(frozen=True)
class MoneylineMarket(_ParsedBase):
    """MONEYLINE shape: one side, no line."""
    side: str = HOME


@dataclass(frozen=True)
class SpreadMarket(_ParsedBase):
    """SPREAD shape: the side asked about wins by more than line."""
    side: str = HOME
    line: float = 0.0


@dataclass(frozen=True)
class TotalMarket(_ParsedBase):
    """TOTAL shape: yes = over line; side set for a TEAM-scope total."""
    line: float = 0.0
    side: str | None = None


@dataclass(frozen=True)
class ThreeWayMarket(_ParsedBase):
    """THREE_WAY shape: a side, or None for the third outcome."""
    side: str | None = None
    line: float | None = None        # race-to target, else None


@dataclass(frozen=True)
class OverUnderMarket(_ParsedBase):
    """OVER_UNDER shape: player + half-point line, yes = over."""
    player_name: str = ""            # raw name from title, before normalization
    line: float = 0.0


@dataclass(frozen=True)
class YesNoMarket(_ParsedBase):
    """Player YES_NO shape: player, no line.

    yes_only: the No leg is not a mapped contract (first touchdown scorer:
    "not first" is every other player and no single Optic odd prices it).
    """
    player_name: str = ""
    yes_only: bool = False


@dataclass(frozen=True)
class GameYesNoMarket(_ParsedBase):
    """Game-scoped YES_NO: no entity, no line — yes/no are the market's
    own sides.  grouping_key tells apart multi-outcome fight props
    (method of finish, round of victory) that share one market type.
    yes_only: the No leg is not a mapped contract (winning-margin buckets).
    """
    grouping_key: str | None = None
    yes_only: bool = False


@dataclass(frozen=True)
class TeamYesNoMarket(_ParsedBase):
    """Team-scoped YES_NO: one question per side, no line.

    grouping_key carries the method of a fighter×method leg.
    yes_only: the No leg is not a mapped contract (winning-margin buckets).
    """
    side: str = HOME
    grouping_key: str | None = None
    yes_only: bool = False


@dataclass(frozen=True)
class RoundStartMarket(_ParsedBase):
    """"Fight ends before round N": Optic to_start_round_N, sides swapped.

    Kalshi Yes (the fight ends in rounds 1..N-1, a corner stoppage between
    rounds counting as the round just ended) is exactly Optic's No (round
    N's bell never sounds).  market_type is already TO_START_ROUND_N.
    """


@dataclass(frozen=True)
class CorrectScoreMarket(_ParsedBase):
    """CORRECT_SCORE shape: the scoreline Kalshi's custom_strike states.

    side is the winner (None for a draw); the score is winner-first, as
    optic.build_rows encodes it.  Only the Yes side maps: Kalshi's No is
    every other scoreline, which no single Optic odd prices.
    """
    side: str | None = None
    winner_score: int = 0
    loser_score: int = 0


@dataclass(frozen=True)
class HalftimeFulltimeMarket(_ParsedBase):
    """HALFTIME_FULLTIME: one Yes per (first-half result, full-time result).

    Each result is a side, None for a tie.  Only the Yes side maps:
    Kalshi's No is the other eight outcomes, which no single Optic odd
    prices.
    """
    first_half: str | None = None
    full_time: str | None = None


ParsedMarket = (
    MoneylineMarket | SpreadMarket | TotalMarket
    | ThreeWayMarket | OverUnderMarket | YesNoMarket
    | GameYesNoMarket | TeamYesNoMarket | RoundStartMarket
    | CorrectScoreMarket | HalftimeFulltimeMarket
)

# Kalshi's round-of-finish wording.  The contract template allows any
# <time period> ("before 2:30 of Round 3" is a total-rounds line), so only
# this exact phrase maps; other wording is unmapped, never guessed.
_ENDS_BEFORE_ROUND_RE = re.compile(r"^Fight ends before round (?P<n>[2-5])$")
_TO_START_ROUND = {
    n: MarketType(f"to_start_round_{n}") for n in range(2, 6)
}
_TO_START_ROUND_TYPES = frozenset(_TO_START_ROUND.values())


def _ends_before_round(market: Market) -> int | None:
    match = _ENDS_BEFORE_ROUND_RE.match((market.yes_sub_title or "").strip())
    return int(match["n"]) if match else None


_HT_RESULT = re.compile(r"^(?:(?P<team>.+) wins 1st Half|(?P<tie>Tie in 1st Half))$")
_FT_RESULT = re.compile(r"^(?:(?P<team>.+) wins game|(?P<tie>Game ends in a tie))$")
_SUBTITLE_LINE = re.compile(r"\b(?:over|more than)\s+(\d+(?:\.\d+)?)", re.I)


def _htft_results(
    market: Market, name_sides: Mapping[str, str],
) -> tuple[str | None, str | None] | None:
    """(first-half, full-time) sides from custom_strike, None for a tie.

    Kalshi states each result as text ("Cleveland wins 1st Half"), not as
    a target id.  The name is resolved through this game's own winner
    markets (name_sides), whose strike ids tie each name to a side; None
    when either result names no side of the game.
    """
    cs = market.custom_strike
    if not isinstance(cs, dict):
        return None
    out: list[str | None] = []
    for key, pattern in (("1st Half Result", _HT_RESULT), ("Fulltime Result", _FT_RESULT)):
        match = pattern.match(str(cs.get(key) or "").strip())
        if match is None:
            return None
        if match["tie"]:
            out.append(None)
            continue
        side = name_sides.get(match["team"].strip().casefold())
        if side is None:
            return None
        out.append(side)
    return out[0], out[1]


# custom_strike keys naming a side of the game: soccer_team,
# tennis_competitor, esports_competitor, ufc_competitor, ...
_SIDE_STRIKE_SUFFIXES = ("_team", "_competitor", "_fighter")


def strike_team_id(market: Market) -> str | None:
    """The side (team/competitor) id Kalshi names in custom_strike, else None.

    custom_strike is {"soccer_team": id}, {"tennis_competitor": id},
    {"Method": "Decision", "ufc_competitor": id}, ... — exactly one side
    key, or it is not a side strike.  A player prop's {"*_player", "*_team"}
    names the player's team, which is not the outcome.
    """
    cs = market.custom_strike
    if not isinstance(cs, dict):
        return None
    ids = [
        v for k, v in cs.items()
        if k.endswith(_SIDE_STRIKE_SUFFIXES) and isinstance(v, str) and v
    ]
    return ids[0] if len(ids) == 1 else None


def _strike_field(market: Market, key: str) -> str | None:
    """A non-side custom_strike value (Method, Round), else None."""
    cs = market.custom_strike
    value = cs.get(key) if isinstance(cs, dict) else None
    return str(value) if value not in (None, "") else None


_NEITHER = "neither"


def strike_side(market: Market) -> str | None:
    """HOME / AWAY / None (the tie id) / _NEITHER, from the strike id.

    _NEITHER: the id is none of the milestone's (a three-way's "No Goal",
    "Neither team", an inning "Tie" with its own target, a fight's
    draw/no-contest).  Raises when there is no strike id or no milestone
    side ids: such a market has no typed side.
    """
    ms = market.milestone or {}
    tid = market.resolved_side_id or strike_team_id(market)
    if tid is None or not ms.get("home_id") or not ms.get("away_id"):
        raise ValueError(f"Kalshi {market.ticker}: no typed side")
    if tid == ms["home_id"]:
        return HOME
    if tid == ms["away_id"]:
        return AWAY
    if tid == ms.get("tie_id"):
        return None
    return _NEITHER


def _team_side(market: Market) -> str:
    """HOME or AWAY; raises for any other outcome."""
    side = strike_side(market)
    if side not in (HOME, AWAY):
        raise ValueError(f"Kalshi {market.ticker}: strike names no team")
    return side


def _score(value: object, ticker: str) -> int:
    text = str(value) if value is not None else ""
    if not text.isdigit():
        raise ValueError(f"Kalshi {ticker}: score {value!r} is not a count")
    return int(text)


def _parse_correct_score(
    market: Market, scope: str, mt: MarketType,
) -> CorrectScoreMarket:
    """Scoreline from custom_strike: soccer home/away score, tennis Set Score.

    Soccer names each score's team by id; those ids are matched to the
    milestone's (already oriented to Optic).  Tennis names the winner and
    the winner-first set score.
    """
    tk = market.ticker
    cs = market.custom_strike if isinstance(market.custom_strike, dict) else {}
    set_score = cs.get("Set Score")
    if set_score is not None:
        winner = _team_side(market)
        parts = str(set_score).split("-")
        if len(parts) != 2:
            raise ValueError(f"Kalshi {tk}: cannot read set score {set_score!r}")
        won, lost = _score(parts[0], tk), _score(parts[1], tk)
        if won <= lost:
            raise ValueError(f"Kalshi {tk}: winner's set score {set_score!r}")
        return CorrectScoreMarket(
            tk, scope, mt, side=winner, winner_score=won, loser_score=lost)
    ms = market.milestone or {}
    ids = (cs.get("home_team_id"), cs.get("away_team_id"))
    scores = (_score(cs.get("home_score"), tk), _score(cs.get("away_score"), tk))
    if ids == (ms.get("home_id"), ms.get("away_id")):
        home_score, away_score = scores
    elif ids == (ms.get("away_id"), ms.get("home_id")):
        away_score, home_score = scores
    else:
        raise ValueError(f"Kalshi {tk}: score team ids {ids} are not the game's")
    # The subtitle ("Stuttgart wins 6-3", "Draw 3-3") repeats the winner-first
    # score; a strike that disagrees with it is rejected, not mapped.
    stated = f"{max(scores)}-{min(scores)}"
    if stated not in market.yes_sub_title:
        raise ValueError(
            f"Kalshi {tk}: custom_strike score {stated} not in "
            f"yes_sub_title {market.yes_sub_title!r}")
    if home_score == away_score:
        return CorrectScoreMarket(
            tk, scope, mt, winner_score=home_score, loser_score=away_score)
    if home_score > away_score:
        return CorrectScoreMarket(
            tk, scope, mt, side=HOME,
            winner_score=home_score, loser_score=away_score)
    return CorrectScoreMarket(
        tk, scope, mt, side=AWAY,
        winner_score=away_score, loser_score=home_score)


def _typed_line(market: Market) -> float:
    """Kalshi's own threshold as a half-point line; raises when untyped."""
    if market.floor_strike is not None:
        if market.strike_type == "greater":
            return float(market.floor_strike)
        # "N+" on a whole-number count (corners, player stats) = over N-0.5.
        if market.strike_type == "greater_or_equal":
            return float(market.floor_strike) - 0.5
    raise ValueError(
        f"Kalshi {market.ticker}: no typed line "
        f"(strike_type={market.strike_type!r}, floor={market.floor_strike!r})")


def _require_subtitle_line(market: Market, line: float) -> None:
    """Raise when Kalshi's own yes text states a different threshold.

    A subtitle with no "over N" / "more than N" is not evidence either
    way and passes.
    """
    m = _SUBTITLE_LINE.search(market.yes_sub_title or "")
    if m is None:
        return
    stated = float(m.group(1))
    if abs(stated - line) > 1e-9:
        raise ValueError(
            f"Kalshi {market.ticker}: strike line {line} but "
            f"yes_sub_title says {market.yes_sub_title!r}")


def market_scope(market: Market) -> str:
    """The Kalshi scope that types this market (event scope, else series)."""
    return (market.competition_scope or market.series_scope or "").strip()


def scoped_market_type(market: Market, cfg: KalshiConfig) -> MarketType | None:
    """Market type from Kalshi's typed scope, else None.

    The event scope decides: an event the sport does not map ("Future"
    inside the KXUEL "Game" series) stays unmapped, and a finer event
    scope types a broader series ("Passing Yards" in "Passing").  Where
    both scopes map and disagree, the series wins: Kalshi files some
    advance events under "Game" inside a "To Advance" series.  With no
    event scope, the series scope decides.
    """
    series = market_type_for_scope(cfg.sport, market.series_scope)
    if not market.competition_scope:
        return _regulation_basis(cfg.sport, series, market)
    event = market_type_for_scope(cfg.sport, market.competition_scope)
    if event is None:
        return team_first_td_type(
            cfg.sport, market.series_scope, market.competition_scope, market.custom_strike)
    return _regulation_basis(cfg.sport, series or event, market)


def _regulation_basis(sport: Sport, mt: MarketType | None, market: Market) -> MarketType | None:
    return regulation_basis(sport, mt, market.rules_primary, market.ticker)


def _extract_player_name(title: str) -> str:
    """Player name from a Kalshi player market title.

    Pattern: "{Name}: {description}" → "{Name}"
    e.g. "Paolo Banchero: 30+ points" → "Paolo Banchero"
    """
    if ":" not in title:
        raise ValueError(f"Kalshi player title has no colon: {title!r}")
    return title[:title.index(":")].strip()


def _parse_fight_prop(
    market: Market, scope: str, mt: MarketType,
) -> ParsedMarket | None:
    """Method / round fight props; None when mt is not one of them."""
    tk = market.ticker
    if mt == MarketType.METHOD_OF_VICTORY:
        method = kalshi_method_label_key(_strike_field(market, "Method"))
        if method is None:
            raise ValueError(f"Kalshi {tk}: no typed Method")
        side = strike_side(market)
        if side in (HOME, AWAY):
            return TeamYesNoMarket(tk, scope, mt, side=side, grouping_key=method)
        # Draw / no contest: fight-scoped, no fighter entity.
        return GameYesNoMarket(tk, scope, mt, grouping_key=method)

    if mt == MarketType.METHOD_OF_FINISH:
        method = kalshi_method_label_key(_strike_field(market, "Method"))
        if method is None:
            raise ValueError(f"Kalshi {tk}: no typed Method")
        return GameYesNoMarket(tk, scope, mt, grouping_key=method)

    if mt == MarketType.ROUND_BETTING:
        rnd = _strike_field(market, "Round")
        if rnd is None:
            raise ValueError(f"Kalshi {tk}: no typed Round")
        side = strike_side(market)
        if side not in (HOME, AWAY):
            key = kalshi_vicround_other_key(rnd)
            if key is None:
                raise ValueError(f"Kalshi {tk}: Round {rnd!r} names no fighter")
            return GameYesNoMarket(tk, scope, mt, grouping_key=key)
        # Key text is Kalshi's own label (it merges with Optic's "X to win
        # in Round N"); the typed Round must agree with it.
        key = canonicalize_fight_prop_key(market.yes_sub_title or "")
        if not rnd.isdigit() or not key.endswith(f"_round_{int(rnd)}"):
            raise ValueError(
                f"Kalshi {tk}: Round {rnd!r} disagrees with "
                f"yes_sub_title {market.yes_sub_title!r}")
        return GameYesNoMarket(tk, scope, mt, grouping_key=key)
    return None


def _parse_margin(
    market: Market, scope: str, mt: MarketType,
) -> ParsedMarket | None:
    """Winning-margin buckets ("Seattle by 7 to 14", "tie"); else None.

    The bucket is Kalshi's own typed "Winning Margin" and is the grouping
    key. A team's bucket is a team YES_NO; the tie leg names no team. Only
    the Yes leg maps: "not this bucket" is not a contract we price.
    """
    if mt != MarketType.WINNING_MARGIN_5WAY:
        return None
    bucket = _strike_field(market, "Winning Margin")
    if bucket is None:
        raise ValueError(f"Kalshi {market.ticker}: no typed Winning Margin")
    key = "_".join(bucket.lower().split())
    if key == "tie":
        return GameYesNoMarket(
            market.ticker, scope, mt, grouping_key=key, yes_only=True)
    return TeamYesNoMarket(
        market.ticker, scope, mt, side=_team_side(market), grouping_key=key,
        yes_only=True)


def _parse_by_shape(
    market: Market, scope: str, mt: MarketType,
) -> ParsedMarket | None:
    """Moneyline, spread, total, three-way and correct-score markets."""
    tk = market.ticker
    if mt.shape == Shape.CORRECT_SCORE:
        return _parse_correct_score(market, scope, mt)

    if mt.shape == Shape.MONEYLINE:
        return MoneylineMarket(tk, scope, mt, side=_team_side(market))

    if mt.shape == Shape.SPREAD:
        line = _typed_line(market)
        _require_subtitle_line(market, line)
        return SpreadMarket(tk, scope, mt, side=_team_side(market), line=line)

    if mt.shape == Shape.TOTAL:
        line = _typed_line(market)
        _require_subtitle_line(market, line)
        if mt.scope == Scope.TEAM:
            return TotalMarket(tk, scope, mt, line=line, side=_team_side(market))
        return TotalMarket(tk, scope, mt, line=line)

    if mt.shape == Shape.THREE_WAY:
        side = strike_side(market)
        return ThreeWayMarket(
            tk, scope, mt,
            side=None if side == _NEITHER else side,
            line=scope_line(scope))
    return None


def _parse_yes_no(market: Market, scope: str, mt: MarketType) -> ParsedMarket:
    """Player, team and game props that are a yes/no or over/under on a count."""
    tk = market.ticker
    if mt.scope == Scope.PLAYER and mt.shape == Shape.OVER_UNDER:
        return OverUnderMarket(
            tk, scope, mt,
            player_name=_extract_player_name(market.title),
            line=_typed_line(market))

    if mt.scope == Scope.PLAYER and mt.shape == Shape.YES_NO:
        return YesNoMarket(
            tk, scope, mt, player_name=_extract_player_name(market.title),
            yes_only=mt in YES_ONLY_PLAYER_TYPES)

    fight = _parse_fight_prop(market, scope, mt)
    if fight is not None:
        return fight

    if mt.scope == Scope.TEAM and mt.shape == Shape.YES_NO:
        return TeamYesNoMarket(tk, scope, mt, side=_team_side(market))

    if mt.scope == Scope.GAME and mt.shape == Shape.YES_NO:
        # A count strike other than "1+" ("2+ overtime periods") asks a
        # different question than the yes/no market.
        if market.floor_strike is not None:
            line = _typed_line(market)
            if line != 0.5:
                raise ValueError(
                    f"Kalshi {tk}: yes/no type {mt.value} with strike line {line}")
        return GameYesNoMarket(tk, scope, mt)

    raise ValueError(
        f"Kalshi {tk}: unexpected (scope={mt.scope.value}, shape={mt.shape.value})")


def parse_typed_market(
    market: Market,
    cfg: KalshiConfig,
    name_sides: Mapping[str, str] | None = None,
) -> ParsedMarket | None:
    """Parse a Kalshi market from its typed fields.

    The market's milestone must already be oriented to the Optic fixture
    (home_id = Optic home).  name_sides maps a casefolded Kalshi team name
    to its side for this game; only halftime / full time needs it.

    Returns None for a scope the sport does not map.  Raises ValueError
    when a mapped market lacks the typed field its shape needs; such a
    market is skipped, never guessed.
    """
    mt = scoped_market_type(market, cfg)
    if mt is None:
        return None
    tk = market.ticker
    scope = market_scope(market)

    # Round of finish: the scope names the to_start_round family (any N);
    # the round comes from Kalshi's own wording.
    if mt in _TO_START_ROUND_TYPES:
        n = _ends_before_round(market)
        if n is None:
            raise ValueError(
                f"Kalshi {tk}: {market.yes_sub_title!r} is not "
                f"'Fight ends before round N'")
        return RoundStartMarket(tk, scope, _TO_START_ROUND[n])

    if mt == MarketType.HALFTIME_FULLTIME:
        results = _htft_results(market, name_sides or {})
        if results is None:
            return None
        return HalftimeFulltimeMarket(
            tk, scope, mt, first_half=results[0], full_time=results[1])

    shaped = _parse_by_shape(market, scope, mt)
    if shaped is not None:
        return shaped

    fight = _parse_fight_prop(market, scope, mt) or _parse_margin(market, scope, mt)
    if fight is not None:
        return fight
    return _parse_yes_no(market, scope, mt)


# === Canonical row building ===

def _drop_incomplete_three_ways(
    rows: list[CanonicalRow],
    three_way_sides: dict[tuple[str, float | None], list[str]],
    *,
    home: str,
    away: str,
    start_date: str,
) -> list[CanonicalRow]:
    """Drop a 3-way group that is not exactly {home, away, tie}.

    A missing third leg, or a scope that does not tell two markets apart
    (KXWCADVANCE files "Game" like KXWCGAME), leaves that group unmapped;
    the game's other markets remain.
    """
    expected = sorted([home, away, TIE_SIDE])
    dropped = {
        key for key, sides in three_way_sides.items()
        if sorted(sides) != expected
    }
    for mt, line in sorted(dropped, key=str):
        sides = three_way_sides[(mt, line)]
        print(
            f"ALERT: kalshi drop incomplete {mt} line={line} "
            f"for {start_date} {away}@{home}: "
            f"sides {sides}, expected {expected}",
            file=sys.stderr,
        )
    if not dropped:
        return rows
    return [row for row in rows if (row.market_type, row.line) not in dropped]


def _player_entity(
    market: Market,
    name: str,
    optic_player_names: Mapping[str, str] | None,
    market_type: MarketType | None = None,
) -> str:
    """Player entity: Optic's name for this ticker, else Kalshi's label.

    Optic labels team_first_touchdown_scorer "<team> :: <player>" and keys
    the player alone (optic.py), so the team prefix is dropped for that
    market only; other markets keep Optic's selection as is.
    """
    optic_name = (optic_player_names or {}).get(market.ticker)
    if name and optic_name:
        if market_type == MarketType.TEAM_FIRST_TOUCHDOWN_SCORER:
            optic_name = optic_name.rsplit(" :: ", 1)[-1]
        return normalize_player_name(optic_name)
    return normalize_player_name(name)


def _strike_player_id(market: Market) -> str | None:
    """The player id Kalshi names in custom_strike ({"soccer_player": id})."""
    cs = market.custom_strike
    if not isinstance(cs, dict):
        return None
    ids = [
        v for k, v in cs.items()
        if k.endswith("_player") and isinstance(v, str) and v
    ]
    return ids[0] if len(ids) == 1 else None


def _with_sibling_player_names(
    markets: list[Market],
    optic_player_names: Mapping[str, str] | None,
) -> dict[str, str]:
    """optic_player_names, extended to unstamped tickers of a named player.

    Optic stamps a Kalshi ticker on one line only: the goalscorer 1+
    ticker sits on its player_goals 0.5 row, while the 1.5 / 2.5 rows
    carry no Kalshi id.  Kalshi's 2+ / 3+ markets name the same player
    by the same typed custom_strike id, so they take the Optic name of
    that player's stamped ticker.  A player id whose stamped tickers
    carry two different Optic names lends neither.
    """
    out = dict(optic_player_names or {})
    by_player: dict[str, set[str]] = defaultdict(set)
    for market in markets:
        pid = _strike_player_id(market)
        if pid and market.ticker in out:
            by_player[pid].add(out[market.ticker])
    for market in markets:
        names = by_player.get(_strike_player_id(market) or "")
        if market.ticker not in out and names and len(names) == 1:
            out[market.ticker] = next(iter(names))
    return out


def _name_sides(markets: list[Market], cfg: KalshiConfig) -> dict[str, str]:
    """Casefolded Kalshi team name -> side, from this game's winner markets.

    A game-winner market names its team in yes_sub_title and its id in the
    strike, so each one ties a name to a side with typed evidence.
    """
    names: dict[str, str] = {}
    for market in markets:
        if scoped_market_type(market, cfg) not in (
                MarketType.MONEYLINE, MarketType.MONEYLINE_3WAY):
            continue
        try:
            side = strike_side(market)
        except ValueError:
            continue
        name = (market.yes_sub_title or "").strip().casefold()
        if side in (HOME, AWAY) and name:
            names[name] = side
    return names


def build_rows(
    start_date: str,
    home: str,
    away: str,
    markets: list[Market],
    cfg: KalshiConfig,
    *,
    league: str,
    optic_player_names: Mapping[str, str] | None = None,
) -> list[CanonicalRow]:
    """Build flat canonical rows from one game's Kalshi markets.

    home / away are the Optic fixture's canonicals; every market's
    milestone is already oriented to them.

    optic_player_names maps a ticker to the Optic selection whose
    source_ids name it.  A player row takes its entity from that name,
    so Kalshi's label ("CHI Bears D/ST") lands on Optic's entity
    ("Chicago Bears D/ST") by the ticker join, not by name matching.
    A ticker Optic does not stamp borrows the name of a stamped ticker
    with the same typed player id (_with_sibling_player_names).

    Row counts per shape:
      MONEYLINE    — 1 row:  side=team, kalshi_side="yes"
      SPREAD       — 2 rows: side=team at -line yes, side=opponent at +line no
      TOTAL        — 2 rows: side="over" yes, side="under" no
      THREE_WAY    — 1 row:  side=team or TIE_SIDE, kalshi_side="yes"
      OVER_UNDER   — 2 rows: side="over" yes, side="under" no
      YES_NO       — 2 rows: side="yes" yes, side="no" no
    """
    canon = {HOME: home, AWAY: away}

    def _side(side: str | None) -> str:
        return TIE_SIDE if side is None else canon[side]

    rows: list[CanonicalRow] = []
    three_way_sides: dict[tuple[str, float | None], list[str]] = defaultdict(list)
    name_sides = _name_sides(markets, cfg)
    optic_player_names = _with_sibling_player_names(markets, optic_player_names)
    for market in markets:
        # One unparseable market must not abort the game or the pipeline.
        try:
            parsed = parse_typed_market(market, cfg, name_sides)
        except ValueError as exc:
            print(f"  kalshi: skipping {market.ticker!r}: {exc}", file=sys.stderr)
            continue
        if parsed is None:
            continue

        mt = parsed.market_type
        row = partial(CanonicalRow,
            league=league,
            start_date=start_date, home=home, away=away,
            market_type=mt.value,
            kalshi_ticker=parsed.ticker,
            kalshi_scope=parsed.scope or None,
            kalshi_title=market.title,
            kalshi_yes_sub_title=market.yes_sub_title or None)

        if isinstance(parsed, MoneylineMarket):
            rows.append(row(entity=None, side=canon[parsed.side], kalshi_side="yes"))

        elif isinstance(parsed, SpreadMarket):
            # The asked-about team is favored → negative line.
            team = canon[parsed.side]
            rows.append(row(entity=None, line=-parsed.line,
                            side=team, kalshi_side="yes"))
            rows.append(row(entity=None, line=parsed.line,
                            side=opponent(team, home, away), kalshi_side="no"))

        elif isinstance(parsed, TotalMarket):
            # A "greater" strike is Kalshi saying yes = over.
            team = canon[parsed.side] if parsed.side is not None else None
            rows.append(row(entity=team, line=parsed.line,
                            side="over", kalshi_side="yes"))
            rows.append(row(entity=team, line=parsed.line,
                            side="under", kalshi_side="no"))

        elif isinstance(parsed, ThreeWayMarket):
            side = _side(parsed.side)
            three_way_sides[(mt.value, parsed.line)].append(side)
            rows.append(row(entity=None, line=parsed.line,
                            side=side, kalshi_side="yes"))

        elif isinstance(parsed, OverUnderMarket):
            entity = _player_entity(market, parsed.player_name, optic_player_names)
            rows.append(row(entity=entity, line=parsed.line,
                            side="over", kalshi_side="yes"))
            rows.append(row(entity=entity, line=parsed.line,
                            side="under", kalshi_side="no"))

        elif isinstance(parsed, YesNoMarket):
            entity = _player_entity(market, parsed.player_name, optic_player_names, mt)
            rows.append(row(entity=entity, side="yes", kalshi_side="yes"))
            if not parsed.yes_only:
                rows.append(row(entity=entity, side="no", kalshi_side="no"))

        elif isinstance(parsed, CorrectScoreMarket):
            rows.append(row(
                entity=None,
                line=correct_score_line(parsed.winner_score, parsed.loser_score),
                side=_side(parsed.side),
                kalshi_side="yes",
            ))

        elif isinstance(parsed, HalftimeFulltimeMarket):
            rows.append(row(
                entity=None, side="yes", kalshi_side="yes",
                grouping_key="|".join(
                    _side(s) for s in (parsed.first_half, parsed.full_time))))

        elif isinstance(parsed, RoundStartMarket):
            rows.append(row(entity=None, side="no", kalshi_side="yes"))
            rows.append(row(entity=None, side="yes", kalshi_side="no"))

        elif isinstance(parsed, GameYesNoMarket):
            rows.append(row(entity=None, side="yes", kalshi_side="yes",
                            grouping_key=parsed.grouping_key))
            if not parsed.yes_only:
                rows.append(row(entity=None, side="no", kalshi_side="no",
                                grouping_key=parsed.grouping_key))

        elif isinstance(parsed, TeamYesNoMarket):
            # Optic quotes only the affirmative, so the "no" side has no
            # Optic counterpart and stays a Kalshi-only novel row.
            team = canon[parsed.side]
            rows.append(row(entity=team, side="yes", kalshi_side="yes",
                            grouping_key=parsed.grouping_key))
            if not parsed.yes_only:
                rows.append(row(entity=team, side="no", kalshi_side="no",
                                grouping_key=parsed.grouping_key))

    report_missing_rules()
    return _drop_incomplete_three_ways(
        rows, three_way_sides, home=home, away=away, start_date=start_date,
    )
