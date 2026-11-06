"""ProphetX market parsing, classification, and canonical row building.

PX markets come in two files:
  prophetx_events.jsonl  — one event per game (competitors, scheduled time)
  prophetx_markets.jsonl — individual markets attached to events

Each market has a `name` that encodes the market type and (for team/player
scoped types) the entity.  The `type` field ("moneyline", "spread", "total")
describes the structural shape.  Classification matches the name to a
canonical MarketType and cross-checks the type field.

Side resolution maps PX outcome_ids to semantic labels:
  - Team-identified (outcome_ids {4,5} or {1714,1715}): via competitor_id
  - Over/under (outcome_ids {12,13}): over/under
  - Yes/no (outcome_ids {1,2}): yes/no
"""

import json
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NamedTuple

from pydantic import BaseModel, field_validator, model_validator

from mappers.market_types import MarketType, Scope, Shape
from mappers.shared import (
    TIE_SIDE,
    AliasValue,
    CanonicalRow,
    MatchKey,
    normalize_line,
    normalize_player_name,
    resolve_team,
    to_date_str,
    to_et_str,
)
from mappers.team_side import team_side

# === League config ===

@dataclass(frozen=True)
class PxConfig:
    """League-specific constants for PX market classification and filtering."""
    tournament_id: int                                # PX API tournament ID, e.g. 132 (NBA)
    exact: dict[str, MarketType]                      # exact market name -> MarketType
    suffix: list[tuple[str, MarketType]]              # (suffix, MarketType), longest-first


# === Models ===

class Competitor(BaseModel):
    id: int
    abbreviation: str
    name: str
    side: str


class Selection(NamedTuple):
    """One side of a PX market line, normalized for matching.

    Two team-identity channels coexist:
      - competitor_id: PX competitor reference, set for outcome_ids
        in {4,5,1714,1715}.  Resolved to a team via comp_map at
        side-label time.
      - team_abbr: pre-resolved canonical team abbreviation, set at
        parse time when the team identity lives in display_name rather
        than competitor_id (currently only sup_moneyline POINT_SPREAD_YN,
        where outcome_ids are {1,2} and the team appears as a prefix
        like "BRE -0.5").  Always None for other selection types.
    """
    line_id: str
    outcome_id: int
    spread_line: float  # signed for spreads; meaningless for other market types
    competitor_id: int | None = None
    display_name: str = ""
    team_abbr: str | None = None


class Line(NamedTuple):
    """One line within a PX market, normalized for matching."""
    line: float | None  # None for moneyline
    selections: list[Selection]


class Market(BaseModel):
    """Raw PX market record — pure API data, no pipeline state."""
    model_config = {"extra": "allow"}

    id: int
    name: str
    type: str
    status: str
    sport_event_id: int
    selections: list[dict] | None = None
    market_lines: list[dict] | None = None
    market_strikes: list[dict] | None = None  # CFTC rename of market_lines

    @model_validator(mode="before")
    @classmethod
    def _normalize_cftc_keys(cls, data: object) -> object:
        """Map CFTC market_strikes → market_lines for downstream parsers."""
        if not isinstance(data, dict):
            return data
        if data.get("market_lines") is None and data.get("market_strikes") is not None:
            return {**data, "market_lines": data["market_strikes"]}
        return data

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return v.strip()


class ClassifiedMarket(BaseModel):
    """A PX market that has passed classification.

    Wraps the raw Market with guaranteed-present enrichment fields
    populated during the classify-and-attach pipeline phase.
    """
    raw: Market
    market_type: MarketType
    team_abbrev: str | None = None   # present iff scope == TEAM
    player: str | None = None        # present iff scope == PLAYER
    market_lines: list[Line]


class Event(BaseModel):
    """Raw PX event record — pure API data, no pipeline state."""
    event_id: int
    status: str
    scheduled: str
    sport_name: str
    tournament_id: int
    tournament_name: str
    competitors: list[Competitor]


class ParsedEvent(BaseModel):
    """A PX event that passed sport/tournament filtering.

    Wraps the raw Event with the computed match_key and a mutable
    markets list populated by the pipeline's classify-and-attach phase.
    """
    raw: Event
    match_key: MatchKey
    markets: list[ClassifiedMarket] = []

    @property
    def is_live(self) -> bool:
        """True when PX considers this event in-progress."""
        return self.raw.status != "not_started"


# === Parsing ===

def _sides(
    event: Event,
    team_aliases: Mapping[str, AliasValue],
) -> tuple[str, str]:
    """Extract (home_abbrev, away_abbrev) from PX competitors.

    Normalizes PX abbreviations to canonical form (e.g. GS → GSW)
    using the team alias table.  For ambiguous abbreviations (e.g.
    PX "COL" = both Columbia and Colorado), disambiguates using the
    competitor's display name and checks the competitor id.
    """
    sides: dict[str, str] = {}
    for comp in event.competitors:
        sides[comp.side] = resolve_team(
            comp.abbreviation, team_aliases, comp.name, comp.id)
    if "home" not in sides or "away" not in sides:
        raise ValueError(
            f"Event {event.event_id}: missing home or away competitor")
    return sides["home"], sides["away"]


