"""crypto.com exchange mapper (FIX semantic path / Optic-gap filler).

crypto.com publishes its prediction-market catalogue over FIX as
SecurityList messages (ingested to BigQuery).  Each message describes
one binary-option contract = one selection.

Primary crypto stamps now come from OpticOdds ``source_ids.market_id``
decoded to a FIX Symbol (see ``mappers/exchanges/crypto_optic.py``).
This module remains the FIX semantic builder for Optic gaps and
crypto-only markets.  ``crypto_security_id`` (FIX SecurityID) is the
source-id stamp — the px_line_id / kalshi_ticker analog.

Four market groups are mapped today: Game Line, Player Prop (soccer
Anytime Goal Scorer — see ``_resolve_prop_line_side``), Team Prop (NFL/CFB
team total points — see ``_team_prop_row``), and Game/Fight Prop (soccer
BTTS — see ``_game_prop_row``).  Player and team props carry a fixture
``external_game_id``; game props are fixture-scoped yes/no questions with
no team side.  Genuinely out of scope are futures (Team/Player Future) and
COMBOS parlays, which have no ``external_game_id``.  Unlisted prop contract
types flow through but are skipped until they get a league-config entry.
"""

import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from mappers.exchanges.crypto_name_guard import (
    feed_name_fits_team,
    participant_contradicts_side,
    skip_crossed_stamp,
)
from mappers.fight_props import (
    canonicalize_fight_prop_key,
    is_roundless_win_label,
)
from mappers.market_types import MarketType, Scope, Shape
from mappers.shared import (
    TIE_SIDE,
    AliasValue,
    CanonicalRow,
    normalize_player_name,
    resolve_team,
)
from mappers.team_side import team_side

GAME_LINE = "Game Line"      # mappable market_group: game lines
FIGHT_LINE = "Fight Line"    # UFC/MMA analogue of Game Line
PLAYER_PROP = "Player Prop"  # mappable market_group: player props
TEAM_PROP = "Team Prop"      # team-scoped Over/Under (NFL/CFB team total points)
GAME_PROP = "Game Prop"      # mappable market_group: game-scoped yes/no props (BTTS)
FIGHT_PROP = "Fight Prop"    # UFC/MMA analogue of Game Prop (method/round/distance)

# Market groups that build game-scoped rows (team sides / fight winner).
GAME_LINE_GROUPS = frozenset({GAME_LINE, FIGHT_LINE})
# Market groups that build game-scoped yes/no props (BTTS, method of victory, …).
GAME_PROP_GROUPS = frozenset({GAME_PROP, FIGHT_PROP})


def crypto_market_rule_source_key_type(market_group: str) -> str:
    """Harvest / Why pin source_key_type for a crypto.com market group."""
    if market_group == TEAM_PROP:
        return "team_prop_contract_type"
    if market_group in GAME_PROP_GROUPS:
        return "game_prop_contract_type"
    if market_group == PLAYER_PROP:
        return "player_prop_contract_type"
    return "contract_type"


def crypto_python_wired_skip(
    crypto: Any,
    source_key: str,
    source_key_type: str,
    market_group: str,
) -> tuple[str, str] | None:
    """Python-wired skip: (reason, canonical) or None to keep harvesting."""
    table: dict[str, Any]
    if source_key_type == "team_prop_contract_type" or market_group == TEAM_PROP:
        table = crypto.team_prop_contract_types or {}
    elif source_key_type == "game_prop_contract_type" or market_group in GAME_PROP_GROUPS:
        table = crypto.game_prop_contract_types or {}
    elif source_key_type == "player_prop_contract_type" or market_group == PLAYER_PROP:
        table = crypto.prop_contract_types or {}
    else:
        ignored = crypto.game_line_ignored or frozenset()
        if source_key in ignored:
            return "already_ignored", ""
        return None
    mt = table.get(source_key)
    if mt is None:
        return None
    return "already_mapped", str(mt.value)


# All mappable catalogue market groups.
MAPPABLE_MARKET_GROUPS = (
    GAME_LINE_GROUPS | {PLAYER_PROP, TEAM_PROP} | GAME_PROP_GROUPS
)

# crypto.com's "1+ goals" anytime-goalscorer market, expressed as a
# Yes/No threshold contract (PREDICT_VALUE is empty; the "1+" lives in
# the contract_type string).
ANYTIME_GOAL_SCORER = "Anytime Goal Scorer"

# Soccer props express the threshold in contract_type ("2+ Shots" = over
# 1.5).  Fixed single-threshold contracts map here; N+ ladders parse via
# _THRESHOLD_RE / _TO_SCORE_GOALS_RE below.
_FIXED_OVER_HALF: dict[str, float] = {
    ANYTIME_GOAL_SCORER: 0.5,
    "To Give Assist": 0.5,
    "To Score Or Give Assist": 0.5,
    "To Receive A Card": 0.5,
    "To Receive A Red Card": 0.5,
    # MLB yes/no player thresholds (crypto lists only the Yes leg).
    "To Get A Hit": 0.5,
    "To Hit A Home Run": 0.5,
    # NFL anytime-touchdown scorer (Yes leg only) → player_touchdowns over 0.5.
    "To Score a Touchdown": 0.5,
    # NHL anytime goal scorer (Yes leg only) → player_goals over 0.5.
    "To Score a Goal": 0.5,
}
_THRESHOLD_RE = re.compile(r"^(\d+)\+ .+$")
_TO_SCORE_GOALS_RE = re.compile(r"^To Score (\d+)\+ Goals$")
_TO_SCORE_TOUCHDOWNS_RE = re.compile(r"^To Score (\d+)\+ Touchdowns$")

# Basketball-style props are true Over/Under stat lines: the line lives
# in PREDICT_VALUE or, when that is blank, in the event name
# (e.g. "Allisha Gray Over 18.5 Total Points").  The side is the
# PREDICT_OUTCOME_TYPE (Over/Under); rows sourced from
# crypto_underlying_securities leave it blank, so the name is the fallback.
_OVER_UNDER_NAME_RE = re.compile(r"\b(Over|Under)\s+(\d+(?:\.\d+)?)\b")


# === Input model ===

