"""Polymarket active matcher — bridge slug/question → OpticOdds.

Polymarket combo legs reference underlying single markets (clob_token_id).
The position↔token bridge (raw_ingestion_us.polymarket_position_token_bridge,
built by BigQuery/load_polymarket_position_bridge.py) carries each single's
slug/question/outcome_label per clob_token_id. This matcher parses that
natural-language question into a `ParsedMarket` (market_type + side_mode +
teams/entity/line) and matches the fixture by TEAM NAME against the optic
schedule (Polymarket exposes no stable team IDs, unlike crypto.com), then emits
one CanonicalRow per outcome with side bound to the outcome_label (or, for
THREE_WAY_FIXED, to the entity named in the question). Rows merge onto existing
optic rows (see attach_polymarket_row in pipeline.py) — a market optic didn't
price is dropped.

The parse is config-driven: a `PolymarketConfig` carries an ordered tuple of
`market_rules` (each a `question -> ParsedMarket | None` recognizer); the first
rule that matches wins. `build_rows` is sport-agnostic — it dispatches on
`(parsed.market_type.scope, parsed.side_mode)`, so a new league/market is added
by writing rules + config only, never by editing this dispatch.
"""

from __future__ import annotations

import contextlib
import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from pydantic import BaseModel

from mappers.canonical_codes import names_close
from mappers.market_types import MarketType, Scope, Shape
from mappers.shared import TIE_SIDE, CanonicalRow, correct_score_line, normalize_player_name
from mappers.team_side import team_side


class SideMode(Enum):
    """How a market's two outcomes bind to canonical sides.

    Side is ALWAYS bound to the outcome label or the entity named in the
    question — never to an outcome's array index. A market that can't cleanly
    resolve its sides is dropped whole (build_rows returns []).
    """

    TEAM_LABEL = "team_label"          # MONEYLINE: each outcome label is a team name → fixture abbrev
    SPREAD_TEAM = "spread_team"        # SPREAD: label=team → abbrev; named team carries the signed line, other negated
    OVER_UNDER = "over_under"          # TOTAL/OVER_UNDER: Over→"over", Under→"under"
    YESNO_AS_OU = "yesno_as_ou"        # player/team Yes-No-at-threshold: Yes→"over", No→"under"
    YESNO = "yesno"                    # GAME yes/no (BTTS): Yes→"yes", No→"no"
    THREE_WAY_FIXED = "three_way_fixed"  # only affirmative outcome emits; side=parsed.fixed_side (abbrev or _TIE)
    # CORRECT_SCORE: only affirmative ("Yes") outcome emits, like
    # THREE_WAY_FIXED, but side is the WINNER (resolved from team_a_goals vs
    # team_b_goals, never index) and line carries the scoreline — see
    # build_rows' EXACT_SCORE branch.
    EXACT_SCORE = "exact_score"


@dataclass(frozen=True)
class ParsedMarket:
    """A recognized single-market question, ready for build_rows dispatch."""

    market_type: MarketType
    team_a: str | None            # normalized team names for fixture matching (GAME/TEAM); None for player-only forms
    team_b: str | None
    side_mode: SideMode
    # entity — PLAYER: normalize_player_name(player); TEAM-scope: normalized team
    # NAME (build_rows resolves → abbrev); GAME: None. Also overloaded by
    # SPREAD_TEAM (a GAME-scope form) to carry the question-named reference team
    # whose signed line is bound; build_rows' SPREAD_TEAM branch reads it directly.
    entity: str | None = None
    line: float | None = None     # unsigned threshold, signed spread, or None
    date: str | None = None       # match date parsed from the slug (injected by the pipeline)
    # Polymarket's OWN kickoff instant (Gamma ``gameStartTime``), injected by the
    # pipeline from the bridge. AUTHORITATIVE for fixture resolution: `date` above
    # is the venue-LOCAL date scraped out of the slug, while optic's
    # Fixture.start_date is UTC, so the two can never be compared safely for a US
    # night game (local D == UTC D+1). When this is set the pipeline matches on the
    # instant and ignores `date` entirely; `date` remains the fallback for bridge
    # rows written before this field existed.
    game_start_time: str | None = None
    # THREE_WAY_FIXED: normalized team name whose Yes maps to that team's abbrev;
    # None + THREE_WAY_FIXED ⇒ _TIE (draw).
    fixed_side_team: str | None = None
    affirmative_label: str = "yes"   # THREE_WAY_FIXED: which outcome_label emits (default "yes")
    # EXACT_SCORE: the two digits parsed straight from "Exact Score: <A> N1 -
    # N2 <B>?" (N1=team_a's goals, N2=team_b's goals per the question's own
    # order — build_rows still resolves team_a/team_b to home/away by NAME,
    # never assumes team_a==home). None unless side_mode==EXACT_SCORE.
    team_a_goals: int | None = None
    team_b_goals: int | None = None
    # Per-question-form name-match granularity (task TN2, see
    # wave-tennis-probe-findings.md section C.2): "full" (default) compares a
    # poly label/entity against the fixture competitor name as today
    # (byte-identical for every league/rule that never sets this). "surname"
    # compares against the LAST underscore-token of the normalized fixture
    # name instead -- four upcoming tennis forms (set-winner, set-handicap,
    # match-total-games, set-games) label players by surname only
    # ("Luca Van Assche" -> "Assche"), varying PER FORM within the same
    # league/config, so this can't be a per-league question_style. Consulted
    # by build_rows' TEAM_LABEL/SPREAD_TEAM branches and by
    # pipeline._match_poly_fixture via _match_name/_fixture_surname_collision
    # below.
    name_granularity: Literal["full", "surname"] = "full"


# A market rule recognizes a question form and produces a ParsedMarket (or None).
MarketRule = Callable[[str, "PolymarketConfig"], "ParsedMarket | None"]