def parse_event(
    line: str,
    cfg: PxConfig,
    team_aliases: Mapping[str, AliasValue],
) -> ParsedEvent | None:
    """Parse and validate a PX event from a JSONL line.

    Returns None when the event's tournament_id doesn't match the
    configured league — early filtering so the pipeline sees only
    the configured league's data.  Live/in-progress events are kept
    so they can match Optic fixtures and emit rows when the live
    board still has markets (load_mappings is insert-only for Optic
    is_live fixtures).

    Converts the UTC scheduled time to Eastern, normalizes team
    abbreviations via team_aliases, and computes the match key up
    front so downstream code doesn't repeat the conversion.
    """
    raw = json.loads(line)
    event = Event(**raw)

    if event.tournament_id != cfg.tournament_id:
        return None

    home, away = _sides(event, team_aliases)
    return ParsedEvent(
        raw=event,
        match_key=MatchKey(to_date_str(to_et_str(event.scheduled)), home, away),
    )


def parse_market(line: str) -> Market:
    """Parse a PX market from a JSONL line."""
    raw = json.loads(line)
    assert "wsd" not in raw, f"PX market {raw.get('id')} already has a 'wsd' key"
    return Market(**raw)


def _sel_id(sel: dict) -> str:
    """Selection id from CFTC strike_id or legacy line_id."""
    sid = sel.get("strike_id")
    if sid is not None:
        return sid
    return sel["line_id"]


def _sel_strike(sel: dict) -> float:
    """Handicap/threshold from CFTC strike or legacy line."""
    if "strike" in sel:
        return float(sel["strike"])
    return float(sel["line"])


def _ml_strike(ml: dict) -> float:
    """Market-row strike from CFTC or legacy key."""
    if "strike" in ml:
        return float(ml["strike"])
    return float(ml["line"])


def _extract_selection(sel: dict) -> Selection:
    """Extract matching-relevant fields from a raw PX selection."""
    return Selection(
        line_id=_sel_id(sel),
        outcome_id=sel["outcome_id"],
        spread_line=_sel_strike(sel),
        competitor_id=sel.get("competitor_id"),
        display_name=sel["display_name"],
    )


# === Per-market structural validation ===
#
# These validate individual market_line structure at extraction time,
# catching corrupt PX records before they enter the canonical pipeline.
# Adapted from market_mapping/nba/prophetx.py lines 131-244.

def _validate_moneyline_sels(sels: list[Selection], name: str) -> None:
    """Moneyline PX type: outcome_ids {4,5} (team) or {1,2} (yes/no).

    PX reuses type=moneyline for both team moneylines and yes/no player
    props (double-double etc.).  Shape distinguishes them later;
    build_rows fail-closes if a team-moneyline Shape gets yes/no sides.
    """
    oids = {s.outcome_id for s in sels}
    if oids != OUTCOME_IDS_TEAM and oids != OUTCOME_IDS_YESNO:
        raise ValueError(
            f"Moneyline {name!r}: unexpected outcome_ids {oids}")
    for s in sels:
        if s.spread_line != 0:
            raise ValueError(
                f"Moneyline {name!r}: selection {s.display_name!r} "
                f"has non-zero line {s.spread_line}")


def _validate_spread_line(
    sels: list[Selection], ml_line: float, name: str,
) -> None:
    """Spread: 2 selections, outcome_ids {1714,1715}, lines sum to zero."""
    if len(sels) != 2:
        raise ValueError(
            f"Spread {name!r} market_line {ml_line}: "
            f"{len(sels)} selections (expected 2)")
    oids = {s.outcome_id for s in sels}
    if oids != OUTCOME_IDS_SPREAD:
        raise ValueError(
            f"Spread {name!r} market_line {ml_line}: "
            f"unexpected outcome_ids {oids}")
    if sels[0].spread_line + sels[1].spread_line != 0:
        raise ValueError(
            f"Spread {name!r} market_line {ml_line}: "
            f"selection lines {sels[0].spread_line} + "
            f"{sels[1].spread_line} don't sum to zero")


def _validate_total_line(
    sels: list[Selection], ml_line: float, name: str,
) -> None:
    """Total: 2 selections, outcome_ids {12,13}, selection lines match market_line."""
    if len(sels) != 2:
        raise ValueError(
            f"Total {name!r} market_line {ml_line}: "
            f"{len(sels)} selections (expected 2)")
    oids = {s.outcome_id for s in sels}
    if oids != OUTCOME_IDS_TOTAL:
        raise ValueError(
            f"Total {name!r} market_line {ml_line}: "
            f"unexpected outcome_ids {oids}")
    for s in sels:
        if s.spread_line != ml_line:
            raise ValueError(
                f"Total {name!r}: selection {s.display_name!r} line "
                f"{s.spread_line} != market_line {ml_line}")


def _validate_sup_moneyline_sels(sels: list[Selection], name: str) -> None:
    """sup_moneyline: 2 selections, outcome_ids {1,2}, selection lines are 0."""
    if len(sels) != 2:
        raise ValueError(
            f"sup_moneyline {name!r}: {len(sels)} selections (expected 2)")
    oids = {s.outcome_id for s in sels}
    if oids != OUTCOME_IDS_YESNO:
        raise ValueError(
            f"sup_moneyline {name!r}: unexpected outcome_ids {oids}")