class Selection(BaseModel):
    """One crypto.com binary-option contract = one selection.

    One security_id == one selection — unlike Kalshi's yes/no split,
    each side is its own contract.  Fields hold raw crypto vocabulary
    (e.g. contract_type "Total Points", outcome_type "Over"); the
    mapper does the translation.  See docs/adding-crypto.md and
    scratch/crypto_com_input_schema.md.

    Teams are resolved to canonical abbrevs from the feed's external
    team IDs (external_home_id / external_away_id), NOT the display
    names: crypto emits full names that never equal the canonical abbrev
    (no resolve_team identity free-ride, so every team needs an explicit
    alias entry), and a name can drift or be mis-guessed, failing
    silently.  The IDs are stable, can't be guessed (they must come from
    the feed), and resolve as a pure string lookup.  The participant
    names are kept for readability/debug only.
    """
    security_id: str            # FIX SecurityID — the source-id stamp
    symbol: str                 # FIX Symbol — readable twin
    league: str                 # eventMeta LEAGUE, e.g. "NBA", "FIFA"
    sport: str                  # eventMeta SPORTS_GROUPING, e.g. "SOCCER"
    start_date: str             # UTC ISO timestamp (eventMeta EVENT_DATE)
    home_participant: str       # eventMeta HOME_PARTICIPANT — name, debug only
    away_participant: str       # eventMeta AWAY_PARTICIPANT — name, debug only
    external_home_id: str       # eventMeta EXTERNAL_HOME_ID — home team resolution key
    external_away_id: str       # eventMeta EXTERNAL_AWAY_ID — away team resolution key
    external_game_id: str       # fixture sanity / debug
    market_group: str           # eventMeta PREDICT_MARKET_TYPE ("Game Line" …)
    contract_type: str          # eventMeta PREDICT_CONTRACT_TYPE ("Moneyline" …)
    period: str                 # eventMeta PREDICT_PERIOD_TYPE (full-match gate)
    # eventMeta PREDICT_OUTCOME_TYPE (Home/Away/Over/…).  Optional: the
    # feed emits it BLANK on some player props — soccer First Goalscorer
    # and the N+ Saves ladder carry no outcome (the threshold lives in
    # the contract_type string).  Those props are unmapped and skipped by
    # _player_prop_row before outcome is read, so a blank value must
    # parse, not crash the load.  Game lines always carry an outcome.
    outcome_type: str | None = None
    value: float | None = None  # eventMeta PREDICT_VALUE → line (None for moneyline)
    # eventName is nullable in the catalogue; it is provenance metadata,
    # not required to identify or map a selection.
    selection_name: str | None  # eventName → crypto_selection_name stamp
    crypto_market_id: str       # eventMeta PREDICT_MARKET_ID
    crypto_outcome_id: str      # eventMeta PREDICT_OUTCOME_ID
    # Player-prop fields — populated only for Player Prop contracts, None
    # for game lines.  Player resolution is name-based: the canonical
    # entity is normalize_player_name(participant), the same merge key
    # Optic and Kalshi emit (all three normalise names through one
    # function, so crypto gets the identity free-ride teams don't —
    # see docs/adding-crypto.md "Player Props").  player_id / team_id are
    # carried for provenance and as the stable key for a future id-based
    # alias map, should a crypto spelling ever fail to merge.
    participant: str | None = None    # eventMeta PARTICIPANT — player name
    player_id: str | None = None      # eventMeta PLAYER_ID — stable player id
    team_id: str | None = None        # eventMeta TEAM_ID — player's team id


def to_selection_record(flat: dict) -> dict | None:
    """Map a full flattened contract to the Selection schema.

    This is the INTERPRETIVE half of the crypto.com read path.  Flat
    catalogue records are built at fetch time from
    ``processed_upstream_us`` tables (see ``fetch/crypto_com_underlying.py``
    and ``fetch/crypto_com_security_def.py``).  The on-disk file is the
    FULL catalogue, unfiltered; deciding what's mappable happens here, on
    read.

    Passes game lines, player props and game props; returns None for
    everything else.  Futures (Team/Player Future), blank-group specials
    and Tournament Props have no `external_game_id` — they can't be tied
    to a fixture and wouldn't even satisfy the Selection model.  A Player
    Prop, by contrast, IS game-scoped (it carries `external_game_id`, a
    `PLAYER_ID` and the player name), so it passes here; build_rows then
    maps the prop contract types it has a canonical target for and skips
    the rest (see docs/adding-crypto.md "Player Props").  A Game Prop
    (e.g. Both Teams To Score) is likewise game-scoped (carries
    `external_game_id`, no player) and passes the same way (see
    docs/adding-crypto.md "Next: add BTTS").  Field map mirrors
    scratch/crypto_com_input_schema.md.

    The `external_game_id` gate is enforced explicitly, not just implied
    by the market-group filter: the feed mislabels a few gameless markets
    as `Game Line` (e.g. PGA "Ryder Cup"), which carry no game id or
    teams and would crash the Selection model.  A real game line or prop
    has the game id 100% of the time, so dropping the ones without it is
    the same fixture-attachment rule, applied where it bites.

    The LEAGUE gate is the same discipline: pipeline filters by
    ``sel.league == CRYPTO.league`` after parse, so a null/blank LEAGUE
    can never attach.  Without the gate, ValidationError on one shared
    catalogue row aborts every crypto-wired league in the tick.
    """
    market_group = flat.get("eventMetaPREDICT_MARKET_TYPE")
    if market_group not in MAPPABLE_MARKET_GROUPS:
        return None
    league = flat.get("eventMetaLEAGUE")
    if not league:
        return None
    # UFC Fight Line rows often omit EXTERNAL_GAME_ID; synthesize a stable
    # fixture key from the NX.F.OPT.<league>-<event>-<yymmdd> symbol prefix
    # (same key the underlying catalogue identity index uses) when both
    # fighter/team ids are present. legacy: symbol parse — replace with the typed venue field, do not extend
    external_game_id = flat.get("eventMetaEXTERNAL_GAME_ID")
    if not external_game_id:
        if not (flat.get("eventMetaEXTERNAL_HOME_ID")
                and flat.get("eventMetaEXTERNAL_AWAY_ID")):
            return None
        symbol = flat.get("Symbol") or ""
        parts = symbol.split("-")
        if len(parts) < 3:
            return None
        external_game_id = "-".join(parts[:3])
    value = flat.get("eventMetaPREDICT_VALUE")
    return {
        "security_id": flat.get("SecurityID"),
        "symbol": flat.get("Symbol"),
        "league": league,
        "sport": flat.get("eventMetaSPORTS_GROUPING"),
        "start_date": flat.get("eventMetaEVENT_DATE"),
        "home_participant": flat.get("eventMetaHOME_PARTICIPANT"),
        "away_participant": flat.get("eventMetaAWAY_PARTICIPANT"),
        "external_home_id": flat.get("eventMetaEXTERNAL_HOME_ID"),
        "external_away_id": flat.get("eventMetaEXTERNAL_AWAY_ID"),
        "external_game_id": external_game_id,
        "market_group": market_group,
        "contract_type": flat.get("eventMetaPREDICT_CONTRACT_TYPE"),
        "period": flat.get("eventMetaPREDICT_PERIOD_TYPE"),
        "outcome_type": flat.get("eventMetaPREDICT_OUTCOME_TYPE"),
        # PREDICT_VALUE is "" / absent for moneyline; a number otherwise.
        "value": float(value) if value not in (None, "") else None,
        "selection_name": flat.get("eventName"),
        "crypto_market_id": flat.get("eventMetaPREDICT_MARKET_ID"),
        "crypto_outcome_id": flat.get("eventMetaPREDICT_OUTCOME_ID"),
        # Player-prop fields — absent (None) on game lines.
        "participant": flat.get("eventMetaPARTICIPANT"),
        "player_id": flat.get("eventMetaPLAYER_ID"),
        "team_id": flat.get("eventMetaTEAM_ID"),
    }