@dataclass(frozen=True)
class PolymarketConfig:
    """Per-league Polymarket matching constants."""

    slug_prefix: str  # official bridge slug prefix, e.g. "mlb" ("" = no official pass)
    optic_league_id: str  # optic league_id to match within, e.g. "mlb"
    market_types: dict[str, MarketType]  # question-kind -> canonical MarketType
    # keys referenced by this league's rules, e.g. "moneyline", "total"
    question_style: Literal["mlb_suffix", "tennis_prefix"] = "mlb_suffix"
    # "mlb_suffix" (A vs B[: O/U N]) | "tennis_prefix" (<Tournament>: A vs B)
    market_rules: tuple[MarketRule, ...] = ()
    # ordered recognizers; parse_question returns the first non-None result.
    # Per-league team-name alias overlay (Task 7): maps a _norm_name'd poly
    # team name -> the _norm_name'd optic name it should be treated as
    # equivalent to. A handful of franchises' poly question name and Optic
    # fixture name share no containment substring at all (MLS: "CF Montréal"
    # vs "Club de Foot Montréal", "Los Angeles Galaxy" vs "LA Galaxy", "New
    # York City FC" vs "New York City Football Club", "D.C. United SC" vs
    # "DC United", "Inter Miami CF" vs "Club Internacional de Fútbol Miami"
    # -- see wave-4-probe-findings.md section D), so plain containment can
    # never bridge the gap; this overlay is consulted by _name_match (via
    # team_alias_scope below) before falling back to containment. Empty by
    # default -- every league before Task 7 is unaffected. Reusable per
    # league (Liga MX/UCL each declare their own dict here).
    team_name_aliases: dict[str, str] = field(default_factory=dict)


class PolyOutcome(BaseModel):
    clob_token_id: str
    position_id: str
    outcome_label: str
    outcome_index: int


class PolyMarket(BaseModel):
    condition_id: str
    slug: str
    question: str
    outcomes: list[PolyOutcome]
    # Gamma ``gameStartTime`` as carried on the bridge row; None for bridge rows
    # written before the column existed (the pipeline then falls back to the
    # slug-parsed date). See ParsedMarket.game_start_time.
    game_start_time: str | None = None


# --- ported from mmpolymarketrfq/common/mapping_loader.py (team-name matching) ---