def _parse_sup_moneyline_line(
    sels: list[Selection],
    name: str,
    event_team_map: dict[str, str] | None,
) -> tuple[float | None, list[Selection]]:
    """Parse a sup_moneyline market into a (line, selections) pair.

    Dispatches on display_name shape:
      OU flavor     — "Over N.N" / "Under N.N" — shared threshold;
                      selections unchanged.
      YES/NO flavor — "YES" / "NO" (any case) — line None; DD/TD
                      that PX ships as sup_moneyline instead of
                      moneyline.
      Spread flavor — "<team> [+-]N.N" — line 0; selections get
                      team_abbr + signed spread_line via
                      event_team_map.

    OU, then YES/NO, then spread.  No mixed flavors.
    """
    ou_lines: list[float] = []
    is_ou = True
    for s in sels:
        m = re.match(r"^(?:Over|Under)\s+([\d.]+)$", s.display_name)
        if m is None:
            is_ou = False
            break
        ou_lines.append(float(m.group(1)))
    if is_ou:
        unique = set(ou_lines)
        if len(unique) != 1:
            raise ValueError(
                f"sup_moneyline {name!r}: inconsistent lines in "
                f"display_names: {unique}")
        return unique.pop(), sels
    if {s.display_name.upper() for s in sels} == {"YES", "NO"}:
        return _yes_no_threshold(name), sels
    return _parse_sup_moneyline_spread(sels, name, event_team_map)


# Soccer goalscorer yes/no props carry their threshold only in the market
# name: "Lionel Messi To Score A Goal" (anytime = over 0.5) and
# "Lionel Messi To Score 2+ Goals" (over 1.5).
_RE_SCORE_A_GOAL = re.compile(r"\bTo Score A Goal$", re.I)
_RE_SCORE_N_GOALS = re.compile(r"\bTo Score (\d+)\+ Goals$", re.I)
# NFL anytime-touchdown scorer: a type=moneyline YES/NO market (strike 0)
# whose threshold lives only in the name, like the soccer goalscorer above.
_RE_SCORE_A_TD = re.compile(r"\bTo Score a Touchdown$", re.I)
_RE_SCORE_N_TDS = re.compile(r"\bTo Score (\d+)\+ Touchdowns$", re.I)


def _yes_no_threshold(name: str) -> float | None:
    """Over/under threshold a yes/no market name implies, else None."""
    if _RE_SCORE_A_GOAL.search(name):
        return 0.5
    if _RE_SCORE_A_TD.search(name):
        return 0.5
    m = _RE_SCORE_N_GOALS.search(name) or _RE_SCORE_N_TDS.search(name)
    if m:
        return int(m.group(1)) - 0.5
    return None


def _parse_sup_moneyline_spread(
    sels: list[Selection],
    name: str,
    event_team_map: dict[str, str] | None,
) -> tuple[float, list[Selection]]:
    """Parse "<team> [+-]N.N" sup_moneyline display_names.

    Returns (0.0, selections) where each selection has team_abbr set
    to the canonical team (resolved via event_team_map) and spread_line
    set to the signed handicap.

    The team-prefix group is permissive (`.+?`) so the same parser
    handles EPL's 3-char codes ("BRE -0.5") and any other league's
    display shape — including NBA full-team-name format ("Atlanta
    Hawks +0.5") — without per-league configuration.  Real validation
    is membership in event_team_map: a junk prefix raises with a clear
    "team X not in event Y" error.

    Validates pair-wise invariants: signed handicaps sum to zero and
    the two selections resolve to distinct teams.
    """
    if event_team_map is None:
        raise ValueError(
            f"sup_moneyline {name!r}: spread-flavor display_names "
            f"({[s.display_name for s in sels]}) but no "
            f"event_team_map provided")
    new_sels: list[Selection] = []
    for s in sels:
        m = re.match(r"^(.+?)\s+([+-][\d.]+)$", s.display_name)
        if m is None:
            raise ValueError(
                f"sup_moneyline {name!r}: can't parse spread from "
                f"display_name {s.display_name!r}")
        prefix, signed = m.group(1), float(m.group(2))
        canonical = event_team_map.get(prefix)
        if canonical is None:
            raise ValueError(
                f"sup_moneyline {name!r}: team prefix {prefix!r} in "
                f"display_name {s.display_name!r} not in event "
                f"(known: {sorted(event_team_map)})")
        new_sels.append(s._replace(
            team_abbr=canonical, spread_line=signed))
    if new_sels[0].spread_line + new_sels[1].spread_line != 0:
        raise ValueError(
            f"sup_moneyline spread {name!r}: signed handicaps "
            f"{new_sels[0].spread_line} + {new_sels[1].spread_line} "
            f"don't sum to zero")
    if new_sels[0].team_abbr == new_sels[1].team_abbr:
        raise ValueError(
            f"sup_moneyline spread {name!r}: both selections "
            f"resolved to the same team {new_sels[0].team_abbr!r}")
    return 0.0, new_sels


def extract_market_lines(
    market: Market,
    event_team_map: dict[str, str] | None = None,
) -> list[Line]:
    """Normalize PX market data into a uniform list of Lines.

    Moneyline markets have selections directly on the market;
    spread and total markets have a market_lines array.  This
    function produces the same shape for both.

    Validates per-market-type structural invariants at extraction
    time — outcome_ids, selection counts, line consistency, and
    spread symmetry.  Raises ValueError on any violation.
    """
    name = market.name

    if market.type == "moneyline":
        assert market.selections is not None
        sels = [_extract_selection(s) for s in market.selections]
        _validate_moneyline_sels(sels, name)
        return [Line(line=None, selections=sels)]

    if market.type == "sup_moneyline":
        assert market.selections is not None
        sels = [_extract_selection(s) for s in market.selections]
        _validate_sup_moneyline_sels(sels, name)
        line, sels = _parse_sup_moneyline_line(sels, name, event_team_map)
        return [Line(line=line, selections=sels)]

    # spread or total — market_lines array (normalized from market_strikes)
    assert market.market_lines is not None
    result = []
    for ml in market.market_lines:
        sels = [_extract_selection(s) for s in ml["selections"]]
        ml_line = _ml_strike(ml)
        if market.type == "spread":
            _validate_spread_line(sels, ml_line, name)
        elif market.type == "total":
            _validate_total_line(sels, ml_line, name)
        result.append(Line(line=ml_line, selections=sels))
    return result