def parse_selection(line: str) -> Selection | None:
    """Parse one full-format catalogue line; None if not a game line.

    The input is one full flattened contract (as written by
    `fetch/crypto_com.py`, cron or ad-hoc); `to_selection_record`
    decides mappability and does the field translation.
    """
    rec = to_selection_record(json.loads(line))
    return None if rec is None else Selection(**rec)


@dataclass(frozen=True)
class CryptoConfig:
    """League-specific constants for crypto.com game-line mapping.

    Driven by the distinct contract_type / outcome_type / period_type
    values seen in the live FIX feed, not transcribed from a vendor
    catalogue (the catalogue lists the possible vocabulary, not what's
    actually offered, and the feed contradicts it in practice).
    """
    sport_grouping: str                     # eventMeta SPORTS_GROUPING, e.g. "NBA"
    league: str                             # eventMeta LEAGUE, e.g. "NBA", "FIFA"
    period_type: str                        # full-match gate, per-league (feed-defined)
    contract_types: dict[str, MarketType]   # game-line contract_type -> canonical MarketType
    # crypto.com symbol-namespace token in NX.F.OPT.<token>-...  It is NOT
    # derivable from league or sport_grouping: soccer files each competition
    # under its league (NX.F.OPT.UCL, sport_grouping "SOCCER") while tennis
    # lumps both tours under the sport grouping (NX.F.OPT.TENNIS, league
    # "ATP"/"WTA").  Defaults to league; override when they differ (tennis).
    symbol_prefix: str | None = None
    # Further meta_league codes whose selections belong to this league
    # (atp_challenger: "ATP Challenger", plus "ATP" which also carries
    # some Challenger events).
    also_leagues: tuple[str, ...] = ()
    # Per-contract period overrides when a game-line type uses a different
    # feed period than the league default (e.g. FIFA To Advance is "Full
    # Game" — ET-inclusive knockout progress — while ML/total/spread stay
    # on "90 Minutes and Stoppage Time").
    contract_period_types: dict[str, str] = field(default_factory=dict)
    # Same contract_type under an alternate period maps to a different
    # MarketType (e.g. MLB Moneyline / Moneyline (3-Way) @ "1st-5th Inning"
    # → f5_moneyline_3way; Moneyline (3-Way) @ "1st-3rd Inning"
    # → f3_moneyline_3way).
    # Keys are feed period strings; lookup uses periods_match.
    period_contract_types: dict[str, dict[str, MarketType]] = field(
        default_factory=dict,
    )
    # Game-line contract_types deliberately OUT OF SCOPE — the crypto
    # explicit ignore list.  Unmapped game-line types
    # are skipped in production (gap-check surfaces them); strict mode in
    # tests still raises.  Types listed here are skipped silently because
    # we've looked at them and chosen not to map them.
    game_line_ignored: frozenset[str] = frozenset()
    # Player-prop vocabulary — kept SEPARATE from the game-line fields
    # above on purpose.  crypto labels the full-match period per market
    # GROUP, not just per league: NBA props are "Full-Game" (hyphen) vs
    # game lines' "Full Game" (space); soccer happens to use "90 Minutes
    # and Stoppage Time" for both.  Reusing period_type for props would
    # silently drop every NBA prop, so props carry their own feed-defined
    # gate.  Both default empty/None — a league that maps no props leaves
    # them out and build_rows produces no prop rows.
    prop_contract_types: dict[str, MarketType] = field(default_factory=dict)
    prop_period_type: str | None = None     # prop full-match gate, per-league (feed-defined)
    # Game-prop vocabulary — a THIRD market group (e.g. Both Teams To
    # Score), again kept separate by the same per-group discipline.  A
    # game prop is game-scoped like a game line (resolved by the event
    # game id) but, like a player prop, carries no team side: it is a
    # yes/no question about the whole game (entity=None, line=None).
    # Unmapped game-prop types are SKIPPED, not raised — the prop
    # discipline, not the game-line one: crypto may extend the group and
    # we map a deliberately chosen subset.  Both default empty/None — a
    # league that maps no game props produces none.
    game_prop_contract_types: dict[str, MarketType] = field(default_factory=dict)
    game_prop_period_type: str | None = None  # game-prop full-match gate (feed-defined)
    # When True, also accept "Round N" periods for mapped game/fight props
    # (UFC Round of Victory / Round of Finish label the outcome in period).
    game_prop_accept_round_periods: bool = False
    # Fixed line per game-prop contract_type for races (Race to 10 Points
    # -> 10.0), written out because the feed leaves PREDICT_VALUE blank.
    game_prop_lines: dict[str, float] = field(default_factory=dict)
    # Team-prop vocabulary — a fourth market group (NFL/CFB "Team Prop" /
    # Total Points). Same Over/Under line shape as a game total, but
    # entity is one fixture side. Distinct from game-line Total Points
    # (game-scoped) and from game props (entity=None). Empty by default.
    team_prop_contract_types: dict[str, MarketType] = field(default_factory=dict)
    team_prop_period_type: str | None = None


def _game_line_period(cfg: CryptoConfig, contract_type: str) -> str:
    """Return the feed period gate for a mapped game-line contract type."""
    return cfg.contract_period_types.get(contract_type, cfg.period_type)


def _period_overlay_market_type(
    cfg: CryptoConfig,
    period: str,
    contract_type: str,
) -> MarketType | None:
    """Return MarketType when period+contract hit period_contract_types."""
    for config_period, by_contract in cfg.period_contract_types.items():
        if periods_match(period, config_period) and contract_type in by_contract:
            return by_contract[contract_type]
    return None


def normalize_period_type(period: str) -> str:
    """Collapse hyphen/whitespace variants for period gate comparison."""
    return re.sub(r"[\s\-]+", " ", period.strip().casefold())


def periods_match(feed_period: str, config_period: str) -> bool:
    """Return True when feed and config period strings are equivalent."""
    return normalize_period_type(feed_period) == normalize_period_type(config_period)