def _normalize(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_name(s: str | None, style: str) -> str:
    """Normalize a team/player name per league style.

    tennis_prefix -> normalize_player_name (diacritic + base-letter fold, period +
    Jr/Sr strip, underscore-joined) so a poly player label agrees with the Optic
    entity. mlb_suffix -> the team _normalize (space-joined, NFKD only).
    """
    if style == "tennis_prefix":
        return normalize_player_name(s or "")
    return _normalize(s)


# === Team-name alias overlay (per-league, reusable — Task 7) ===
#
# PolymarketConfig.team_name_aliases (see field docstring above) needs to be
# consulted from inside _name_match, including the calls build_rows (frozen)
# makes directly -- THREE_WAY_FIXED's fixed_side_team check and SPREAD_TEAM's
# per-outcome label check both compare a poly name to home_name/away_name with
# no PolymarketConfig in reach at that call site, so an explicit parameter
# can't be threaded through without editing build_rows. Instead, the pipeline
# opens an ambient scope with the active league's aliases for the duration of
# its whole Polymarket pass (fixture resolution AND build_rows), and
# _name_match consults whatever scope is currently open. No open scope (every
# league before this task, and every call site outside the Polymarket pass)
# means an empty dict -- a no-op, so _name_match's behavior is byte-identical
# to before for anything that never opens one.
_active_team_aliases: dict[str, str] = {}


@contextlib.contextmanager
def team_alias_scope(aliases: dict[str, str]):
    """Make `aliases` visible to `_name_match` for the duration of the block."""
    global _active_team_aliases
    previous = _active_team_aliases
    _active_team_aliases = aliases
    try:
        yield
    finally:
        _active_team_aliases = previous


def _name_match(a: str, b: str, style: str) -> bool:
    """Compare two already-_norm_name'd names per style.

    Both styles first resolve either side through the active
    team_name_aliases overlay (see team_alias_scope), so an aliased poly name
    matches its intended optic name before the style-specific comparison
    runs. tennis_prefix -> exact equality after alias resolution, plus the existing
    player reverse-order check (Lorenzo Lorusso ↔ Lorusso Lorenzo). Never
    containment: "rune" must not match "holger_rune". mlb_suffix -> the team
    containment check (_names_equiv-style) after alias resolution.

    Task-u1 (UFC): the alias overlay used to be consulted only on the
    mlb_suffix path (tennis_prefix returned before reaching it) because no
    tennis_prefix league had ever populated team_name_aliases -- ATP/WTA ship
    an empty dict, so this reordering is a no-op for them (byte-identical:
    `if _active_team_aliases` never fires). UFC is the first tennis_prefix
    league to need a real fighter-name alias (transliteration variants, e.g.
    "Magomed Zaynukov" poly vs "Magomed Zayunokov" optic), which needs the
    overlay to actually run under exact-match semantics too.
    """
    if not a or not b:
        return False
    if _active_team_aliases:
        a = _active_team_aliases.get(a, a)
        b = _active_team_aliases.get(b, b)
    if style == "tennis_prefix":
        return a == b or names_close(a, b, player=True)
    return a == b or a in b or b in a


# === Per-question-form name granularity (task TN2) ===
#
# ParsedMarket.name_granularity ("full" | "surname") lets a form label
# players by surname only (the four upcoming tennis forms in
# wave-tennis-probe-findings.md section C.2) while sibling forms in the SAME
# league/config (moneyline/total_sets) keep full-name matching -- the
# granularity varies per question FORM, not per league, so it can't live on
# PolymarketConfig.question_style. _match_name/_fixture_surname_collision are
# consulted by build_rows' TEAM_LABEL/SPREAD_TEAM branches and by
# pipeline._match_poly_fixture (which reads parsed.name_granularity directly).


def _match_name(poly_value: str, fixture_name: str | None, style: str, granularity: str) -> bool:
    """Compare a poly-side name/label to a RAW fixture competitor name.

    granularity="full" (default): reduces to exactly the pre-existing call
    pattern every consumer used before this task --
    `_name_match(poly_value, _norm_name(fixture_name, style), style)` --
    byte-identical, no behavior change for any existing form.

    granularity="surname": compares `_norm_name(poly_value, style)` (poly
    surname labels are already single-token) against the LAST
    underscore-token of `_norm_name(fixture_name, style)` -- reproduces the
    probe's "last whitespace token" convention ("Luca Van Assche" ->
    "assche"). normalize_player_name never splits on hyphens, so
    "Auger-Aliassime" stays one token and matches a bare "Auger-Aliassime"
    poly label exactly.
    """
    if granularity == "surname":
        surname = _norm_name(fixture_name, style).rsplit("_", 1)[-1]
        return _name_match(_norm_name(poly_value, style), surname, style)
    return _name_match(poly_value, _norm_name(fixture_name, style), style)


def _fixture_surname_collision(home_name: str | None, away_name: str | None, style: str) -> bool:
    """True when a fixture's two competitors share the same last-token surname.

    Flip-safety guard (task TN2): under granularity="surname" a shared last
    token makes ANY surname-based label/entity resolution against this
    fixture inherently ambiguous (e.g. two "Silva"s in the same match) --
    callers must drop (return no match) rather than guess which side is
    which. A no-op under granularity="full" (callers gate this check behind
    `granularity == "surname"`).
    """
    h = _norm_name(home_name, style).rsplit("_", 1)[-1]
    a = _norm_name(away_name, style).rsplit("_", 1)[-1]
    return bool(h) and h == a


# Both regexes split on the FIRST " vs " occurrence (non-greedy team_a group)
# -- safe for MLB team names; revisit if a league has a team name containing
# "vs".
# Full-game moneyline: "<Team A> vs. <Team B>"  (no suffix)
_Q_MONEYLINE = re.compile(r"^(.+?)\s+vs\.?\s+(.+?)$", re.I)
# Full-game total:     "<Team A> vs. <Team B>: O/U <N>"
_Q_TOTAL = re.compile(r"^(.+?)\s+vs\.?\s+(.+?):\s*o/u\s*([\d.]+)\s*$", re.I)
# Anything with a ":" that isn't a recognized suffix form is an exotic/period
# market the moneyline rule drops -> not ours.

# MLB player props: "<Player>: <Stat> O/U <N>"  (labels Over/Under). The stat is
# anchored so only the two props Polymarket lists for MLB match (probe 2026-07-22:
# Home Runs 922 markets, Strikeouts 365 — Hits / Total Bases / Hits+Runs+RBIs are
# priced by optic but not offered by poly, so no rule for them).
_Q_HOME_RUNS = re.compile(r"^(?P<player>.+?):\s*home runs\s+o/u\s*([\d.]+)\s*$", re.I)
_Q_STRIKEOUTS = re.compile(r"^(?P<player>.+?):\s*strikeouts\s+o/u\s*([\d.]+)\s*$", re.I)
# MLB game spread: "Spread: <Team> (-N)" / "(+N)"  (labels = the two TEAM names).
# Anchored on the exact "Spread:" prefix so "1st 5 Innings Spread: …" never
# matches here -- that form is a DIFFERENT market (optic's 1st_half_run_line),
# handled by mlb_f5_spread_rule.
_Q_SPREAD = re.compile(r"^spread:\s*(?P<team>.+?)\s*\(\s*([+-]?[\d.]+)\s*\)\s*$", re.I)
# MLB first-inning run: "Will there be a run scored in the first inning?: <A> vs. <B>"
# (labels Yes/No). Anchored on the full first-inning prefix so the F5 forms
# ("… winning after 5 innings?", "1st 5 …") — different markets, each with its
# own rule — never match here.
_Q_FIRST_INNING = re.compile(
    r"^will there be a run scored in the first inning\?:\s*(.+?)\s+vs\.?\s+(.+?)\s*$",
    re.I,
)
# MLB extra innings: "Will the game go to extra innings?: <A> vs. <B>" (labels
# Yes/No, 2 outcomes -- verified across every live slug, n_outcomes=2).  Unlike
# _Q_FIRST_INNING this is a genuine GAME yes/no, not a threshold in disguise:
# optic's `will_there_be_extra_innings` is (Scope.GAME, Shape.YES_NO), so the
# rule emits SideMode.YESNO with no line rather than YESNO_AS_OU @ 0.5.
#
# Anchored on the full literal prefix so neither of poly's two sibling
# innings-state forms can reach it -- "<A> vs. <B>: Tied after N innings?" and
# "<Team> winning after N innings?" are the two legs of the F5 3-way moneyline
# and now have their own rules (_Q_MLB_F5_TIED / _Q_MLB_F5_WINNER); they must
# keep dropping HERE regardless: "tied after 9" is not the same bet as "goes to
# extra innings" (a game tied after 9 in a 9-inning game does go to extras, but
# the poly form is parameterised on N and is quoted at N=5).
_Q_MLB_EXTRA_INNINGS = re.compile(
    r"^will the game go to extra innings\?:\s*(.+?)\s+vs\.?\s+(.+?)\s*$",
    re.I,
)

# === MLB 1st-5-innings (F5) forms ===
#
# All four are byte-exact from the poly bridge (prod census 2026-08-04, 14d,
# slug LIKE "mlb%"): F5 total 1002 markets, F5 spread 430, F5 winner-leg 398,
# F5 draw-leg 193 -- every one n_outcomes=2. They stayed unmapped until now
# only because optic's catalogue was believed to have no F5 counterpart; the
# baseball-first5-spreadstotals branch established that the correct optic
# family is "1st_half_*" (see mlb.py OPTIC.table_types), which gives all
# three shapes a target.
#
# F5 total: "<A> vs. <B>: 1st 5 Innings O/U <N>" (labels Over/Under). The
# full-game _Q_TOTAL cannot match this -- it requires "o/u" IMMEDIATELY after
# the only colon in the question, and here that colon is followed by the
# literal "1st 5 Innings" (team_b would need a second colon to backtrack
# over, and there isn't one). The reverse is equally safe: this pattern
# requires the "1st 5 innings" literal the full-game form never carries.
_Q_MLB_F5_TOTAL = re.compile(
    r"^(.+?)\s+vs\.?\s+(.+?):\s*1st\s+5\s+innings\s+o/u\s*([\d.]+)\s*$", re.I
)
# F5 spread: "1st 5 Innings Spread: <Team> (-N)" (labels = the two TEAM names,
# same as the full-game spread). Disjoint from _Q_SPREAD by construction:
# that one anchors "spread:" at ^, this one anchors the "1st 5 innings "
# prefix BEFORE "spread:", so neither can match the other's question.
_Q_MLB_F5_SPREAD = re.compile(
    r"^1st\s+5\s+innings\s+spread:\s*(?P<team>.+?)\s*\(\s*([+-]?[\d.]+)\s*\)\s*$", re.I
)
# F5 3-way moneyline, TEAM leg: "<Team> winning after 5 innings?" (labels
# Yes/No). Poly ships the F5 moneyline as three separate 2-outcome markets --
# the slugs say so outright: first-five-winner-home / -away / -draw -- so the
# THREE_WAY_FIXED per-leg vocabulary is the exact fit, and the draw leg below
# is what makes this a genuine 3-way (matching Kalshi's real KXMLBF5-*-TIE
# market and optic's 1st_half_moneyline_3-way), NOT crypto's 2-way F5
# moneyline.
#
# Only ONE team is named, so team_b stays None and the fixture resolves in
# Phase B off the slug head (mlb-oak-min-<date>-first-five-winner-home shares
# ("oak","min") with the game slug) -- identical to
# soccer_first_half_leader_rule / soccer_second_half_winner_rule.
#
# The "5" is a LITERAL, not a \d+ group: the form is parameterised on N and
# only N=5 is quoted today (census: 398 winner + 193 draw legs, all N=5), but
# a future "winning after 7 innings?" is NOT a 1st-5-innings market and must
# keep dropping rather than mis-stamp onto the F5 row.
_Q_MLB_F5_WINNER = re.compile(r"^(?P<team>.+?)\s+winning after 5 innings\?\s*$", re.I)
# F5 3-way moneyline, DRAW leg: "<A> vs. <B>: Tied after 5 innings?" (labels
# Yes/No). Names BOTH teams, so it resolves in Phase A. Same literal-5
# anchoring as the team leg above.
#
# NB this is exactly the question mlb_extra_innings_rule's docstring calls out
# as un-mappable -- correctly, at the time: with no F5 market on the optic
# side, "tied after 5" had nowhere to land, and it must never be folded into
# will_there_be_extra_innings ("tied after 5" is a different bet). Now that
# optic's 1st_half_moneyline_3-way is wired, it lands on that market's draw
# selection, which is what it actually is.
_Q_MLB_F5_TIED = re.compile(
    r"^(.+?)\s+vs\.?\s+(.+?):\s*tied after 5 innings\?\s*$", re.I
)


# === Market rules (question form -> ParsedMarket) ===
#
# Each rule is a recognizer bound to a league config via cfg.market_rules.
# They resolve the canonical MarketType through cfg.market_types (the config
# stays the single source of truth for which MarketType a kind maps to), so a
# league that doesn't declare a kind simply drops (rule returns None).


def mlb_total_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Full-game total: "<A> vs <B>: O/U N" -> OVER_UNDER (GAME)."""
    q = (question or "").strip()
    m = _Q_TOTAL.match(q)
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


def mlb_moneyline_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Full-game moneyline: "<A> vs <B>" -> TEAM_LABEL (GAME).

    A ":" that didn't match the O/U total form is a market kind we don't map
    (period/spread/prop) -> return None. (mlb_total_rule must run before this.)
    """
    q = (question or "").strip()
    if ":" in q:
        return None
    m = _Q_MONEYLINE.match(q)
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


def _player_prop_rule(
    question: str,
    cfg: PolymarketConfig,
    pattern: re.Pattern[str],
    kind: str,
    *,
    side_mode: SideMode = SideMode.OVER_UNDER,
    line_transform: Callable[[float], float] | None = None,
) -> ParsedMarket | None:
    """Shared recognizer for a "<Player>: <Stat> ..." prop -> (PLAYER).

    Default shape is "<Player>: <Stat> O/U N" -> OVER_UNDER, line=N (MLB's
    home-runs/strikeouts props, m.group(2) the O/U value verbatim). A caller
    can override `side_mode` (e.g. a Yes/No ladder bound YESNO_AS_OU) and/or
    `line_transform` (e.g. the "N+ <stat>" ladder, whose over/under threshold
    is N-0.5, not N itself) — used by soccer_player_goals_rule. Both default
    to the original MLB behavior, so mlb_home_runs_rule/mlb_strikeouts_rule
    are unaffected.

    entity is ALWAYS normalize_player_name(player) — never the question_style
    _norm_name — because the optic PLAYER entity is normalize_player_name(selection);
    keying on the mlb_suffix team normalizer would never match the optic row.
    When team_alias_scope is open, resolve the poly entity through
    team_name_aliases (e.g. megan_dileo -> megan_gustafson) so player-prop
    stamps land on the Optic row.
    """
    q = (question or "").strip()
    m = pattern.match(q)
    if not m:
        return None
    mt = cfg.market_types.get(kind)
    if mt is None:
        return None
    try:
        raw_line = float(m.group(2))
    except ValueError:
        return None
    line = line_transform(raw_line) if line_transform is not None else raw_line
    entity = normalize_player_name(m.group("player"))
    if _active_team_aliases:
        entity = _active_team_aliases.get(entity, entity)
    return ParsedMarket(
        market_type=mt,
        team_a=None,
        team_b=None,
        side_mode=side_mode,
        entity=entity,
        line=line,
    )


def mlb_home_runs_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Player home-runs prop: "<Player>: Home Runs O/U N" -> OVER_UNDER (PLAYER)."""
    return _player_prop_rule(question, cfg, _Q_HOME_RUNS, "home_runs")


def mlb_strikeouts_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Player strikeouts prop: "<Player>: Strikeouts O/U N" -> OVER_UNDER (PLAYER)."""
    return _player_prop_rule(question, cfg, _Q_STRIKEOUTS, "strikeouts")


def mlb_spread_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Game spread: "Spread: <Team> (-N)" -> SPREAD_TEAM (GAME).

    The question names ONE team + its signed line (put in entity); BOTH outcome
    labels are the two team names, so the pipeline resolves the fixture from those
    labels. Anchored on "Spread:" so "1st 5 Innings Spread: …" is not taken here
    (returns None) -- that is the F5 run line, mlb_f5_spread_rule's market.
    """
    q = (question or "").strip()
    m = _Q_SPREAD.match(q)
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


def mlb_first_inning_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """First-inning run: "Will there be a run scored in the first inning?: A vs. B"
    -> YESNO_AS_OU @ 0.5 (GAME). Yes->over, No->under (optic 1st_inning_total_runs
    @ 0.5). Anchored on the full first-inning prefix so the F5 forms
    ("… after 5 innings") never match.
    """
    q = (question or "").strip()
    m = _Q_FIRST_INNING.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("first_inning")
    if mt is None:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group(1), style),
        team_b=_norm_name(m.group(2), style),
        side_mode=SideMode.YESNO_AS_OU,
        entity=None,
        line=0.5,
    )


def mlb_extra_innings_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Extra innings: "Will the game go to extra innings?: A vs. B" -> YESNO (GAME).

    Pairs with optic's `will_there_be_extra_innings` (Scope.GAME, Shape.YES_NO),
    wired in this branch's MLB commit. Both sides carry entity=None and
    line=None, so the rows collide on (market_type, entity, line, side) with
    side in {"yes","no"} -- no threshold encoding on either side.

    NB this is a READINESS pairing, not a live win: optic lists the market in its
    catalogue but a 14d census of `opticodds_prices` found ZERO ticks for it, so
    every poly row here drops as `dropped_no_optic` until optic starts quoting
    it. That is the fail-safe direction (attach_polymarket_row is stamp-else-drop
    and never invents a standalone row), and it means the poly half is already in
    place the day optic turns it on -- the same reasoning the optic-side
    taxonomy-only keys were wired under.

    It used to be the ONLY one of poly's five unmapped MLB forms with an optic
    counterpart at all. That is no longer true: the four F5 forms (1st-5-innings
    total and spread, "<Team> winning after 5 innings?" and "Tied after 5
    innings?") now map onto optic's "1st_half_*" family -- see mlb_f5_total_rule
    / mlb_f5_spread_rule / mlb_f5_winner_rule / mlb_f5_tied_rule. The
    "tied after 5" form in particular lands on the F5 3-way's DRAW selection,
    which is what it is; it still must never land HERE.
    """
    q = (question or "").strip()
    m = _Q_MLB_EXTRA_INNINGS.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("extra_innings")
    if mt is None:
        return None
    style = cfg.question_style
    return ParsedMarket(
        market_type=mt,
        team_a=_norm_name(m.group(1), style),
        team_b=_norm_name(m.group(2), style),
        side_mode=SideMode.YESNO,
    )


def mlb_f5_total_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """F5 total: "<A> vs. <B>: 1st 5 Innings O/U N" -> OVER_UNDER (GAME).

    Identical shape to mlb_total_rule, just a different MarketType kind --
    optic's `1st_half_total_runs` rather than `total_runs`. Poly's highest-volume
    unmapped MLB form (1002 markets; ~$310k/48h when first measured).
    """
    q = (question or "").strip()
    m = _Q_MLB_F5_TOTAL.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("f5_total")
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


def mlb_f5_spread_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """F5 spread: "1st 5 Innings Spread: <Team> (-N)" -> SPREAD_TEAM (GAME).

    Identical mechanics to mlb_spread_rule (named team + its signed line in
    entity; both outcome labels are the two team names, so the fixture resolves
    from those labels in Phase A) -- only the MarketType kind differs, targeting
    optic's `1st_half_run_line`.
    """
    q = (question or "").strip()
    m = _Q_MLB_F5_SPREAD.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("f5_spread")
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


def mlb_f5_winner_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """F5 3-way ML, team leg: "<Team> winning after 5 innings?" ->
    THREE_WAY_FIXED (GAME), fixed_side_team=<Team>.

    Mirrors soccer_first_half_leader_rule / soccer_second_half_winner_rule: one
    team named, team_b None, so the fixture resolves in Phase B via the slug
    head. Pairs with mlb_f5_tied_rule (the draw leg) onto the single 3-way
    market optic exposes as `1st_half_moneyline_3-way`.
    """
    q = (question or "").strip()
    m = _Q_MLB_F5_WINNER.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("f5_moneyline_3way")
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


def mlb_f5_tied_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """F5 3-way ML, draw leg: "<A> vs. <B>: Tied after 5 innings?" ->
    THREE_WAY_FIXED (GAME), fixed_side_team=None (-> _TIE in build_rows).

    Mirrors soccer_second_half_draw_rule (both teams named -> Phase A). The
    _TIE side is optic's "Draw" selection of `1st_half_moneyline_3-way` and
    Kalshi's own KXMLBF5-<event>-TIE market, so all three platforms land on the
    same row.

    Must stay anchored on its own literal prefix so it never reaches
    mlb_extra_innings_rule's market: a game tied after 5 is not a game going to
    extra innings.
    """
    q = (question or "").strip()
    m = _Q_MLB_F5_TIED.match(q)
    if not m:
        return None
    mt = cfg.market_types.get("f5_moneyline_3way")
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




# === UFC/MMA v1 (task-u1, ufc-probe-findings.md sections B/C) ===
#
# Poly's UFC bridge menu is exactly 6 question forms; this v1 builds the 4
# CLEAN ones (~67%/253 of the 346-market census). Fighters are 1v1 with full
# names on both sides (never surname-only) -- question_style="tennis_prefix"
# is reused verbatim for exact-match name semantics (containment on short
# surnames like "Ko"/"Silva" would be unsafe).
#
# DROPPED, not built (return None; never recognized by any rule below):
#   - "Will the fight be won by submission?" (GAME_WIN_BY_SUBMISSION) -- no
#     clean optic target (optic's only "submission" signal is one bucket
#     embedded in the free-text `name` field of the discrete N-way
#     method_of_ending market; no standalone Yes/No market_id exists).
#   - "Will <Fighter> win by KO or TKO?" (FIGHTER_WIN_BY_KOTKO) -- its only
#     clean 2-sided optic target (team_to_win_by_knockout_submission_dq)
#     bundles KO/TKO+Submission+DQ ("any finish"), a BROADER proposition than
#     poly's literal KO/TKO-only question -- mapping one onto the other is a
#     silent probability skew. The semantically-exact target
#     (method_of_victory's "<Fighter> - KO/TKO" selection) needs a
#     market_id+name-suffix bucketer that doesn't exist yet (optic.py's
#     table_types is a flat market_id -> MarketType dict) -- deferred to a
#     follow-up, not force-fit here.
# Neither of the two above gets a MarketType constant or a recognizer; a
# question matching one simply falls through every rule below and
# parse_question returns None (dropped), same as any other unrecognized form.



# Cricket series winner. Live bridge 2026-08-26: tournament prefix then
# "<A> vs <B>". Draw / completed-match / runs props stay unrecognized —
# Optic prices moneyline only.
_Q_CRICKET_DRAW = re.compile(r"\bdraw\b", re.I)
_Q_CRICKET_MONEYLINE = re.compile(
    r"^(?:.+:\s+)?(.+?)\s+vs\.?\s+(.+?)\s*$",
    re.I,
)


def cricket_moneyline_rule(
    question: str, cfg: PolymarketConfig,
) -> ParsedMarket | None:
    """Cricket match winner: optional tournament prefix, then A vs B."""
    q = (question or "").strip()
    if not q or _Q_CRICKET_DRAW.search(q):
        return None
    m = _Q_CRICKET_MONEYLINE.match(q)
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


cricket_market_rules: tuple[MarketRule, ...] = (cricket_moneyline_rule,)




# Basketball question forms (probe: .superpowers/sdd/wave-5-probe-findings.md
# sections B/C, byte-exact against the live wnba bridge rows). WNBA's poly
# menu is exactly 6 forms: moneyline/total/spread are BYTE-IDENTICAL in shape
# to MLB's own forms (bare "<A> vs. <B>" moneyline, "<A> vs. <B>: O/U <N>"
# total, "Spread: <Team> (-N)" spread) -- no new regex or rule needed for
# those three, mlb_moneyline_rule/mlb_total_rule/mlb_spread_rule are reused
# directly (see basketball_market_rules below). Only the 3 player-prop forms
# are new, and only because the stat word differs from MLB's Home
# Runs/Strikeouts -- the shape ("<Player>: <Stat> O/U <N>") is identical.

# Basketball player props: "<Player>: <Stat> O/U <N>". Each stat regex mirrors
# _Q_HOME_RUNS's shape exactly (named "player" group + numeric group),
# anchored on its own stat word so Points/Rebounds/Assists never cross-match
# each other. Probe: 962/1,624 wnba bridge rows (59.2%) are these 3 props
# combined, all with Yes/No outcome labels (see basketball_player_*_rule).
_Q_BB_POINTS = re.compile(r"^(?P<player>.+?):\s*points\s+o/u\s*([\d.]+)\s*$", re.I)
_Q_BB_REBOUNDS = re.compile(r"^(?P<player>.+?):\s*rebounds\s+o/u\s*([\d.]+)\s*$", re.I)
_Q_BB_ASSISTS = re.compile(r"^(?P<player>.+?):\s*assists\s+o/u\s*([\d.]+)\s*$", re.I)


def basketball_player_points_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Player points prop: "<Player>: Points O/U N" -> YESNO_AS_OU (PLAYER).

    CRITICAL deviation from the MLB player-prop template: WNBA player props
    use Yes/No outcome labels, not Over/Under (probe confirmed 100% across
    962 rows) -- so side_mode is explicitly YESNO_AS_OU, not
    _player_prop_rule's OVER_UNDER default. Line = the O/U threshold N
    directly (no line_transform); entity = normalize_player_name(player),
    exactly as the MLB props do.
    """
    return _player_prop_rule(
        question, cfg, _Q_BB_POINTS, "player_points", side_mode=SideMode.YESNO_AS_OU
    )


def basketball_player_rebounds_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Player rebounds prop: "<Player>: Rebounds O/U N" -> YESNO_AS_OU (PLAYER).

    See basketball_player_points_rule for the YESNO_AS_OU rationale.
    """
    return _player_prop_rule(
        question, cfg, _Q_BB_REBOUNDS, "player_rebounds", side_mode=SideMode.YESNO_AS_OU
    )


def basketball_player_assists_rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Player assists prop: "<Player>: Assists O/U N" -> YESNO_AS_OU (PLAYER).

    See basketball_player_points_rule for the YESNO_AS_OU rationale.
    """
    return _player_prop_rule(
        question, cfg, _Q_BB_ASSISTS, "player_assists", side_mode=SideMode.YESNO_AS_OU
    )



def parse_question(question: str, cfg: PolymarketConfig) -> ParsedMarket | None:
    """Parse a single-market question via cfg.market_rules; first match wins.

    Returns None if no rule recognizes the question (the market is dropped as a
    non-game-line). There is NO legacy dict fallback: every league config must
    declare its market_rules.
    """
    for rule in cfg.market_rules:
        parsed = rule(question, cfg)
        if parsed is not None:
            return parsed
    return None


def parse_market(line: str) -> PolyMarket | None:
    """Parse one JSON line (written by fetch/polymarket.py) into a PolyMarket."""
    try:
        return PolyMarket(**json.loads(line))
    except (ValueError, TypeError):
        return None


def _stamp(o: PolyOutcome, market: PolyMarket) -> dict:
    """Shared polymarket_* stamp kwargs for a CanonicalRow."""
    return {
        "polymarket_clob_token_id": o.clob_token_id,
        "polymarket_condition_id": market.condition_id,
        "polymarket_position_id": o.position_id,
        "polymarket_slug": market.slug,
        "polymarket_question": market.question,
    }


def _unique_fixture_side(
    name: str,
    *,
    home: str,
    away: str,
    home_name: str,
    away_name: str,
    style: str,
    granularity: str = "full",
) -> str | None:
    """Return the fixture abbrev `name` uniquely matches, else None.

    mlb_suffix containment can hit both sides (``ofi`` ⊂ ``sofia`` and
    ``ofi`` ⊂ ``ofi fc``). Preferring home is a silent mis-map — drop.
    """
    if not name:
        return None
    hit_home = _match_name(name, home_name, style, granularity)
    hit_away = _match_name(name, away_name, style, granularity)
    if hit_home == hit_away:
        return None
    return team_side(home if hit_home else away, home=home, away=away)


def _resolve_entity(
    parsed: ParsedMarket,
    *,
    home: str,
    away: str,
    home_name: str,
    away_name: str,
    style: str,
) -> tuple[bool, str | None]:
    """Resolve the row `entity` for a scope, as (ok, entity).

    GAME -> (True, None); PLAYER -> (True, parsed.entity) verbatim (already a
    normalized player name); TEAM -> (True, abbrev) for parsed.entity (a
    normalized team NAME) uniquely matched to a fixture side. Returns
    (False, None) when a TEAM-scope name matches neither side or both
    (flip-unsafe -> caller drops the whole market).
    """
    scope = parsed.market_type.scope
    if scope == Scope.GAME:
        return True, None
    if scope == Scope.PLAYER:
        return True, parsed.entity
    side = _unique_fixture_side(
        parsed.entity or "",
        home=home, away=away, home_name=home_name, away_name=away_name,
        style=style,
    )
    if side is None:
        return False, None
    return True, side


def build_rows(
    market: PolyMarket,
    parsed: ParsedMarket,
    *,
    home: str,
    away: str,
    home_name: str,
    away_name: str,
    start_date: str,
    cfg: PolymarketConfig,
    league: str,
) -> list[CanonicalRow]:
    """Emit CanonicalRows for a parsed market; side bound to label or entity.

    Dispatches on parsed.side_mode (and parsed.market_type.scope for entity
    resolution). Flip-safety: a market whose outcomes/entity don't cleanly
    resolve to complementary sides is dropped WHOLE (return []). Rows merge onto
    existing optic rows later (attach_polymarket_row) — guard #3 (market must
    exist in optic for this fixture) and guard #4 (cross-clob optic-disagreement)
    are enforced in the poly pass, not here.
    """
    mt = parsed.market_type
    mode = parsed.side_mode
    style = cfg.question_style
    outcomes = market.outcomes

    def row(side: str, *, entity: str | None, line: float | None, o: PolyOutcome) -> CanonicalRow:
        return CanonicalRow(
            league=league, start_date=start_date, home=home, away=away,
            market_type=mt.value, entity=entity, line=line, side=side,
            **_stamp(o, market))

    # THREE_WAY_FIXED emits a single row for the affirmative outcome; it has its
    # own arity handling (the complementary outcome is intentionally dropped).
    if mode == SideMode.THREE_WAY_FIXED:
        if mt.shape is not Shape.THREE_WAY:
            return []  # a fixed 3-way side only makes sense on a THREE_WAY type
        if parsed.fixed_side_team is None:
            side = TIE_SIDE
        else:
            side = _unique_fixture_side(
                parsed.fixed_side_team,
                home=home, away=away, home_name=home_name, away_name=away_name,
                style=style,
            )
            if side is None:
                return []  # neither side, or both (containment collision) -> drop
        affirmative = [o for o in outcomes if _normalize(o.outcome_label) == parsed.affirmative_label]
        if len(affirmative) != 1:
            return []  # ambiguous/missing affirmative outcome -> drop
        return [row(side, entity=None, line=None, o=affirmative[0])]

    # EXACT_SCORE mirrors THREE_WAY_FIXED's single-affirmative-row pattern
    # (only "Yes" emits; "No" drops) but resolves a winner-anchored scoreline
    # key instead of a fixed team/tie side. Flip-safe: which parsed digit is
    # home_goals vs away_goals is decided by NAME match against the caller's
    # home_name/away_name, never by trusting the question's team_a/team_b
    # order (even though real data always has team_a==home per the probe).
    if mode == SideMode.EXACT_SCORE:
        if mt.shape is not Shape.CORRECT_SCORE:
            return []  # a scoreline key only makes sense on a CORRECT_SCORE type
        if parsed.team_a_goals is None or parsed.team_b_goals is None:
            return []
        a_side = _unique_fixture_side(
            parsed.team_a or "",
            home=home, away=away, home_name=home_name, away_name=away_name,
            style=style,
        )
        b_side = _unique_fixture_side(
            parsed.team_b or "",
            home=home, away=away, home_name=home_name, away_name=away_name,
            style=style,
        )
        if a_side is None or b_side is None or a_side == b_side:
            return []  # each name must uniquely map to opposite fixture sides
        if a_side == home:
            home_goals, away_goals = parsed.team_a_goals, parsed.team_b_goals
        else:
            home_goals, away_goals = parsed.team_b_goals, parsed.team_a_goals

        if home_goals == away_goals:
            side = TIE_SIDE
            winner_goals, loser_goals = home_goals, away_goals
        elif home_goals > away_goals:
            side = home
            winner_goals, loser_goals = home_goals, away_goals
        else:
            side = away
            winner_goals, loser_goals = away_goals, home_goals  # winner's goals first

        affirmative = [o for o in outcomes if _normalize(o.outcome_label) == parsed.affirmative_label]
        if len(affirmative) != 1:
            return []  # ambiguous/missing affirmative outcome -> drop
        line = correct_score_line(winner_goals, loser_goals)
        return [row(side, entity=None, line=line, o=affirmative[0])]

    # All remaining modes are strictly two-sided: exactly two complementary outcomes.
    if len(outcomes) != 2:
        return []

    if mode == SideMode.TEAM_LABEL:
        granularity = parsed.name_granularity
        if granularity == "surname" and _fixture_surname_collision(home_name, away_name, style):
            return []  # both competitors share this surname -> ambiguous, drop (flip-safety)
        seen: set[str] = set()
        rows: list[CanonicalRow] = []
        for o in outcomes:
            lab = _norm_name(o.outcome_label, style)
            side = _unique_fixture_side(
                lab, home=home, away=away, home_name=home_name,
                away_name=away_name, style=style, granularity=granularity,
            )
            if side is None:
                return []  # a label that isn't exactly one team -> drop market
            seen.add(side)
            rows.append(row(side, entity=None, line=None, o=o))
        if seen != {home, away}:
            return []  # not both complementary teams -> drop
        return rows

    if mode == SideMode.SPREAD_TEAM:
        if parsed.line is None:
            return []  # a spread with no line can't be signed -> drop
        granularity = parsed.name_granularity
        if granularity == "surname" and _fixture_surname_collision(home_name, away_name, style):
            return []  # both competitors share this surname -> ambiguous, drop (flip-safety)
        # The team named in the question carries +line; the other -line.
        ref = _unique_fixture_side(
            parsed.entity or "",
            home=home, away=away, home_name=home_name, away_name=away_name,
            style=style, granularity=granularity,
        )
        if ref is None:
            return []  # named team resolves to neither side, or both -> drop
        seen = set()
        rows = []
        for o in outcomes:
            lab = _norm_name(o.outcome_label, style)
            side = _unique_fixture_side(
                lab, home=home, away=away, home_name=home_name,
                away_name=away_name, style=style, granularity=granularity,
            )
            if side is None:
                return []
            seen.add(side)
            line = parsed.line if side == ref else -parsed.line
            rows.append(row(side, entity=None, line=line, o=o))
        if seen != {home, away}:
            return []
        return rows

    if mode in (SideMode.OVER_UNDER, SideMode.YESNO_AS_OU):
        ok, entity = _resolve_entity(parsed, home=home, away=away, home_name=home_name,
                                     away_name=away_name, style=style)
        if not ok:
            return []
        seen = set()
        rows = []
        for o in outcomes:
            lab = _normalize(o.outcome_label)
            if mode == SideMode.OVER_UNDER:
                over_lab, under_lab = "over", "under"
            else:  # YESNO_AS_OU
                over_lab, under_lab = "yes", "no"
            # GOTCHA-1 (wave-tennis-probe-findings.md section C.1): some forms
            # (tennis total_sets) bake the line into the label itself
            # ("Over 2.5" -> _normalize -> "over 2 5"), unlike every prior
            # OVER_UNDER form's bare "Over"/"Under". `lab == over_lab` alone
            # would silently drop those. The `startswith(over_lab + " ")`
            # variant matches "over 2 5" without over-matching an unrelated
            # label that happens to start with the same word (e.g.
            # "overtime" -- no space after "over", so it correctly falls
            # through to the drop branch). Bare "over"/"under" still match via
            # the `==` arm, so this is byte-identical for every existing form.
            if lab == over_lab or lab.startswith(over_lab + " "):
                side = "over"
            elif lab == under_lab or lab.startswith(under_lab + " "):
                side = "under"
            else:
                return []  # must be the two complementary labels -> else drop
            seen.add(side)
            rows.append(row(side, entity=entity, line=parsed.line, o=o))
        if seen != {"over", "under"}:
            return []
        return rows

    if mode == SideMode.YESNO:
        ok, entity = _resolve_entity(parsed, home=home, away=away, home_name=home_name,
                                     away_name=away_name, style=style)
        if not ok:
            return []
        seen = set()
        rows = []
        for o in outcomes:
            lab = _normalize(o.outcome_label)
            if lab == "yes":
                side = "yes"
            elif lab == "no":
                side = "no"
            else:
                return []  # must be yes/no -> else drop
            seen.add(side)
            rows.append(row(side, entity=entity, line=None, o=o))
        if seen != {"yes", "no"}:
            return []
        return rows

    return []


# Phase 4d: basketball bundles canonical home is basketball_markets.py.
from mappers.vocab import basketball_markets as _basketball_markets  # noqa: E402

BASKETBALL_MARKET_TYPES = _basketball_markets.BASKETBALL_MARKET_TYPES
basketball_market_rules = _basketball_markets.basketball_market_rules

# Sport bundles live in mappers/vocab/*_markets.py.
from mappers.vocab import esports_markets as _esports_markets  # noqa: E402
from mappers.vocab import soccer_markets as _soccer_markets  # noqa: E402
from mappers.vocab import tennis_markets as _tennis_markets  # noqa: E402

ESPORTS_MARKET_TYPES = _esports_markets.ESPORTS_MARKET_TYPES
LOL_MARKET_TYPES = _esports_markets.LOL_MARKET_TYPES
esports_map_handicap_rule = _esports_markets.esports_map_handicap_rule
esports_market_rules = _esports_markets.esports_market_rules
esports_moneyline_rule = _esports_markets.esports_moneyline_rule
esports_total_maps_rule = _esports_markets.esports_total_maps_rule
_Q_ESPORTS_MONEYLINE = _esports_markets._Q_ESPORTS_MONEYLINE
lol_market_rules = _esports_markets.lol_market_rules
lol_moneyline_rule = _esports_markets.lol_moneyline_rule

SOCCER_MARKET_TYPES = _soccer_markets.SOCCER_MARKET_TYPES
soccer_market_rules = _soccer_markets.soccer_market_rules
soccer_anytime_goalscorer_rule = _soccer_markets.soccer_anytime_goalscorer_rule
soccer_btts_rule = _soccer_markets.soccer_btts_rule
soccer_exact_score_rule = _soccer_markets.soccer_exact_score_rule
soccer_first_half_btts_rule = _soccer_markets.soccer_first_half_btts_rule
soccer_first_half_draw_rule = _soccer_markets.soccer_first_half_draw_rule
soccer_first_half_leader_rule = _soccer_markets.soccer_first_half_leader_rule
soccer_first_half_team_total_rule = _soccer_markets.soccer_first_half_team_total_rule
soccer_first_half_total_rule = _soccer_markets.soccer_first_half_total_rule
soccer_first_to_score_rule = _soccer_markets.soccer_first_to_score_rule
soccer_ml_draw_rule = _soccer_markets.soccer_ml_draw_rule
soccer_ml_team_win_rule = _soccer_markets.soccer_ml_team_win_rule
soccer_neither_scores_first_rule = _soccer_markets.soccer_neither_scores_first_rule
soccer_player_assists_rule = _soccer_markets.soccer_player_assists_rule
soccer_player_goals_or_assists_rule = _soccer_markets.soccer_player_goals_or_assists_rule
soccer_player_goals_rule = _soccer_markets.soccer_player_goals_rule
soccer_player_saves_rule = _soccer_markets.soccer_player_saves_rule
soccer_player_shots_on_target_rule = _soccer_markets.soccer_player_shots_on_target_rule
soccer_player_shots_rule = _soccer_markets.soccer_player_shots_rule
soccer_second_half_draw_rule = _soccer_markets.soccer_second_half_draw_rule
soccer_second_half_team_total_rule = _soccer_markets.soccer_second_half_team_total_rule
soccer_second_half_total_rule = _soccer_markets.soccer_second_half_total_rule
soccer_second_half_winner_rule = _soccer_markets.soccer_second_half_winner_rule
soccer_spread_rule = _soccer_markets.soccer_spread_rule
soccer_team_total_corners_rule = _soccer_markets.soccer_team_total_corners_rule
soccer_team_total_rule = _soccer_markets.soccer_team_total_rule
soccer_total_corners_rule = _soccer_markets.soccer_total_corners_rule
soccer_total_rule = _soccer_markets.soccer_total_rule

TENNIS_MARKET_TYPES = _tennis_markets.TENNIS_MARKET_TYPES
tennis_market_rules = _tennis_markets.tennis_market_rules
tennis_match_total_games_rule = _tennis_markets.tennis_match_total_games_rule
tennis_moneyline_rule = _tennis_markets.tennis_moneyline_rule
tennis_set_games_rule = _tennis_markets.tennis_set_games_rule
tennis_set_handicap_rule = _tennis_markets.tennis_set_handicap_rule
tennis_set_winner_rule = _tennis_markets.tennis_set_winner_rule
tennis_total_sets_rule = _tennis_markets.tennis_total_sets_rule