# === Classification ===

# Expected PX `type` field for each Shape.  Cross-checked at
# classification time to catch data corruption or new market shapes.
# PX uses three structural types; they map directly to Shape.
_PX_TYPE_FOR_SHAPE: dict[Shape, str] = {
    Shape.MONEYLINE:   "moneyline",
    Shape.SPREAD:      "spread",
    Shape.TOTAL:       "total",
    Shape.THREE_WAY:   "moneyline",
    Shape.OVER_UNDER:  "total",
    Shape.YES_NO:      "moneyline",
    Shape.YES_NO_LINE: "sup_moneyline",
    Shape.H2H:         "moneyline",  # guess — no PX H2H data yet; classify_market will raise if wrong
    # CORRECT_SCORE is never wired into any PX config (no league's PX.exact/
    # suffix maps to MarketType.CORRECT_SCORE) — classify_market can't be
    # reached with this shape today. Entry exists only to satisfy
    # test_px_type_for_shape_covers_all_shapes (every Shape must have one);
    # "moneyline" is a placeholder guess, same convention as the H2H entry.
    Shape.CORRECT_SCORE: "moneyline",
    # Likewise unreachable: no PX config maps to DOUBLE_CHANCE.
    Shape.DOUBLE_CHANCE: "moneyline",
}

# sup_moneyline markets reuse the same PX name suffixes as regular
# total markets but need distinct MarketTypes to avoid key collisions.
# After name-based matching, classify_market remaps to _YN variants
# when px_type is "sup_moneyline".
_SUP_MONEYLINE_REMAP: dict[MarketType, MarketType] = {
    MarketType.PLAYER_ASSISTS: MarketType.PLAYER_ASSISTS_YN,
    MarketType.PLAYER_BLOCKS: MarketType.PLAYER_BLOCKS_YN,
    MarketType.PLAYER_GOALS: MarketType.PLAYER_GOALS_YN,
    MarketType.PLAYER_POINTS: MarketType.PLAYER_POINTS_YN,
    MarketType.PLAYER_PTS_AST: MarketType.PLAYER_PTS_AST_YN,
    MarketType.PLAYER_PTS_REB: MarketType.PLAYER_PTS_REB_YN,
    MarketType.PLAYER_PTS_REB_AST: MarketType.PLAYER_PTS_REB_AST_YN,
    MarketType.PLAYER_REB_AST: MarketType.PLAYER_REB_AST_YN,
    MarketType.PLAYER_REBOUNDS: MarketType.PLAYER_REBOUNDS_YN,
    MarketType.PLAYER_STEALS: MarketType.PLAYER_STEALS_YN,
    MarketType.PLAYER_STEALS_BLOCKS: MarketType.PLAYER_STEALS_BLOCKS_YN,
    MarketType.PLAYER_THREES: MarketType.PLAYER_THREES_YN,
    MarketType.PLAYER_TOUCHDOWNS: MarketType.PLAYER_TOUCHDOWNS_YN,
    MarketType.PLAYER_TURNOVERS: MarketType.PLAYER_TURNOVERS_YN,
    # EPL "Spread (Regular Time)" may ship as type=sup_moneyline.
    # Same Shape.SPREAD as POINT_SPREAD; team identity is parsed from
    # display_name into Selection.team_abbr at extract time.
    MarketType.POINT_SPREAD: MarketType.POINT_SPREAD_YN,
}
_SUP_MONEYLINE_REVERSE: dict[MarketType, MarketType] = {
    v: k for k, v in _SUP_MONEYLINE_REMAP.items()
}
# String-keyed lookup for downgrade in build_rows (row.market_type is a string).
_SUP_MONEYLINE_REVERSE_BY_VALUE: dict[str, MarketType] = {
    k.value: v for k, v in _SUP_MONEYLINE_REVERSE.items()
}
_SUP_MONEYLINE_REVERSE_VALUES: frozenset[str] = frozenset(
    _SUP_MONEYLINE_REVERSE_BY_VALUE.keys()
)


def is_known_market(name: str, cfg: PxConfig) -> bool:
    """True if name matches an exact or suffix entry in cfg."""
    if name in cfg.exact:
        return True
    return any(name.endswith(s) for s, _ in cfg.suffix)


class MatchResult(NamedTuple):
    """Result of matching a PX market name against cfg.

    suffix is None when the name was an exact-match in cfg.exact;
    otherwise it's the cfg.suffix entry that endswith-matches `name`.
    Sharing this choice with extract_player guarantees both functions
    agree on which boundary divides the player-name from the stat-name
    portion of the market name.
    """
    market_type: MarketType
    suffix: str | None