def _game_prop_period_ok(sel: Selection, cfg: CryptoConfig) -> bool:
    """Return True when a game/fight prop passes its period gate."""
    if cfg.game_prop_period_type is None:
        return False
    if periods_match(sel.period, cfg.game_prop_period_type):
        return True
    return bool(
        cfg.game_prop_accept_round_periods
        and normalize_period_type(sel.period).startswith("round ")
    )


# === Supersession dedupe ===

def dedupe_superseded(selections: list[Selection]) -> list[Selection]:
    """Collapse re-issued contract vintages: keep the latest per question.

    crypto.com re-lists a game's catalogue in waves, minting new
    SecurityIDs for the same betting questions, and the catalogue can
    carry both vintages at once; the latest is the live one.  Evidence
    and design rationale: docs/adding-crypto.md "Built: supersession
    dedupe".

    The question key is the full feed-vocabulary identity plus Symbol,
    NOT the EXTERNAL_MARKET_ID/OUTCOME_ID pair (blank or per-player-
    umbrella on props).  Symbol is included because a re-issue can mint
    a new outcome slot (e.g. M.O.1.1 → M.O.1.4) while RFQs still cite
    the old leg — attach_crypto_row loads each symbol as its own row.
    Re-issues under the *same* symbol still collapse to max security_id.
    The event home/away ids are included so an orientation-flipped
    re-issue could never collapse two different bets.  Output is sorted
    by security_id so downstream row order is independent of the feed
    file's unordered scan order.
    """
    latest: dict[tuple, Selection] = {}
    for sel in selections:
        key = (sel.external_game_id,
               sel.external_home_id, sel.external_away_id,
               sel.market_group, sel.contract_type, sel.period,
               sel.player_id, sel.participant,
               sel.outcome_type, sel.value,
               sel.symbol)
        prev = latest.get(key)
        if prev is None or sel.security_id > prev.security_id:
            latest[key] = sel
    return sorted(latest.values(), key=lambda s: s.security_id)


# === Mapping ===

def _resolve_side(outcome_type: str, home: str, away: str, shape: Shape) -> str:
    """Translate a crypto.com outcome_type to a canonical side.

    `home`/`away` here are the **selection's own** event home/away teams,
    resolved to canonical abbrevs from the feed's external team IDs
    (sel.external_home_id / sel.external_away_id), NOT the fixture's
    home/away.  Resolving on the stable feed ID rather than the display
    name makes the team identity immune to spelling/rename drift and
    impossible to mis-guess (the ID must come from the feed) — the same
    identity principle PX (competitor_id) and Kalshi (ticker code) use.

    These are event-level fields: they describe the game and are
    identical across every selection of it.  outcome_type then picks
    which of the game's two teams the bet is on (Home → the event home
    team, Away → the event away team).  Because we resolve crypto's own
    home/away orientation — not the fixture's position — the side stays
    correct even when crypto's orientation is flipped relative to Optic
    (neutral-site games, real for World Cup soccer).

    (The genuinely per-outcome identity would be the outcome-level
    TEAM_ID, but it is null on Over/Under and Draw, so we key on the
    always-present event home/away IDs and dispatch the no-team outcomes
    on outcome_type instead.)

    Dispatched on the market's shape so the side value agrees with the
    other exchanges' rows in the merge key:
      MONEYLINE / SPREAD / THREE_WAY — Home → the selection's home team
                           abbrev; Away → the selection's away team abbrev
      THREE_WAY          — additionally Draw → TIE_SIDE ("_TIE"), the same
                           draw literal Optic and Kalshi emit, so a crypto
                           draw row merges onto theirs (World Cup soccer).
                           A "Draw" on MONEYLINE/SPREAD raises — basketball
                           can't draw, so it would be a feed error.
      TOTAL              — Over/Under → "over"/"under"
      YES_NO             — Yes/No → "yes"/"no", the same literals Optic and
                           Kalshi emit (game-scoped game props, e.g. BTTS).
                           home/away are unused for this shape.  crypto
                           lists only the Yes side today; "No" is handled
                           defensively so a future No side merges.
    """
    if shape in (Shape.MONEYLINE, Shape.SPREAD, Shape.THREE_WAY):
        if outcome_type == "Home":
            return home
        if outcome_type == "Away":
            return away
        if shape == Shape.THREE_WAY and outcome_type == "Draw":
            return TIE_SIDE
        raise ValueError(f"unexpected {shape} outcome_type {outcome_type!r}")
    if shape == Shape.TOTAL:
        if outcome_type == "Over":
            return "over"
        if outcome_type == "Under":
            return "under"
        raise ValueError(f"unexpected TOTAL outcome_type {outcome_type!r}")
    if shape == Shape.YES_NO:
        if outcome_type == "Yes":
            return "yes"
        if outcome_type == "No":
            return "no"
        raise ValueError(f"unexpected YES_NO outcome_type {outcome_type!r}")
    raise ValueError(f"unsupported crypto.com shape {shape}")


def _resolve_fight_moneyline_side(
    sel: Selection, home: str, away: str,
) -> str:
    """Resolve UFC Fight Line moneyline side without PREDICT_OUTCOME_TYPE.

    UFC moneylines leave outcome_type blank and stamp the fighter on
    PARTICIPANT / PLAYER_ID.  Prefer the stable PLAYER_ID match against
    EXTERNAL_HOME_ID / EXTERNAL_AWAY_ID; fall back to participant name.
    """
    if sel.player_id:
        if sel.player_id == sel.external_home_id:
            return home
        if sel.player_id == sel.external_away_id:
            return away
    participant = (sel.participant or "").casefold()
    if participant and participant == (sel.home_participant or "").casefold():
        return home
    if participant and participant == (sel.away_participant or "").casefold():
        return away
    raise ValueError(
        f"crypto.com fight moneyline {sel.security_id!r}: cannot resolve "
        f"side from participant={sel.participant!r} player_id={sel.player_id!r}"
    )


def _yes_threshold_line_side(
    sel: Selection, mt: MarketType,
) -> tuple[float | None, str] | None:
    """Yes-leg threshold / YES_NO props; None to skip or fall through.

    crypto lists only the Yes leg.  ``No`` is skipped (not raised) so one
    stray row cannot zero the league.  Unhandled contract types return
    None so the caller can try Over/Under-from-name, then raise.
    """
    if mt.shape == Shape.YES_NO:
        if sel.outcome_type not in (None, "Yes"):
            return None
        return None, "yes"
    if sel.outcome_type == "No":
        return None
    if sel.contract_type in _FIXED_OVER_HALF:
        return _FIXED_OVER_HALF[sel.contract_type], "over"
    if m := _TO_SCORE_GOALS_RE.match(sel.contract_type):
        return int(m.group(1)) - 0.5, "over"
    if m := _TO_SCORE_TOUCHDOWNS_RE.match(sel.contract_type):
        return int(m.group(1)) - 0.5, "over"
    if m := _THRESHOLD_RE.match(sel.contract_type):
        return int(m.group(1)) - 0.5, "over"
    return None


def _resolve_over_under_prop(sel: Selection) -> tuple[float, str] | None:
    """Resolve a true Over/Under stat-line prop; None if not one.

    Basketball props (Total Points/Rebounds/Assists/3-Pointers) carry an
    Over/Under outcome and a real line, unlike the soccer threshold props
    whose line is baked into contract_type.  The line comes from
    PREDICT_VALUE when present, otherwise from the event name; the side
    comes from PREDICT_OUTCOME_TYPE, falling back to the name for rows
    (from crypto_underlying_securities) that leave outcome_type blank.

    Returns None when there is no Over/Under signal, or when the signal
    exists but the line is missing — skip that symbol, do not abort the
    league tick.
    """
    name_match = _OVER_UNDER_NAME_RE.search(sel.selection_name or "")
    side = sel.outcome_type.lower() if sel.outcome_type in ("Over", "Under") else None
    if side is None and name_match is None:
        return None
    if side is None:
        if name_match is None:
            return None
        side = name_match.group(1).lower()
    line = sel.value
    if line is None and name_match is not None:
        line = float(name_match.group(2))
    if line is None:
        return None
    return line, side


def _resolve_prop_line_side(
    sel: Selection, mt: MarketType,
) -> tuple[float | None, str] | None:
    """Translate a crypto.com player-prop selection to (line, side).

    Over/Under outcome rows use the stat line.  Yes/blank rows use the
    contract_type threshold (or YES_NO) *before* scanning the event name
    for ``Over 1.5``, so a Yes 2+ TD whose name happens to contain Over
    cannot steal the line.  Blank-outcome basketball rows still fall
    through to the name.  None means skip (No leg, missing line).
    """
    if sel.outcome_type in ("Over", "Under"):
        return _resolve_over_under_prop(sel)
    threshold = _yes_threshold_line_side(sel, mt)
    if threshold is not None:
        return threshold
    if sel.outcome_type == "No":
        return None
    over_under = _resolve_over_under_prop(sel)
    if over_under is not None:
        return over_under
    raise ValueError(
        f"crypto.com prop contract_type {sel.contract_type!r} has no "
        f"line/side rule — add one to _resolve_prop_line_side"
    )


def _player_prop_row(
    sel: Selection, cfg: CryptoConfig, *,
    start_date: str, home: str, away: str, league: str,
    player_aliases: Mapping[str, str],
    crypto_name_aliases: Mapping[str, str] = {},
) -> CanonicalRow | None:
    """Build a canonical row from a crypto.com player-prop selection.

    Returns None when the prop is not mappable: outside the prop period
    gate, or a contract type with no canonical target.  Unmapped prop
    types are SKIPPED, not raised — the OPPOSITE discipline to game
    lines.  crypto offers many prop types (shots, fouls, cards, …) we
    deliberately don't map yet, so the mapped set is a chosen subset of
    the offered set; raising would break the pipeline on every unmapped
    prop.  (For game lines the mapped set IS the offered set, so an
    unmapped game-line type is a feed change worth raising on.)

    A prop is PLAYER-scoped: the row keys on the player entity, not a
    team side, so there is no home/away team-identity resolution here.
    The entity is `player_aliases[player_id]` when an alias exists,
    else the `crypto_name_aliases` fallback (keyed on the normalized
    participant name), else normalize_player_name(participant) — the
    same merge key Optic and Kalshi emit, so a crypto prop merges onto
    theirs.  The alias map (config/<league>/player_aliases.toml,
    `crypto_id` key) covers players crypto spells differently from
    Optic: common/short names vs Optic's full registry names ("Almoez
    Ali" vs "Almoez Ali Zainalabedeen Mohamed Abdulla"), nicknames
    ("Gio Reyna" vs "Giovanni Reyna"), transliteration drift ("Xusanov"
    vs "Khusanov").  It is keyed on the feed's stable PLAYER_ID, so a
    crypto respelling can't silently detach an alias.

    Props sourced from processed_upstream_us.crypto_underlying_securities
    carry no PLAYER_ID (`sel.player_id is None`), so the id-keyed alias
    can't apply; the `crypto_name` submap (same TOML, `crypto_name` key)
    is the name-keyed fallback that re-applies the curated mappings for
    those rows.  A player matched by neither falls back to the name path
    and at worst stays novel.
    """
    if cfg.prop_period_type is None or not periods_match(
            sel.period, cfg.prop_period_type):
        return None
    mt = cfg.prop_contract_types.get(sel.contract_type)
    if mt is None:
        return None
    if sel.participant is None:
        raise ValueError(
            f"crypto.com player prop {sel.security_id!r} "
            f"({sel.contract_type!r}) has no participant to resolve"
        )

    resolved = _resolve_prop_line_side(sel, mt)
    if resolved is None:
        return None
    line, side = resolved
    normalized = normalize_player_name(sel.participant)
    alias = player_aliases.get(sel.player_id) if sel.player_id else None
    entity = alias or crypto_name_aliases.get(normalized) or normalized
    return CanonicalRow(
        league=league,
        start_date=start_date,
        home=home,
        away=away,
        market_type=mt.value,
        entity=entity,
        line=line,
        side=side,
        crypto_security_id=sel.security_id,
        crypto_symbol=sel.symbol,
        crypto_market_id=sel.crypto_market_id,
        crypto_outcome_id=sel.crypto_outcome_id,
        crypto_selection_name=sel.selection_name,
    )


def _resolve_fixture_team(
    team_id: str | None,
    aliases: Mapping[str, AliasValue],
    home: str,
    away: str,
) -> str | None:
    """Canonical abbrev when ``team_id`` aliases onto a fixture side."""
    if not team_id:
        return None
    try:
        entity = resolve_team(team_id, aliases)
    except ValueError:
        return None
    if entity in {home, away}:
        return entity
    return None


def _team_prop_entity(
    sel: Selection,
    *,
    home: str,
    away: str,
    aliases: Mapping[str, AliasValue],
) -> str | None:
    """Canonical abbrev for a Team Prop side, or None when it cannot bind.

    TEAM_ID aliases are flip-safe.  Nickname matching only selects the
    crypto home/away *slot*; the canonical comes from that slot's
    EXTERNAL_* id so a reversed listing cannot stamp Optic's other side.
    """
    bound = _resolve_fixture_team(sel.team_id, aliases, home, away)
    if bound is not None:
        return bound
    part = (sel.participant or "").strip()
    if not part:
        return None
    home_hit = feed_name_fits_team(part, sel.home_participant)
    away_hit = feed_name_fits_team(part, sel.away_participant)
    if home_hit and not away_hit:
        return _resolve_fixture_team(sel.external_home_id, aliases, home, away)
    if away_hit and not home_hit:
        return _resolve_fixture_team(sel.external_away_id, aliases, home, away)
    return None