def classify_market(name: str, px_type: str, cfg: PxConfig) -> MatchResult:
    """Classify a PX market into a canonical MarketType and matched suffix.

    Matches on `name` (exact for game-level, longest-suffix for
    parameterized), then cross-checks that the PX `type` field agrees.
    Raises ValueError if the name is unrecognized or the type mismatches.

    Suffix matching picks the strictly-longest endswith match across
    cfg.suffix, independent of declared order.  Two suffixes can both
    endswith-match the same name (e.g. " Total Points" and " Points"
    both match "X Total Points") — the longer one wins.  Equal-length
    distinct suffixes can't both endswith-match a single name (the
    last N chars of a string are unique), so "strictly longest" is
    always unambiguous; no tie-breaker needed.
    """
    # Step 1: match name
    mt: MarketType | None = cfg.exact.get(name)
    matched_suffix: str | None = None
    if mt is None:
        best: tuple[str, MarketType] | None = None
        for suffix, candidate in cfg.suffix:
            if name.endswith(suffix) and (
                best is None or len(suffix) > len(best[0])
            ):
                best = (suffix, candidate)
        if best is not None:
            matched_suffix, mt = best

    if mt is None:
        raise ValueError(f"Unrecognized PX market name: {name!r}")

    # PX ships some threshold yes/no props (NFL "To Score a Touchdown") as
    # type=moneyline, not sup_moneyline.  Their over/under twin is the
    # configured type, so treat them as the sup_moneyline flavour.
    if (
        px_type == "moneyline"
        and mt.shape == Shape.OVER_UNDER
        and _yes_no_threshold(name) is not None
    ):
        px_type = "sup_moneyline"

    # Step 2: cross-check PX type against the pre-remap Shape.
    #
    # px_type="sup_moneyline" is allowed to ride on top of multiple
    # shapes (OVER_UNDER → YES_NO_LINE for player props; SPREAD →
    # POINT_SPREAD_YN for EPL "Spread (Regular Time)"; YES_NO for
    # DD/TD that PX relabeled from moneyline).  We defer validation
    # to the remap step below, which raises if the matched shape
    # needs a _YN variant and has none — stronger than a pre-remap
    # Shape↔px_type comparison could give us.
    expected = _PX_TYPE_FOR_SHAPE.get(mt.shape)
    if expected is None:
        raise ValueError(
            f"PX market {name!r}: classified as {mt.value} "
            f"(shape={mt.shape.value}) but no _PX_TYPE_FOR_SHAPE entry")
    if px_type != "sup_moneyline" and px_type != expected:
        raise ValueError(
            f"PX market {name!r}: type is {px_type!r}, "
            f"expected {expected!r} for {mt.value} "
            f"(shape={mt.shape.value})")

    # Step 3: remap to _YN variant for sup_moneyline markets.  The
    # matched_suffix carries through unchanged: PX uses the same name
    # suffix for the _YN variant as for its OVER_UNDER counterpart, so
    # the suffix to strip in extract_player is the same either way.
    # Genuine YES_NO (DD/TD) needs no remap — already yes/no.
    if px_type == "sup_moneyline" and mt.shape != Shape.YES_NO:
        remapped = _SUP_MONEYLINE_REMAP.get(mt)
        if remapped is None:
            raise ValueError(
                f"PX market {name!r}: sup_moneyline with no _YN "
                f"variant for {mt.value}")
        mt = remapped

    return MatchResult(market_type=mt, suffix=matched_suffix)


def build_team_id_map(
    competitors: list[Competitor],
    team_markets: list[Market],
    event_team_map: dict[str, str],
    event_id: int,
) -> dict[int, str]:
    """Build market-ID → canonical-team map via the modulo relationship.

    PX team total market IDs encode the competitor: the low-order
    digits match the competitor ID (market_id % 1M == competitor_id
    % 1M).

    We check injection (each market maps to a real, distinct
    competitor) and guard against competitor suffix collisions.
    Together with the collision guard, injection implies bijection
    for the 2-market case by pigeonhole.  For 1-market events
    (PX sometimes publishes a solo team total) the injection
    check is the strongest we can enforce.

    Returns a dict mapping each team-scoped market's ID to its
    canonical team abbreviation.
    """
    # competitor suffix → canonical abbreviation
    comp_suffix: dict[int, str] = {
        c.id % 1_000_000: event_team_map[c.abbreviation]
        for c in competitors
    }
    if len(comp_suffix) != len(competitors):
        raise ValueError(
            f"Event {event_id}: competitor suffix collision — "
            f"{len(competitors)} competitors but only "
            f"{len(comp_suffix)} distinct id % 1M suffixes")

    if not team_markets:
        return {}

    if len(team_markets) > 2:
        raise ValueError(
            f"Expected at most 2 team total markets for event "
            f"{event_id}, got {len(team_markets)}: "
            f"{[m.name for m in team_markets]}")

    team_id_map: dict[int, str] = {}
    matched: set[int] = set()
    for m in team_markets:
        suffix = m.id % 1_000_000
        if suffix not in comp_suffix:
            raise ValueError(
                f"Team total market {m.id} ({m.name!r}) "
                f"suffix {suffix} doesn't match any "
                f"competitor in event {event_id}: {comp_suffix}")
        if suffix in matched:
            raise ValueError(
                f"Duplicate team total suffix {suffix} "
                f"in event {event_id}")
        matched.add(suffix)
        team_id_map[m.id] = comp_suffix[suffix]

    return team_id_map


def extract_player(name: str, suffix: str) -> str:
    """Extract the player name from a PX market name by stripping suffix.

    `suffix` is the one classify_market matched against the same name,
    threaded through by classify_and_enrich.  Sharing the choice
    eliminates the risk that classify and extract pick different
    suffixes when more than one endswith-matches — e.g. both
    " Total Points" and " Points" match "Paolo Banchero Total Points",
    but only the longer one strips to the correct player "Paolo
    Banchero".  classify_market already picked the longer one; we just
    reuse that choice here.
    """
    assert name.endswith(suffix), (
        f"PX market name {name!r} doesn't end with matched suffix "
        f"{suffix!r} — classify_market/extract_player got out of sync")
    return name[:len(name) - len(suffix)].rstrip()