def _team_prop_row(
    sel: Selection,
    cfg: CryptoConfig,
    *,
    start_date: str,
    home: str,
    away: str,
    league: str,
    aliases: Mapping[str, AliasValue],
    entity_names: Mapping[str, str] = {},
    skipped_name_mismatch: list[str] | None = None,
) -> CanonicalRow | None:
    """Build a canonical row from a crypto.com team-prop selection.

    Unmapped types and unresolvable sides are skipped, not raised.
    """
    if cfg.team_prop_period_type is None or not periods_match(
            sel.period, cfg.team_prop_period_type):
        return None
    mt = cfg.team_prop_contract_types.get(sel.contract_type)
    if mt is None:
        return None
    entity = _team_prop_entity(sel, home=home, away=away, aliases=aliases)
    if entity is None:
        return None
    if _skip_crossed_team_prop(
        sel, home=home, away=away, league=league, aliases=aliases,
        entity_names=entity_names, skipped_name_mismatch=skipped_name_mismatch,
    ):
        return None
    over_under = _resolve_over_under_prop(sel)
    if over_under is None:
        return None
    line, side = over_under
    return CanonicalRow(
        league=league,
        start_date=start_date,
        home=home,
        away=away,
        market_type=mt.value,
        entity=entity,
        line=line,
        side=side,
        crypto_security_id=sel.security_id,
        crypto_symbol=sel.symbol,
        crypto_market_id=sel.crypto_market_id,
        crypto_outcome_id=sel.crypto_outcome_id,
        crypto_selection_name=sel.selection_name,
    )


def _skip_crossed_team_prop(
    sel: Selection,
    *,
    home: str,
    away: str,
    league: str,
    aliases: Mapping[str, AliasValue],
    entity_names: Mapping[str, str],
    skipped_name_mismatch: list[str] | None,
) -> bool:
    """True when swapped crypto_ids would stamp the wrong team total."""
    sel_home = _resolve_fixture_team(sel.external_home_id, aliases, home, away)
    sel_away = _resolve_fixture_team(sel.external_away_id, aliases, home, away)
    if sel_home is None or sel_away is None:
        return False
    if not skip_crossed_stamp(
        sel.home_participant, sel.away_participant, sel_home, sel_away,
        entity_names, league=league,
    ):
        return False
    detail = (
        f"{sel.external_home_id}→{sel_home}/"
        f"{sel.external_away_id}→{sel_away} "
        f"{sel.home_participant!r}/{sel.away_participant!r}"
    )
    print(f"  crypto [{league}]: skipped crossed team prop {detail}", file=sys.stderr)
    if skipped_name_mismatch is not None:
        skipped_name_mismatch.append(detail)
    return True


def _skip_fight_prop(sel: Selection, reason: str) -> None:
    """Log an unmappable fight prop; the caller drops the selection."""
    print(
        f"  crypto [{sel.league}]: skipped fight prop "
        f"{sel.contract_type!r} ({reason}) for security "
        f"{sel.security_id!r}",
        file=sys.stderr,
    )


def _fight_prop_side_and_key(
    sel: Selection, mt: MarketType,
) -> tuple[str, str | None] | None:
    """Resolve (side, grouping_key) for a fight prop; None to skip it.

    Fight props are multi-outcome Yes questions: the PARTICIPANT label is
    the outcome identity and becomes ``grouping_key`` so distinct methods
    / rounds do not collide.  outcome_type never carries that identity —
    it is blank, Yes/No, or (since 2026-08-13) the Home/Away/Draw fighter
    the label already names — so it only picks the yes/no polarity.

    Unmappable legs are skipped, not raised: the fight-prop vocabulary is
    a chosen subset of a set crypto.com keeps extending, and one novel
    value must not cost the league every market's rows for the tick.
    """
    if sel.outcome_type not in (None, "Yes", "No", "Home", "Away", "Draw"):
        _skip_fight_prop(sel, f"novel outcome_type {sel.outcome_type!r}")
        return None
    side = "no" if sel.outcome_type == "No" else "yes"
    # Binary distance markets merge on (market_type, side) alone — do not
    # stamp a grouping_key from Yes/No participant text.
    if mt == MarketType.FIGHT_GOES_DISTANCE:
        return side, None
    label = (sel.participant or sel.selection_name or "").strip()
    if not label:
        _skip_fight_prop(sel, "no participant/name label")
        return None
    if mt == MarketType.ROUND_BETTING and is_roundless_win_label(label):
        _skip_fight_prop(sel, f"round not named in label {label!r}")
        return None
    return side, canonicalize_fight_prop_key(label)


def _three_way_prop_side(
    sel: Selection, home: str, away: str, aliases: Mapping[str, AliasValue],
) -> str | None:
    """Team or tie side for a Home / Away / Neither (No Goal) game prop.

    Home/Away are the selection's own event sides, resolved from the typed
    external team ids so a flipped listing cannot swap the teams.
    """
    if sel.outcome_type in ("Neither", "No Goal"):
        return TIE_SIDE
    if sel.outcome_type == "Yes":
        # Some feeds carry Yes + the team on PARTICIPANT / TEAM_ID; a Yes
        # with no team names no side and stays unmapped.
        return _team_prop_entity(sel, home=home, away=away, aliases=aliases)
    sel_home = _resolve_fixture_team(sel.external_home_id, aliases, home, away)
    sel_away = _resolve_fixture_team(sel.external_away_id, aliases, home, away)
    if sel_home is None or sel_away is None or sel_home == sel_away:
        return None
    return {"Home": sel_home, "Away": sel_away}.get(sel.outcome_type or "")


def _game_prop_outcome(
    sel: Selection,
    mt: MarketType,
    home: str,
    away: str,
    aliases: Mapping[str, AliasValue] = {},
    line: float | None = None,
) -> tuple[str, float | None, str | None] | None:
    """Resolve side/line/grouping_key for a mapped game or fight prop."""
    if mt.shape == Shape.THREE_WAY:
        side = _three_way_prop_side(sel, home, away, aliases)
        return None if side is None else (side, line, None)
    if sel.market_group == FIGHT_PROP:
        resolved = _fight_prop_side_and_key(sel, mt)
        if resolved is None:
            return None
        side, grouping_key = resolved
        return side, None, grouping_key
    if mt.shape == Shape.YES_NO:
        if sel.outcome_type is None:
            return None
        return _resolve_side(sel.outcome_type, home, away, mt.shape), None, None
    if mt.shape == Shape.TOTAL:
        if sel.outcome_type == "Yes":
            return "over", 0.5, None
        if sel.outcome_type == "No":
            return "under", 0.5, None
        return None
    raise ValueError(
        f"crypto.com game prop {sel.contract_type!r} maps to "
        f"{mt.value} ({mt.shape.name}); _game_prop_row handles YES_NO and TOTAL"
    )