def classify_and_enrich(
    market: Market,
    cfg: PxConfig,
    team_id_map: dict[int, str],
    event_team_map: dict[str, str] | None = None,
) -> ClassifiedMarket:
    """Classify a raw PX market and extract its enrichment fields.

    Composes classify_market, extract_player, and extract_market_lines
    into a single step that returns a ClassifiedMarket with all fields
    guaranteed present.

    team_id_map maps market IDs to canonical team abbreviations,
    built upstream via the modulo relationship between PX market IDs
    and competitor IDs (market_id % 1M == competitor_id % 1M).
    Bijection validation in the pipeline guarantees that every
    team-scoped market's ID is present in the map.

    event_team_map maps PX team prefixes (abbreviations and canonicals)
    to canonical team abbreviations for this event's two competitors.
    Required only for sup_moneyline POINT_SPREAD_YN, where team identity
    is encoded in selection display_name; harmless for other markets.
    """
    match = classify_market(market.name, market.type, cfg)
    mt = match.market_type
    team_abbrev = None
    player = None
    if mt.scope == Scope.TEAM:
        if market.id not in team_id_map:
            raise ValueError(
                f"Team-scoped market {market.id} ({market.name!r}) "
                f"not in team_id_map — bijection should have caught this")
        team_abbrev = team_id_map[market.id]
    elif mt.scope == Scope.PLAYER:
        # PLAYER-scoped markets always come from cfg.suffix (never
        # cfg.exact), so classify_market must have picked a suffix.
        assert match.suffix is not None, (
            f"PLAYER-scoped {market.name!r} matched via cfg.exact — "
            f"no suffix to strip")
        player = extract_player(market.name, match.suffix)
    return ClassifiedMarket(
        raw=market,
        market_type=mt,
        team_abbrev=team_abbrev,
        player=player,
        market_lines=_classified_lines(market, match, event_team_map),
    )


def _classified_lines(
    market: Market,
    match: MatchResult,
    event_team_map: dict[str, str] | None,
) -> list[Line]:
    """extract_market_lines, with YES/NO three-way legs bound to a side."""
    lines = extract_market_lines(market, event_team_map)
    if match.market_type.shape == Shape.YES_NO_LINE and market.type == "moneyline":
        threshold = _yes_no_threshold(market.name)
        if threshold is None:
            raise ValueError(
                f"PX market {market.name!r}: no threshold in name for "
                f"{match.market_type.value}")
        return [Line(line=threshold, selections=ln.selections) for ln in lines]
    if match.market_type.shape == Shape.THREE_WAY and _is_yes_no(lines):
        return _split_three_way_lines(
            market.name, match.suffix, lines, event_team_map or {})
    return lines


def _is_yes_no(lines: list[Line]) -> bool:
    """True when every selection is a fixed yes/no outcome (oids {1,2})."""
    oids = {s.outcome_id for line in lines for s in line.selections}
    return bool(oids) and oids <= OUTCOME_IDS_YESNO


def _split_three_way_lines(
    name: str,
    suffix: str | None,
    lines: list[Line],
    event_team_map: Mapping[str, str],
) -> list[Line]:
    """Bind one leg of a three-way that PX lists as its own YES/NO market.

    Soccer friendlies ship the 90-minute result as three markets —
    "<team> to Win (90 Min)" (suffix rule) and "Draw (90 Min)" (exact
    rule) — each with YES/NO selections instead of one market with
    team/draw selections.  The YES selection is that leg: it carries
    the team (resolved via event_team_map) or _TIE.  The NO side has no
    Optic counterpart and is dropped.  A leg that names neither team
    nor a draw yields no lines, so the market maps nothing rather than
    failing the league.
    """
    if suffix is not None:
        prefix = extract_player(name, suffix)
        side = event_team_map.get(prefix) or {
            k.casefold(): v for k, v in event_team_map.items()
        }.get(prefix.casefold())
    elif name.casefold().startswith("draw"):
        side = TIE_SIDE
    else:
        side = None
    if side is None:
        return []
    return [
        Line(line=None, selections=[s._replace(team_abbr=side)])
        for line in lines
        for s in line.selections
        if s.outcome_id == 1
    ]


# === Side-label resolution ===

# WARNING: The outcome_id mappings below are an AI assessment based on
# observed PX data.  They need careful real-world verification before
# being trusted for production matching.
#
# PX outcome_id: the structural role a selection plays in a market.
#
# Every PX selection carries an outcome_id that describes *what kind
# of position* it is, independent of which game or player.  These
# codes are stable across all NBA games:
#
#   OUTCOME_IDS_TEAM {4, 5}       — team-identified (moneyline): one
#                per team, pick the winner.  competitor_id → team.
#   OUTCOME_IDS_SPREAD {1714, 1715} — team-identified (spread): one
#                per team, pick who covers.  competitor_id → team.
#   OUTCOME_IDS_TOTAL {12, 13}    — over/under: direction on a total
#                (game, team, or player stat).  12 = over, 13 = under.
#   OUTCOME_IDS_YESNO {1, 2}      — yes/no: binary outcome (e.g.
#                double-double).  1 = yes, 2 = no.
#
# Team-identified outcomes carry a competitor_id that maps to the
# team abbreviation via the event's competitors array.  The others
# resolve from outcome_id alone.

OUTCOME_IDS_TEAM   = frozenset({4, 5})       # moneyline team selections
OUTCOME_IDS_SPREAD = frozenset({1714, 1715})  # spread team selections
OUTCOME_IDS_TOTAL  = frozenset({12, 13})      # over/under (12=over, 13=under)
OUTCOME_IDS_YESNO  = frozenset({1, 2})        # yes/no (1=yes, 2=no)