def _game_prop_row(
    sel: Selection, cfg: CryptoConfig, *,
    start_date: str, home: str, away: str, league: str,
    aliases: Mapping[str, AliasValue] = {},
) -> CanonicalRow | None:
    """Build a canonical row from a crypto.com game/fight-prop selection.

    Soccer game props (e.g. BTTS) are game-scoped yes/no with no team
    side (entity=None, line=None, side=yes/no).  MLB "To Score A Run" @
    1st Inning maps onto Optic first_inning_total 0.5 (Yes=over, No=under).
    UFC fight props (round betting, distance) key their outcome on
    ``grouping_key`` — see _fight_prop_side_and_key.

    Returns None when the prop is not mappable: outside the game-prop
    period gate, a contract type with no canonical target, or a fight
    prop whose outcome cannot be identified.
    """
    # A period overlay (e.g. 1st-half BTTS) replaces the full-match gate.
    mt = _period_overlay_market_type(cfg, sel.period, sel.contract_type)
    if mt is None:
        if not _game_prop_period_ok(sel, cfg):
            return None
        mt = cfg.game_prop_contract_types.get(sel.contract_type)
    if mt is None:
        return None

    grouping_key: str | None = None
    line: float | None = None
    resolved = _game_prop_outcome(
        sel, mt, home, away, aliases, cfg.game_prop_lines.get(sel.contract_type))
    if resolved is None:
        return None
    side, line, grouping_key = resolved

    return CanonicalRow(
        league=league,
        start_date=start_date,
        home=home,
        away=away,
        market_type=mt.value,
        entity=None,
        line=line,
        side=side,
        grouping_key=grouping_key,
        crypto_security_id=sel.security_id,
        crypto_symbol=sel.symbol,
        crypto_market_id=sel.crypto_market_id,
        crypto_outcome_id=sel.crypto_outcome_id,
        crypto_selection_name=sel.selection_name,
    )