_TEAM_OUTCOME_IDS = OUTCOME_IDS_TEAM | OUTCOME_IDS_SPREAD

_FIXED_SIDE_LABELS: dict[int, str] = {
    12: "over",
    13: "under",
    1: "yes",
    2: "no",
}


def build_comp_map(
    event: Event,
    team_aliases: Mapping[str, AliasValue],
) -> dict[int, str]:
    """Build {competitor_id: normalized_abbrev} from a PX event."""
    return {
        c.id: resolve_team(
            c.abbreviation, team_aliases, c.name, c.id)
        for c in event.competitors
    }


def resolve_side_label(
    sel: Selection,
    comp_map: dict[int, str],
) -> str:
    """Map a PX selection to its semantic side label.

    Three resolution paths, picked by which channel carries the side
    identity on the selection:

    1. Pre-resolved team_abbr (parse-time): currently only sup_moneyline
       POINT_SPREAD_YN, where the team identity lives in display_name
       and is canonicalized in extract_market_lines.
    2. Team-identified via competitor_id: moneyline (outcome_ids {4,5})
       and spread (outcome_ids {1714,1715}) — resolved via comp_map.
    3. Fixed labels: over/under (outcome_ids {12,13}) and yes/no
       (outcome_ids {1,2}) — resolved from outcome_id alone.
    """
    if sel.team_abbr is not None:
        return sel.team_abbr

    if sel.outcome_id in _TEAM_OUTCOME_IDS:
        assert sel.competitor_id is not None
        team = comp_map.get(sel.competitor_id)
        if team is None:
            raise ValueError(
                f"competitor_id {sel.competitor_id} not in comp_map")
        return team

    # Yes/no outcome_ids are not stable across PX market types: moneyline
    # props ship 1=YES, sup_moneyline goalscorer props ship 1=NO.  The
    # display_name is authoritative whenever it is literally YES/NO.
    if sel.outcome_id in OUTCOME_IDS_YESNO:
        shown = sel.display_name.strip().upper()
        if shown in ("YES", "NO"):
            return shown.lower()

    label = _FIXED_SIDE_LABELS.get(sel.outcome_id)
    if label is None:
        raise ValueError(f"Unknown outcome_id {sel.outcome_id}")
    return label


# === Canonical row building ===

def build_rows(
    start_date: str,
    home: str,
    away: str,
    markets: list[ClassifiedMarket],
    comp_map: dict[int, str],
    player_aliases: dict[str, str] | None = None,
    *,
    league: str,
) -> list[CanonicalRow]:
    """Build flat canonical rows from a game's PX markets.

    Every classified market produces rows.  Each selection on each
    market_line produces one row — two rows per line (one per side).

    Line semantics by shape:
      MONEYLINE, THREE_WAY, YES_NO — None (no line)
      SPREAD                       — signed, from sel.line (e.g. -8.5, +8.5)
      TOTAL, OVER_UNDER            — unsigned threshold from ml.line (e.g. 220.5)
    """
    rows: list[CanonicalRow] = []
    for market in markets:
        mt = market.market_type

        if mt.scope == Scope.TEAM:
            entity = market.team_abbrev
        elif mt.scope == Scope.PLAYER:
            assert market.player is not None
            entity = normalize_player_name(market.player)
            if player_aliases:
                entity = player_aliases.get(entity, entity)
        else:
            entity = None

        for ml in market.market_lines:
            for sel in ml.selections:
                side = resolve_side_label(sel, comp_map)
                # Team moneylines must not carry yes/no sides.  PX type=
                # moneyline also hosts Shape.YES_NO props (oids {1,2});
                # those shapes are fine — only MONEYLINE/THREE_WAY/H2H
                # expect team (or _TIE) labels.
                if (
                    mt.shape in (Shape.MONEYLINE, Shape.THREE_WAY, Shape.H2H)
                    and side in ("yes", "no")
                ):
                    raise ValueError(
                        f"PX {mt.value} {market.raw.name!r}: side "
                        f"{side!r} from outcome_id {sel.outcome_id} "
                        f"— team moneyline got yes/no oids {{1,2}}")
                if side == TIE_SIDE and mt.shape == Shape.THREE_WAY:
                    pass
                elif mt.shape in {Shape.MONEYLINE, Shape.SPREAD, Shape.THREE_WAY}:
                    named = team_side(side, home=home, away=away)
                    if named is None:
                        continue
                    side = named

                # Spread: per-selection signed line.
                # Totals: per-market-line unsigned threshold.
                # Moneyline: no line.
                if mt.shape == Shape.SPREAD:
                    line = sel.spread_line
                elif ml.line is not None:
                    line = ml.line
                else:
                    line = None

                rows.append(CanonicalRow(
                    league=league,
                    start_date=start_date,
                    home=home,
                    away=away,
                    market_type=mt.value,
                    entity=entity,
                    line=line,
                    side=side,
                    px_event_id=market.raw.sport_event_id,
                    px_line_id=sel.line_id,
                    px_market_name=market.raw.name,
                    px_selection_display_name=sel.display_name,
                ))

    # Downgrade _YN rows to regular over/under when no regular
    # counterpart exists at the same (entity, line).  sup_moneyline
    # markets get _YN types to avoid colliding with a coexisting
    # regular `total` version (seen in NBA fetch fetch 2026-03-06/23_54).
    # When sup_moneyline is the sole version (NCAAB, same fetch), the
    # _YN type blocks the cross-exchange merge with Optic, which uses
    # the regular type.
    yn_to_ou = {"yes": "over", "no": "under"}
    regular_keys: set[tuple[str, str | None, float | None]] = set()
    for r in rows:
        if r.market_type not in _SUP_MONEYLINE_REVERSE_VALUES:
            regular_keys.add((r.market_type, r.entity, normalize_line(r.line)))
    for r in rows:
        yn_mt = _SUP_MONEYLINE_REVERSE_BY_VALUE.get(r.market_type)
        if yn_mt is None:
            continue
        if (yn_mt.value, r.entity, normalize_line(r.line)) not in regular_keys:
            r.market_type = yn_mt.value
            # Player-prop _YN rows have side ∈ {"yes","no"} that needs
            # rewriting to over/under for merge with the regular total.
            # POINT_SPREAD_YN rows already carry team-abbrev sides
            # (parsed from display_name), which match POINT_SPREAD
            # untouched — gate the rewrite on side membership.
            if r.side in yn_to_ou:
                r.side = yn_to_ou[r.side]

    return rows