def build_rows(
    start_date: str,
    home: str,
    away: str,
    selections: list[Selection],
    cfg: CryptoConfig,
    *,
    aliases: Mapping[str, AliasValue],
    league: str,
    player_aliases: Mapping[str, str] = {},
    crypto_name_aliases: Mapping[str, str] = {},
    entity_names: Mapping[str, str] = {},
    fixture_names: Mapping[str, str] = {},
    strict_game_lines: bool = False,
    skipped_unmapped_game_lines: list[str] | None = None,
    skipped_name_mismatch: list[str] | None = None,
) -> list[CanonicalRow]:
    """Build canonical rows from a game's crypto.com selections.

    Each selection is one side of one line, so each produces one row
    (unlike Kalshi's yes/no split).  `home`/`away` are the fixture's
    canonical abbrevs and become the row's home/away — the merge key
    shared with the other exchanges, so they must stay in the fixture's
    orientation.  The bet's *side*, by contrast, is resolved from the
    selection's own event team IDs (sel.external_home_id /
    sel.external_away_id) via `aliases` — identity-based, so it stays
    correct even when crypto's home/away orientation is flipped relative
    to Optic (neutral-site games).  A guard skips (with an ALERT line) any
    selection whose two resolved teams are not exactly the fixture's
    {home, away}, so an alias or relabel mistake drops that bet rather
    than cross-wiring it or aborting the whole league.

    Three market groups produce rows, each on its own path and period
    gate: game lines (below), player props (`_player_prop_row`) and game
    props (`_game_prop_row`).  Game lines are filtered at the full-match
    period gate; an unmapped game-line contract_type is skipped in
    production (surfaced by gap-check as ``unmapped game line`` /
    vocabulary-drift alerts).  Pass ``strict_game_lines=True`` in tests
    to keep the old raise-on-novel behaviour.  Deliberately out-of-scope
    types belong in ``cfg.game_line_ignored``.  Half-periods, futures and
    unmapped props/game-props are skipped.

    Game-line rows are game-scoped, so entity is None.  Line semantics:
    None for moneyline and 3-way moneyline, signed for spread, unsigned
    threshold for totals (taken verbatim from the feed's value).  Player
    props are player-scoped (entity = the player) — see `_player_prop_row`.
    Game props are game-scoped yes/no questions with no team side
    (entity=None, line=None) — see `_game_prop_row`.
    """
    rows: list[CanonicalRow] = []
    side_mismatch: list[str] = []
    mismatch_teams: tuple[str, str] = ("", "")
    for sel in selections:
        # Game / fight props take a separate path: their own period gate,
        # a yes/no side, and (for fight props) grouping_key from the label.
        if sel.market_group in GAME_PROP_GROUPS:
            gp_row = _game_prop_row(
                sel, cfg, start_date=start_date,
                home=home, away=away, league=league, aliases=aliases)
            if gp_row is not None:
                rows.append(gp_row)
            continue

        # Player props take a separate path: their own period gate, a
        # player entity, and no team-side resolution.  (Futures/specials
        # were already dropped on read by to_selection_record.)
        if sel.market_group == PLAYER_PROP:
            prop_row = _player_prop_row(
                sel, cfg, start_date=start_date,
                home=home, away=away, league=league,
                player_aliases=player_aliases,
                crypto_name_aliases=crypto_name_aliases)
            if prop_row is not None:
                rows.append(prop_row)
            continue

        if sel.market_group == TEAM_PROP:
            team_row = _team_prop_row(
                sel, cfg, start_date=start_date,
                home=home, away=away, league=league, aliases=aliases,
                entity_names=entity_names,
                skipped_name_mismatch=skipped_name_mismatch)
            if team_row is not None:
                rows.append(team_row)
            continue

        if sel.market_group not in GAME_LINE_GROUPS:
            continue
        overlay_mt = _period_overlay_market_type(
            cfg, sel.period, sel.contract_type)
        if overlay_mt is None and not periods_match(
                sel.period, _game_line_period(cfg, sel.contract_type)):
            continue
        if sel.contract_type in cfg.game_line_ignored:
            continue

        mt = overlay_mt if overlay_mt is not None else cfg.contract_types.get(
            sel.contract_type)
        if mt is None:
            if strict_game_lines:
                raise ValueError(
                    f"unmapped crypto.com game-line contract_type "
                    f"{sel.contract_type!r} for {cfg.league} — add it to "
                    f"CryptoConfig.contract_types or confirm it's out of scope"
                )
            if skipped_unmapped_game_lines is not None:
                skipped_unmapped_game_lines.append(sel.contract_type)
            continue

        # Identity-based side: resolve the selection's own event team
        # IDs, never the fixture's position.  The guard ties the
        # selection to this game's two teams (and so to the right entry
        # after a flip).
        sel_home = resolve_team(sel.external_home_id, aliases)
        sel_away = resolve_team(sel.external_away_id, aliases)
        if skip_crossed_stamp(
            sel.home_participant, sel.away_participant, sel_home, sel_away,
            entity_names, league=league,
        ):
            detail = (
                f"{sel.external_home_id}→{sel_home}/"
                f"{sel.external_away_id}→{sel_away} "
                f"{sel.home_participant!r}/{sel.away_participant!r}"
            )
            print(
                f"  crypto [{league}]: skipped crossed crypto_id {detail}",
                file=sys.stderr,
            )
            if skipped_name_mismatch is not None:
                skipped_name_mismatch.append(detail)
            continue
        if {sel_home, sel_away} != {home, away}:
            # Was an assert: one unresolved id (Yibing Wu 730131 vs
            # atp_challenger YWI5, 2026-10-22) aborted every atp_challenger
            # row on every tick.  Skipping keeps the bet off the fixture
            # (no cross-wire); one ALERT per game is printed below.
            side_mismatch.append(sel.security_id)
            mismatch_teams = (sel_home, sel_away)
            continue

        if mt.scope == Scope.TEAM:
            # Team-scoped yes/no (e.g. To Advance): entity is the team,
            # side is always "yes" — crypto lists only the affirmative
            # leg, same as Optic to_advance.  outcome_type is Home/Away
            # (which team advances), not Yes/No; TEAM_ID is the stable
            # identity key (mirrors Kalshi's bare team-code suffix).
            if not sel.team_id:
                raise ValueError(
                    f"team-scoped {sel.contract_type!r} missing team_id "
                    f"for security {sel.security_id!r}")
            entity = resolve_team(sel.team_id, aliases)
            if entity not in {home, away}:
                raise ValueError(
                    f"crypto.com {sel.contract_type!r} team {entity!r} "
                    f"not in fixture {{{home}, {away}}}")
            if sel.outcome_type == "Home":
                if entity != sel_home:
                    raise ValueError(
                        f"Home to_advance team_id {entity!r} != "
                        f"selection home {sel_home!r}")
            elif sel.outcome_type == "Away":
                if entity != sel_away:
                    raise ValueError(
                        f"Away to_advance team_id {entity!r} != "
                        f"selection away {sel_away!r}")
            else:
                raise ValueError(
                    f"unexpected team-scoped {sel.contract_type!r} "
                    f"outcome_type {sel.outcome_type!r} for "
                    f"security {sel.security_id!r}")
            rows.append(CanonicalRow(
                league=league,
                start_date=start_date,
                home=home,
                away=away,
                market_type=mt.value,
                entity=entity,
                line=None,
                side="yes",
                crypto_security_id=sel.security_id,
                crypto_symbol=sel.symbol,
                crypto_market_id=sel.crypto_market_id,
                crypto_outcome_id=sel.crypto_outcome_id,
                crypto_selection_name=sel.selection_name,
            ))
            continue

        # UFC Fight Line moneylines leave outcome_type blank and stamp
        # the fighter on PARTICIPANT / PLAYER_ID.
        if sel.outcome_type is None and sel.market_group == FIGHT_LINE:
            side = _resolve_fight_moneyline_side(sel, sel_home, sel_away)
        else:
            # A mapped soccer/ball game line always carries an outcome;
            # only some player props leave it blank (see Selection.outcome_type).
            assert sel.outcome_type is not None, (
                f"game-line {sel.contract_type!r} has no outcome_type "
                f"for security {sel.security_id!r}"
            )
            side = _resolve_side(sel.outcome_type, sel_home, sel_away, mt.shape)
        if mt.shape in (Shape.MONEYLINE, Shape.SPREAD, Shape.THREE_WAY) and side not in {TIE_SIDE}:
            named = team_side(side, home=home, away=away)
            if named is None:
                raise ValueError(
                    f"crypto.com {sel.security_id!r} side {side!r} is not "
                    f"fixture {{{home}, {away}}}"
                )
            side = named
            if participant_contradicts_side(
                sel.participant, side, home=home, away=away,
                home_name=fixture_names.get(home, ""),
                away_name=fixture_names.get(away, ""), league=league,
            ):
                detail = f"{sel.symbol} participant={sel.participant!r} side={side}"
                print(f"  crypto [{league}]: skipped side/participant mismatch {detail}",
                      file=sys.stderr)
                if skipped_name_mismatch is not None:
                    skipped_name_mismatch.append(detail)
                continue
        # No line on the no-line shapes (moneyline, 3-way moneyline);
        # signed for spread, unsigned threshold for totals.
        no_line_shape = mt.shape in (Shape.MONEYLINE, Shape.THREE_WAY)
        line = None if no_line_shape else sel.value

        # A spread/total needs a numeric threshold, but crypto.com
        # occasionally lists one with an empty PREDICT_VALUE.  Such a row
        # is unusable, and a line-less spread also breaks the downstream
        # sort invariant (spreads pair by signed line).  Skip it in
        # production; raise under strict tests.
        if line is None and not no_line_shape:
            if strict_game_lines:
                raise ValueError(
                    f"crypto.com {sel.contract_type!r} maps to {mt.value} "
                    f"but carries no PREDICT_VALUE line for security "
                    f"{sel.security_id!r}"
                )
            print(
                f"  crypto [{league}]: skipped line-less {mt.value} "
                f"{sel.contract_type!r} (empty PREDICT_VALUE) for "
                f"security {sel.security_id!r}",
                file=sys.stderr,
            )
            continue

        rows.append(CanonicalRow(
            league=league,
            start_date=start_date,
            home=home,
            away=away,
            market_type=mt.value,
            entity=None,
            line=line,
            side=side,
            crypto_security_id=sel.security_id,
            crypto_symbol=sel.symbol,
            crypto_market_id=sel.crypto_market_id,
            crypto_outcome_id=sel.crypto_outcome_id,
            crypto_selection_name=sel.selection_name,
        ))

    if side_mismatch:
        # One line per game per tick: cron_pipeline.sh forwards only the
        # first 40 ALERT lines, so per-selection lines would crowd others out.
        print(
            f"ALERT: crypto [{league}]: skipped {len(side_mismatch)} "
            f"selection(s), teams {{{mismatch_teams[0]}, {mismatch_teams[1]}}} "
            f"!= fixture {{{home}, {away}}} (first security "
            f"{side_mismatch[0]!r})",
            file=sys.stderr,
        )
    return rows