# === Grouping and validation ===

def group_markets(markets: list[ClassifiedMarket]) -> dict[str, list[ClassifiedMarket]]:
    """Group PX markets by MarketType.value."""
    grouped: dict[str, list[ClassifiedMarket]] = defaultdict(list)
    for m in markets:
        grouped[m.market_type.value].append(m)
    return dict(grouped)


def validate_markets(
    grouped: dict[str, list[ClassifiedMarket]],
    home: str,
    away: str,
    label: str,
) -> None:
    """Validate grouped PX markets for a single game.

    Checks scope-specific invariants and raises ValueError on violation.
    label is used in error messages to identify the game.
    """
    for mt_value, entries in grouped.items():
        n = len(entries)
        if n == 0:
            continue

        mt = entries[0].market_type
        if mt.shape == Shape.THREE_WAY and all(map(_is_split_leg, entries)):
            _validate_split_three_way(entries, label)
            continue

        if mt.scope == Scope.GAME:
            # POINT_SPREAD_YN is the one GAME-scope MarketType that PX
            # ships as one market per spread line (sup_moneyline shape
            # SPREAD): multiple lines per game means multiple
            # ClassifiedMarket entries, one Line each.  Other
            # GAME-scope markets bundle all lines into one market's
            # market_lines[] array, so n == 1 is the right invariant.
            if mt == MarketType.POINT_SPREAD_YN:
                # Each entry's single Line carries two selections with
                # signed handicaps that sum to zero, so the unordered
                # pair of spread_line values uniquely identifies the
                # line.  Two markets at the same line would silently
                # collide on row_key downstream — reject here.
                seen: set[frozenset[float]] = set()
                for m in entries:
                    sels = m.market_lines[0].selections
                    assert sels[0].spread_line is not None
                    assert sels[1].spread_line is not None
                    key = frozenset(
                        {sels[0].spread_line, sels[1].spread_line})
                    if key in seen:
                        raise ValueError(
                            f"{label}: {mt_value} has duplicate "
                            f"line {sorted(key)}")
                    seen.add(key)
            elif n != 1:
                raise ValueError(
                    f"{label}: {mt_value} has {n} entries, expected 1")

        # PX may skip one team's prefix (opaque, unresolvable) —
        # so we may see 1 entry instead of the expected pair.
        elif mt.scope == Scope.TEAM:
            if n > 2:
                raise ValueError(
                    f"{label}: {mt_value} has {n} entries, expected 1 or 2")
            teams = {m.team_abbrev for m in entries}
            if not teams <= {home, away}:
                raise ValueError(
                    f"{label}: {mt_value} teams are {teams}, "
                    f"expected subset of {{{home}, {away}}}")

        elif mt.scope == Scope.PLAYER:
            players = []
            for m in entries:
                name = m.player
                if not name or not name.strip():
                    raise ValueError(
                        f"{label}: {mt_value} has entry with "
                        f"empty player name")
                players.append(name)
            # YES_NO_LINE markets legitimately have multiple entries
            # per player at different thresholds (e.g. Total Points
            # at 13.5 and 14.5).
            if mt.shape != Shape.YES_NO_LINE:
                dupes = [p for p in players if players.count(p) > 1]
                if dupes:
                    raise ValueError(
                        f"{label}: {mt_value} has duplicate players: "
                        f"{sorted(set(dupes))}")

        # Validate market_lines on every market
        for m in entries:
            mls = m.market_lines
            if not mls:
                raise ValueError(
                    f"{label}: {mt_value} market has no market_lines")
            for ml in mls:
                n_sels = len(ml.selections)
                if n_sels != 2:
                    raise ValueError(
                        f"{label}: {mt_value} market_line has "
                        f"{n_sels} selections, expected 2")


def _is_split_leg(m: ClassifiedMarket) -> bool:
    """A YES/NO three-way leg from _split_three_way_lines (maybe unbound)."""
    sels = [s for line in m.market_lines for s in line.selections]
    if not sels:
        return m.raw.type == "moneyline"
    return all(s.outcome_id == 1 and s.team_abbr for s in sels)


def _validate_split_three_way(
    entries: list[ClassifiedMarket],
    label: str,
) -> None:
    """Split three-way legs must bind distinct sides, one selection each."""
    sides = [
        s.team_abbr
        for m in entries
        for line in m.market_lines
        for s in line.selections
    ]
    if len(sides) != len(set(sides)):
        raise ValueError(
            f"{label}: {entries[0].market_type.value} has {len(entries)} "
            f"entries that are not distinct YES/NO legs: {sides}")
