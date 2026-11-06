"""Optic fixtures+odds pipeline.

Parses Optic fixture JSONL, builds the game schedule index, builds
canonical rows from odds, and verifies Optic source_ids against our
PX/Kalshi matching (strip on hard mismatch by default — missing >
wrong; see ``optic_verify.verify_against_optic``).
"""

import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel

from mappers.fight_props import (
    canonicalize_fight_prop_key,
    is_emittable_method,
    parse_optic_mof_label,
    parse_optic_mov_name,
)
from mappers.market_types import MarketType, Scope, Shape
from mappers.optic_sides import fold_side
from mappers.shared import (
    FIXTURE_HORIZON_HOURS,
    TIE_SIDE,
    CanonicalRow,
    MatchKey,
    correct_score_line,
    double_chance_side,
    lines,
    margin_band_key,
    normalize_line,
    normalize_player_name,
    to_date_str,
    to_et_str,
)

# Optic API ids for /fixtures/odds requests.  Display names (the
# sportsbook field on each odd, and keys in merged source_ids) come
# from opticodds_sportsbooks — e.g. polymarket_usa_ → "Polymarket (USA)".
# crypto_com is requested so its native market_id can be decoded to a
# FIX Symbol; it is NOT in OPTIC_MAPPED_SPORTSBOOKS (that would collide
# with the FIX/hybrid crypto.com emit on the same MERGE key).
PREDICTION_MARKET_SPORTSBOOK_IDS = (
    "polymarket", "polymarket_usa_", "novig", "sx_bet", "crypto_com",
)

# Sportsbooks written to markets_us.market_mapping from optic_odds.source_ids.
# "SX Bet" added 2026-06-22 for the SX.bet RFQ tenant.  Optic's SX ids are
# {event_id: sportXeventId, market_id: <marketHash>, selection_id:
# "<marketHash>|one|two"} -- the suffix is the MAKER's outcome (a taker on
# outcome one lifts the "|two" odd; verified 2026-10-13).  Until ~2026-08 the
# selection_id was a rotating orderHash and unusable.  Optic carries SX for
# ~41% of SX's book, so mappers/exchanges/sxbet_pass.py maps the rest off
# SX's own catalogue and load_mappings emits those rows in the same shape.
# "Betfair Exchange" added 2026-10-07 for the orderbook platform's Betfair adapter:
# Optic's betfair_exchange odds (already fetched, SPORTSBOOK_BATCHES) carry Betfair's
# own event_id / market_id ("1.xxx") / selection_id, which is the key a Betfair
# Exchange book is subscribed and joined on. Only the back book is mapped; the
# _lay_ and Australian ids are the same markets and are not fetched.
OPTIC_MAPPED_SPORTSBOOKS = frozenset({
    "Polymarket",
    "Novig",
    "Polymarket (USA)",
    "SX Bet",
    "DraftKings",
    "Betfair Exchange",
})

# Display name for Optic's crypto_com sportsbook (source_ids key after dedup).
CRYPTO_COM_SPORTSBOOK = "crypto.com"

# Sportsbooks whose per-odd source_ids we preserve when deduplicating
# the multi-sportsbook fetch in fetch/optic.py.
EXCHANGE_SOURCE_ID_SPORTSBOOKS = frozenset({
    "Kalshi",
    "Prophet X",
    CRYPTO_COM_SPORTSBOOK,
}) | OPTIC_MAPPED_SPORTSBOOKS


# === League config ===

@dataclass(frozen=True)
class OpticConfig:
    """League-specific constants for Optic fixture filtering and classification."""
    league_id: str                             # e.g. "nba"
    table_types: dict[str, MarketType]         # optic market_id -> MarketType
    # Unconditional abbreviation overrides keyed by Optic competitor id.
    # If a competitor's id is listed, its Optic abbreviation is never
    # consulted — so a later upstream backfill/edit cannot shift the
    # canonical.  Added for World Cup 2026: Optic ships an empty
    # abbreviation for the three WC debutants (Haiti, Curacao,
    # New Zealand; probed 2026-06-07), and the pipeline keys teams by
    # Optic abbreviation.  Keyed by competitor id, not name, because
    # names are also subject to upstream edits (e.g. a diacritic fix
    # to "Curacao").
    abbr_overrides: dict[str, str] = field(default_factory=dict)
    # Optic fixture fetch window: only games starting within this many
    # hours of fetch time are requested from the API, and the pipeline
    # excuses missing matches beyond it (absence is expected, not an
    # error).  Per-league so both sides read the same value — a
    # fetch-side-only override would make the diagnostics judge old
    # data against the wrong window.  The World Cup runs 96h: a dense
    # fixed schedule, fully quoted well ahead.
    horizon_hours: float = FIXTURE_HORIZON_HOURS
    # Additional Optic league ids folded into this league.  Optic
    # sometimes carves special events out of the main league into a
    # tiny league of their own (e.g. the WNBA All-Star game lives in
    # "usa_-_wnba_all_star", not "wnba") while every other exchange
    # keeps them under the parent league.  Ids listed here are fetched
    # alongside league_id (the /fixtures/active endpoint accepts
    # repeated league params — verified live 2026-07-25) and their
    # fixtures join the same index, so the rest of the pipeline treats
    # them as ordinary fixtures of this league.
    extra_league_ids: tuple[str, ...] = ()


# === Models ===

class Competitor(BaseModel):
    id: str
    abbreviation: str
    name: str


class Odd(BaseModel):
    """One side of one bet from the Optic odds feed."""
    model_config = {"extra": "allow"}

    id: str
    market: str = ""
    market_id: str
    name: str = ""
    selection: str = ""
    normalized_selection: str = ""
    selection_line: str | None = None
    points: float | None = None
    team_id: str | None = None
    player_id: str | None = None
    grouping_key: str
    source_ids: dict = {}


class Game(BaseModel):
    """One game from the Optic fixtures+odds feed.

    We fetch from /fixtures/active, so games are either "unplayed" or
    "live".  Across all historical data (1134 fixtures) these are the
    only two (status, is_live) pairs observed:
        ("unplayed", False) — 1085
        ("live",     True)  —   49
    Live games are loaded into the schedule index so that PX/Kalshi
    events can match them (avoiding false "missing fixture" warnings).
    The pipeline emits those rows; load_mappings inserts unmatched
    keys only (Optic is_live, not start_date).
    """
    model_config = {"extra": "allow"}

    id: str
    game_id: str
    start_date: str
    status: str
    is_live: bool
    home_competitors: list[Competitor]
    away_competitors: list[Competitor]
    league: dict = {}
    odds: list[Odd] = []
    # Fixture-level cross-feed ids when fetched with
    # include_sportradar_id=true (e.g. {"sportradar_id":
    # "sr:fixture:66456904"}).  fetch/optic.py carries this over from
    # the /fixtures/active response — the /fixtures/odds record it is
    # otherwise built from has no fixture-level source_ids.  Empty on
    # data fetched before that change.
    source_ids: dict = {}


class GameRef(NamedTuple):
    """Game-level Optic IDs, associated with each matched odd."""
    fixture_id: str
    game_id: str


class Fixture(NamedTuple):
    """One Optic game: schedule info + odds, ET-converted.

    Clean, validated form of an Optic Game. A doubles side is folded
    to one pair before this is built. Converts start time to Eastern
    and pre-builds the team_map for resolving odd.team_id to abbreviation.
    """
    fixture_id: str            # Optic's top-level id
    game_id: str               # Optic's game_id
    # Bare Sportradar integer (prefix stripped), e.g. "66456904", or
    # None when absent.  The exact event join for Huddle, whose
    # betradar.event.extId equals this value — see docs/adding-huddle.md.
    sportradar_id: str | None
    start_et: str              # full ET datetime, e.g. "2026-02-27T19:00:00"
    start_date: str            # raw UTC ISO timestamp, e.g. "2026-02-26T01:00:00Z"
    home: str                  # canonical abbrev, e.g. "IND"
    away: str                  # canonical abbrev, e.g. "CHA"
    home_name: str             # full name, e.g. "Indiana Pacers"
    away_name: str             # full name, e.g. "Charlotte Hornets"
    team_map: dict[str, str]   # {optic_team_id: abbreviation}
    odds: list[Odd]            # all odds (game + player)
    is_live: bool              # True when Optic status == "live"
    # Optic competitor abbreviations before optic_id → canonical rewrite.
    # Book codes (Kalshi / Poly USA / PX) often still emit these.
    home_optic_abbr: str = ""
    away_optic_abbr: str = ""
    league_id: str = ""        # Optic league id, e.g. "germany_-_dfb_pokal"
    season_type: str = ""      # Optic stage label ("" when absent)


# === Parsing ===

def _strip_sr_prefix(sr: str | None) -> str | None:
    """Strip Optic's sr:(fixture|match): prefix to the bare integer id.

    Optic returns source_ids.sportradar_id as a prefixed string —
    "sr:fixture:66456904" for soccer, "sr:match:52864807" for NBA.  The
    prefix varies by sport/entity; the trailing integer is the id Huddle
    carries as betradar.event.extId.  Returns None if absent.
    """
    if not sr:
        return None
    return sr.rsplit(":", 1)[-1]


def _folded_competitor(
    competitors: list[Competitor],
) -> tuple[Competitor, list[str]]:
    """One side entity plus every id that should resolve to its code."""
    folded = fold_side([
        {"id": c.id, "name": c.name, "abbreviation": c.abbreviation}
        for c in competitors
    ])
    if folded is None:
        raise ValueError(
            f"Expected at least 1 competitor, got {len(competitors)}")
    comp = Competitor(
        id=str(folded["id"]),
        name=str(folded["name"]),
        abbreviation=str(folded["abbreviation"]),
    )
    members = [str(oid) for oid in folded["member_ids"] if oid]
    if comp.id and comp.id not in members:
        members.append(comp.id)
    return comp, members


def _member_names(
    competitors: list[Competitor], code: str,
) -> tuple[tuple[str, str], ...]:
    """Each player's name on a side, mapped to that side's code."""
    return tuple((c.name, code) for c in competitors if c.name)


def parse_game(line: str) -> Game:
    """Parse an Optic game from a JSONL line."""
    return Game(**json.loads(line))


def _canonical_abbr(comp: Competitor, cfg: OpticConfig) -> str:
    """Resolve canonical abbreviation for a competitor."""
    if comp.id in cfg.abbr_overrides:
        return cfg.abbr_overrides[comp.id]
    abbr = (comp.abbreviation or "").strip()
    if abbr:
        return abbr
    raise ValueError(
        f"Optic competitor {comp.name!r} (id={comp.id!r}) has an empty "
        f"abbreviation for league {cfg.league_id!r}"
    )


def _norm_side_name(name: str) -> str:
    """Casefolded, whitespace-collapsed participant name for side matching."""
    return " ".join((name or "").split()).casefold()


def _side_name_codes(
    home_name: str, home: str, away_name: str, away: str,
    extra: tuple[tuple[str, str], ...] = (),
) -> dict[str, str]:
    """Participant name → abbreviation for the fixture's two sides.

    Empty when both sides normalize to the same name (or one is blank),
    since no name match can then tell the two apart. Extra names are
    the members of a pair, so a selection of one player still hits.
    """
    by_name = {
        key: code
        for key, code in (
            (_norm_side_name(home_name), home),
            (_norm_side_name(away_name), away),
        )
        if key
    }
    if len(by_name) != 2:
        return {}
    for name, code in extra:
        key = _norm_side_name(name)
        if key and key not in by_name:
            by_name[key] = code
    return by_name


def _odds_team_aliases(
    odds: list[Odd],
    team_map: dict[str, str],
    *,
    home_name: str,
    home: str,
    away_name: str,
    away: str,
    extra_names: tuple[tuple[str, str], ...] = (),
) -> dict[str, str]:
    """Map odds-side competitor ids onto the fixture's own two teams.

    Optic identifies a participant by a per-competition competitor RECORD
    (``id``), not by the underlying entity (``base_id``): Bournemouth is
    "AFC Bournemouth" F2CCF38E0A5A in the Premier League and "Bournemouth"
    CDE44712BC73 in Club Friendlies, both base_id 3859.  A fixture's odds
    can cite a different record of a participant than the fixture's own
    competitor list — live on Club Friendlies (Bournemouth, 2026-07-30) and
    ITF Women (Jo-Yee Chan, 2026-07-31), where EVERY priced row for that
    side used an id the fixture never carried.  team_map is keyed on the
    fixture's two ids, so those odds raised KeyError in build_rows and took
    the whole multi-league run down with them.

    The odds payload carries no base_id, so ``selection`` — the bare
    participant name, undecorated even on spread and correct-score rows —
    is the only signal available.  An id is claimed only on an unambiguous
    name match; anything else is left out for build_rows to skip rather
    than guessed at, since a wrong side is worse than a missing row.
    """
    by_name = _side_name_codes(
        home_name, home, away_name, away, extra_names,
    )
    if not by_name:
        return {}

    aliases: dict[str, str] = {}
    for odd in odds:
        team_id = odd.team_id
        if not team_id or team_id in team_map or team_id in aliases:
            continue
        code = by_name.get(_norm_side_name(odd.selection))
        if code is not None:
            aliases[team_id] = code
    return aliases


def _utc_ymd(start_date: str) -> str:
    """YYYYMMDD from an Optic UTC start, or '' if the prefix is unparseable."""
    s = str(start_date).strip().replace(" ", "T", 1)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:4] + s[5:7] + s[8:10]
    return ""


def _fixture_id_matches_start(fx: Fixture) -> bool:
    """True when the id's YYYYMMDD prefix matches start_date's UTC date."""
    ymd = _utc_ymd(fx.start_date)
    return bool(ymd) and fx.fixture_id[:8] == ymd


def _clone_keep_rank(fx: Fixture, status: str) -> tuple[int, int, str]:
    """Lower tuple wins: live > completed > delayed > unplayed > cancelled.

    Completed beat delayed: that board already went live and finished.
    Delayed still beats leftover unplayed. Cancelled is inactive.
    Unplayed is indecisive — keep it only when no sure-active clone
    exists, then date-prefix / id.
    """
    st = (status or "").strip().lower()
    if fx.is_live or st == "live":
        band = 0
    elif st == "completed":
        band = 1
    elif st == "delayed":
        band = 2
    elif st == "cancelled":
        band = 4
    else:
        band = 3
    prefix_miss = 0 if _fixture_id_matches_start(fx) else 1
    return (band, prefix_miss, fx.fixture_id)


def _pick_clone_winner(
    group: list[tuple[Fixture, str]],
) -> tuple[Fixture, list[Fixture]]:
    """Best clone in *group*; losers are the rest (same game_id)."""
    ranked = sorted(group, key=lambda row: _clone_keep_rank(row[0], row[1]))
    winner = ranked[0][0]
    return winner, [fx for fx, _ in ranked[1:]]


def _collapse_game_id_clones(
    rows: list[tuple[Fixture, str]],
) -> list[Fixture]:
    """Keep one Fixture per game_id; log dropped Optic clone ids."""
    by_gid: dict[str, list[tuple[Fixture, str]]] = defaultdict(list)
    for fx, status in rows:
        by_gid[fx.game_id].append((fx, status))
    kept: list[Fixture] = []
    for gid, group in by_gid.items():
        if len(group) == 1:
            kept.append(group[0][0])
            continue
        winner, losers = _pick_clone_winner(group)
        for fx in losers:
            print(
                f"  optic: collapse clone {fx.fixture_id} \u2192 "
                f"{winner.fixture_id} game_id={gid}",
                file=sys.stderr,
            )
        kept.append(winner)
    return kept


def _index_fixtures(fixtures: list[Fixture]) -> dict[MatchKey, list[Fixture]]:
    """Group fixtures by (ET date, home, away); DH lists stay intact."""
    index: dict[MatchKey, list[Fixture]] = {}
    for fx in fixtures:
        key = MatchKey(to_date_str(fx.start_et), fx.home, fx.away)
        index.setdefault(key, []).append(fx)
    return index


def _fixture_from_game(game: Game, cfg: OpticConfig) -> Fixture | None:
    """Validate one Optic Game into a Fixture, or None if out of league."""
    if game.league.get("id") not in (cfg.league_id, *cfg.extra_league_ids):
        return None
    home_comp, home_ids = _folded_competitor(game.home_competitors)
    away_comp, away_ids = _folded_competitor(game.away_competitors)
    start_et = to_et_str(game.start_date)
    home = _canonical_abbr(home_comp, cfg)
    away = _canonical_abbr(away_comp, cfg)
    home_oa = (home_comp.abbreviation or "").strip() or home
    away_oa = (away_comp.abbreviation or "").strip() or away
    team_map = dict.fromkeys(home_ids, home)
    team_map.update(dict.fromkeys(away_ids, away))
    team_map.update(_odds_team_aliases(
        game.odds, team_map,
        home_name=home_comp.name, home=home,
        away_name=away_comp.name, away=away,
        extra_names=_member_names(game.home_competitors, home)
        + _member_names(game.away_competitors, away),
    ))
    return Fixture(
        fixture_id=game.id,
        game_id=game.game_id,
        sportradar_id=_strip_sr_prefix(game.source_ids.get("sportradar_id")),
        start_et=start_et,
        start_date=game.start_date,
        home=home,
        away=away,
        home_name=home_comp.name,
        away_name=away_comp.name,
        team_map=team_map,
        odds=game.odds,
        is_live=game.is_live,
        home_optic_abbr=home_oa,
        away_optic_abbr=away_oa,
        league_id=str(game.league.get("id") or ""),
        # Stage label ("Regular Season", "Group Stage", "Round 2"), kept as an
        # extra so a non-string value cannot fail the whole league's parse.
        season_type=str((game.model_extra or {}).get("season_type") or "").strip(),
    )


def _drop_foreign_odds(
    rows: list[tuple[Fixture, str]],
) -> list[tuple[Fixture, str]]:
    """Remove odds that carry a *different loaded game's* id prefix.

    Optic odd ids are ``{game_id}:{sportsbook}:{market}:{selection}``.  On
    2026-10-09 /fixtures/odds returned Colorado @ Dallas' ten odds inside the
    next night's Dallas @ Colorado fixture.  Odd ids are the key of the
    pipeline's odd/game-ref lookups, so the later fixture won each id and the
    earlier game's rows were stamped with the wrong game_id/fixture_id on
    every venue.

    Only a prefix equal to another game in this batch is treated as foreign.
    A prefix no loaded game owns is a reschedule leftover (the odd keeps the
    original date after the game_id moved) and is left alone.  Clones share a
    game_id, so their own odds are never foreign to each other.
    """
    owned = {fx.game_id for fx, _ in rows}
    out: list[tuple[Fixture, str]] = []
    for fx, status in rows:
        kept = [
            odd for odd in fx.odds
            if (prefix := odd.id.split(":", 1)[0]) == fx.game_id
            or prefix not in owned
        ]
        if len(kept) != len(fx.odds):
            print(
                f"  optic: fixture {fx.fixture_id} ({fx.game_id}): dropped "
                f"{len(fx.odds) - len(kept)} foreign odds carrying another "
                f"loaded game's id",
                file=sys.stderr,
            )
            fx = fx._replace(odds=kept)
        out.append((fx, status))
    return out


def load_fixtures(
    source: str | Path | Iterable[str],
    cfg: OpticConfig,
) -> dict[MatchKey, list[Fixture]]:
    """Parse Optic JSONL into an index of validated Fixture objects.

    Live games stay in the index so PX/Kalshi/crypto can match them;
    load_mappings inserts unmatched keys only for Optic-live game_ids.
    Same-day doubleheaders (same MatchKey, different game_id) stay as
    a list. Two fixture ids that share game_id are clones: one winner
    is kept (live > completed > delayed > unplayed > cancelled).
    See mappers/docs/optic-game-id-clones.md.
    """
    loaded: list[tuple[Fixture, str]] = []
    line_iter = lines(Path(source)) if isinstance(source, (str, Path)) else source
    for line in line_iter:
        game = Game(**json.loads(line))
        fixture = _fixture_from_game(game, cfg)
        if fixture is None:
            continue
        loaded.append((fixture, game.status or ""))
    loaded = _drop_foreign_odds(loaded)
    return _index_fixtures(_collapse_game_id_clones(loaded))


# === Canonical row builder ===

def _team_map_required(mt: MarketType) -> bool:
    """True when build_rows resolves odd.team_id through team_map.

    Player props and H2H rows carry a team_id but take their entity from
    the selection name, so an id missing from team_map costs them nothing
    and must not drop the row.
    """
    if mt.shape in (Shape.MONEYLINE, Shape.SPREAD, Shape.THREE_WAY,
                    Shape.CORRECT_SCORE):
        return True
    return mt.shape in (Shape.TOTAL, Shape.YES_NO) and mt.scope == Scope.TEAM


def _side_code(
    odd: Odd, team_map: dict[str, str], name_codes: dict[str, str],
) -> str | None:
    """The odd's side as a canonical abbreviation, None when unresolvable.

    Optic also omits team_id altogether on some 2-way moneyline odds — 7 of
    38 boxing_matches moneyline odds on the 2026-08-08 card, both fighters,
    every book — which used to assert in build_rows and abort the whole
    multi-league run.  The selection still names the participant, the same
    signal _odds_team_aliases recovers a foreign competitor record from, so
    resolve through it rather than dropping a priced side.
    """
    if odd.team_id is not None:
        return team_map.get(odd.team_id)
    return name_codes.get(_norm_side_name(odd.selection))


def _side_or_tie(side_code: str | None, is_draw_leg: bool) -> str:
    """The odd's side, or TIE_SIDE for a 3-way / correct-score draw leg."""
    if is_draw_leg:
        return TIE_SIDE
    assert side_code is not None
    return side_code


_DOUBLE_CHANCE_DRAW_NAMES = frozenset({"draw", "tie"})


def _double_chance_name_codes(
    fixture: Fixture, name_codes: dict[str, str],
) -> dict[str, str]:
    """name_codes plus each side's own moneyline selection name.

    Double chance odds name both outcomes ("England Or Draw") and carry no
    usable team_id, so they resolve by name. The moneyline selections are
    Optic's own spelling of the same sides.
    """
    codes = dict(name_codes)
    clashes: set[str] = set()
    for odd in fixture.odds:
        if odd.market_id != "moneyline" or not odd.team_id:
            continue
        code = fixture.team_map.get(odd.team_id)
        key = _norm_side_name(odd.selection)
        if code is None or not key:
            continue
        if codes.get(key, code) != code:
            clashes.add(key)
        codes[key] = code
    for key in clashes:
        codes.pop(key, None)
    return codes


def _double_chance_side(
    selection: str | None, name_codes: dict[str, str], home: str, away: str,
) -> str | None:
    """Optic "England Or Draw" / "England Or Spain" as a canonical side.

    Tries every " or " split, so a team name containing "or" still parses.
    None unless exactly one split names two distinct outcomes of this game.
    """
    def outcome(name: str) -> str | None:
        if name in _DOUBLE_CHANCE_DRAW_NAMES:
            return TIE_SIDE
        return name_codes.get(name)

    outcomes = {home, away, TIE_SIDE}
    norm = _norm_side_name(selection or "")
    sep = " or "
    found: set[str] = set()
    at = norm.find(sep)
    while at != -1:
        a, b = outcome(norm[:at]), outcome(norm[at + len(sep):])
        if a in outcomes and b in outcomes and a != b:
            found.add(double_chance_side({a, b}, home, away))
        at = norm.find(sep, at + 1)
    return found.pop() if len(found) == 1 else None


_KILLS_ODD_TYPES = frozenset(MarketType[f"MAP_{n}_KILLS_ODD"] for n in range(1, 6))
_ODD_EVEN_SIDES = {"odd": "yes", "even": "no"}
_QUARTER_KEYS = {
    "1st_quarter": "q1", "2nd_quarter": "q2", "3rd_quarter": "q3", "4th_quarter": "q4",
}
_OUTCOME_YES_NO_TYPES = _KILLS_ODD_TYPES | {
    MarketType.HALFTIME_FULLTIME, MarketType.HIGHEST_SCORING_QUARTER,
}


def _htft_key(selection: str | None, name_codes: dict[str, str]) -> str | None:
    """Optic "Arizona Cardinals :: Draw" as ``"<1H side>|<full-time side>"``."""
    parts = (selection or "").split(" :: ")
    if len(parts) != 2:
        return None
    sides = []
    for part in parts:
        norm = _norm_side_name(part)
        side = TIE_SIDE if norm in _DOUBLE_CHANCE_DRAW_NAMES else name_codes.get(norm)
        if side is None:
            return None
        sides.append(side)
    return "|".join(sides)


def _outcome_yes_no(
    mt: MarketType, odd: Odd, name_codes: dict[str, str],
) -> tuple[str, str | None] | None:
    """(side, grouping_key) of a game yes/no Optic lists as named outcomes.

    Odd/even kills: Odd is the Yes. Highest-scoring quarter and halftime /
    full time: one affirmative per outcome, the outcome in grouping_key.
    None when the selection does not parse.
    """
    selection = (odd.normalized_selection or "").strip().casefold()
    if mt in _KILLS_ODD_TYPES:
        side = _ODD_EVEN_SIDES.get(selection)
        return (side, None) if side else None
    if mt is MarketType.HIGHEST_SCORING_QUARTER:
        key = _QUARTER_KEYS.get(selection)
        return ("yes", key) if key else None
    key = _htft_key(odd.selection, name_codes)
    return ("yes", key) if key else None


def _race_to_points_line(odd: Odd, mt: MarketType) -> float | None:
    """Points target for Optic ``race_to_N_points`` (catalog + Poly US Path 2)."""
    if mt is not MarketType.RACE_TO_POINTS:
        return None
    if odd.points is not None:
        return float(odd.points)
    match = re.fullmatch(r"race_to_(\d+)_points", odd.market_id)
    return float(match.group(1)) if match else None


_MARGIN_BAND_RE = re.compile(r"(\d+)(?:-(\d+)|\+)")


def _winning_margin_key(odd: Odd) -> str | None:
    """Optic ``winning_margin`` band (selection_line "11-20", "21+") as its grouping_key."""
    match = _MARGIN_BAND_RE.fullmatch((odd.selection_line or "").strip())
    if match is None:
        return None
    high = match.group(2)
    return margin_band_key(int(match.group(1)), int(high) if high else None)


def _report_unresolved_sides(
    unresolved_ids: dict[str, str],
    unresolved_names: dict[str, int],
    *,
    league: str,
    fixture: Fixture,
    home: str,
    away: str,
) -> None:
    """Alert on odds build_rows dropped because their side didn't resolve."""
    where = f"optic [{league}] fixture {fixture.fixture_id} ({away}@{home})"
    if unresolved_ids:
        detail = ", ".join(
            f"{team_id} ({selection or 'blank selection'})"
            for team_id, selection in sorted(unresolved_ids.items()))
        print(f"  {where}: skipped odds for {len(unresolved_ids)} "
              f"competitor id(s) absent from the fixture: {detail}",
              file=sys.stderr)
    if unresolved_names:
        detail = ", ".join(
            f"{selection or 'blank selection'} (x{count})"
            for selection, count in sorted(unresolved_names.items()))
        print(f"  {where}: skipped {sum(unresolved_names.values())} odd(s) "
              f"with no team_id whose selection matched neither side: "
              f"{detail}", file=sys.stderr)


# Optic prices "to score anytime" as its own market, but it is the same
# bet as player_goals over 0.5.  Folded onto that row only for players
# the fixture has no player_goals 0.5 odd for, so a book quoting both
# never double-counts (or collides on) one real-world question.
ANYTIME_GOAL_SCORER = "anytime_goal_scorer"
_ANYTIME_LINE = 0.5


def _anytime_covered_players(odds: list[Odd], cfg: OpticConfig) -> set[str]:
    """Players that already have a player_goals 0.5 odd in this fixture."""
    if "player_goals" not in cfg.table_types:
        return set()
    return {
        normalize_player_name(o.selection)
        for o in odds
        if o.market_id == "player_goals" and o.points == _ANYTIME_LINE
    }


def _fold_anytime(
    odd: Odd, covered: set[str],
) -> tuple[str, float, str] | None:
    """(entity, line, side) for an anytime odd on player_goals, or None.

    Optic ships the affirmative leg with a blank selection_line; an
    explicit yes/no is honoured.  Anything else is skipped.
    """
    entity = normalize_player_name(odd.selection)
    if entity in covered:
        return None
    token = (odd.selection_line or "").strip().casefold()
    if token in ("", "yes", "over"):
        return entity, _ANYTIME_LINE, "over"
    if token in ("no", "under"):
        return entity, _ANYTIME_LINE, "under"
    return None


def build_rows(
    start_date: str,
    home: str,
    away: str,
    fixture: Fixture,
    cfg: OpticConfig,
    *,
    league: str,
) -> tuple[list[CanonicalRow], dict[str, Odd], dict[str, GameRef]]:
    """Build flat canonical rows from an Optic fixture's odds.

    Filters to the types in cfg.table_types.
    Each odd is one side of one bet — already flat with half-point
    lines and signed spreads.

    Returns (rows, odd_lookup, game_ref_lookup) where:
      odd_lookup maps optic_id → Odd (for verification and JSON output)
      game_ref_lookup maps optic_id → GameRef (game-level Optic IDs)
    """
    team_map = fixture.team_map
    name_codes = _side_name_codes(
        fixture.home_name, fixture.home, fixture.away_name, fixture.away)
    dc_name_codes: dict[str, str] | None = None
    game_ref = GameRef(fixture_id=fixture.fixture_id, game_id=fixture.game_id)

    rows: list[CanonicalRow] = []
    odds_used: list[Odd] = []
    odd_lookup: dict[str, Odd] = {}
    game_ref_lookup: dict[str, GameRef] = {}
    unresolved_team_ids: dict[str, str] = {}
    unresolved_selections: dict[str, int] = {}
    skipped_malformed: dict[str, int] = {}

    anytime_covered = _anytime_covered_players(fixture.odds, cfg)

    for odd in fixture.odds:
        mt = cfg.table_types.get(odd.market_id)
        anytime = mt is None and odd.market_id == ANYTIME_GOAL_SCORER
        if anytime:
            mt = cfg.table_types.get("player_goals")
        if mt is None:
            continue

        # A 3-way / correct-score leg with no team_id (null or blank) is
        # the draw, which takes TIE_SIDE below instead of a side of its
        # own. Live Optic Draw rows often store team_id as "" in BQ.
        side_code = _side_code(odd, team_map, name_codes)
        is_draw_leg = not odd.team_id and mt.shape in (
            Shape.THREE_WAY, Shape.CORRECT_SCORE)

        # Odds citing a competitor record the fixture doesn't carry, or no
        # competitor at all, that the selection name could not resolve
        # either.  Skip the odd instead of raising: one Optic-side id fault
        # must not abort the whole run, and dropping is fail-safe where
        # guessing is not.
        if side_code is None and _team_map_required(mt) and not is_draw_leg:
            if odd.team_id is None:
                unresolved_selections[odd.selection] = (
                    unresolved_selections.get(odd.selection, 0) + 1)
            else:
                unresolved_team_ids.setdefault(odd.team_id, odd.selection)
            continue

        entity = None
        line = None
        side: str
        grouping_key: str | None = None

        if anytime:
            folded = _fold_anytime(odd, anytime_covered)
            if folded is None:
                continue
            entity, line, side = folded

        elif mt.shape == Shape.MONEYLINE:
            if side_code is None:
                skipped_malformed[odd.market_id] = (
                    skipped_malformed.get(odd.market_id, 0) + 1)
                continue
            side = side_code

        elif mt.shape == Shape.SPREAD:
            if side_code is None or odd.points is None:
                skipped_malformed[odd.market_id] = (
                    skipped_malformed.get(odd.market_id, 0) + 1)
                continue
            side = side_code
            line = odd.points  # signed (positive = underdog)

        elif mt.shape == Shape.TOTAL:
            if mt.scope == Scope.TEAM and side_code is None:
                skipped_malformed[odd.market_id] = (
                    skipped_malformed.get(odd.market_id, 0) + 1)
                continue
            if (
                odd.selection_line not in ("over", "under")
                or odd.points is None
                or odd.points < 0
            ):
                skipped_malformed[odd.market_id] = (
                    skipped_malformed.get(odd.market_id, 0) + 1)
                continue
            if mt.scope == Scope.TEAM:
                entity = side_code
            side = odd.selection_line
            line = odd.points

        elif mt.shape == Shape.THREE_WAY:
            # Optic 3-way draw odds have team_id=null or blank (and
            # selection="Draw").  Consistent across 4 dates of
            # live data (32 games, all 3-way period variants).
            side = _side_or_tie(side_code, is_draw_leg)
            line = _race_to_points_line(odd, mt)

        elif mt.shape == Shape.CORRECT_SCORE:
            # selection_line = "<own_goals>:<opponent_goals>" for the
            # anchor team (team_id set), or "<N>:<N>" for a Draw (team_id
            # null) -- wave-rescue-probe-findings.md section B.1. side
            # resolves off team_id exactly like the THREE_WAY branch above
            # (never off the selection name string, which is redundant with
            # team_id here). line packs the winner-anchored scoreline via
            # the SAME encoding polymarket.build_rows' EXACT_SCORE branch
            # uses (correct_score_line) so the two exchanges' rows collide
            # on (market_type, entity, line, side).
            assert odd.selection_line is not None
            w_str, l_str = odd.selection_line.split(":", 1)
            winner_goals, loser_goals = int(w_str), int(l_str)
            side = _side_or_tie(side_code, is_draw_leg)
            line = correct_score_line(winner_goals, loser_goals)

        elif mt.shape == Shape.DOUBLE_CHANCE:
            if dc_name_codes is None:
                dc_name_codes = _double_chance_name_codes(fixture, name_codes)
            dc_side = _double_chance_side(
                odd.selection, dc_name_codes, home, away)
            if dc_side is None:
                skipped_malformed[odd.market_id] = (
                    skipped_malformed.get(odd.market_id, 0) + 1)
                continue
            side = dc_side

        elif mt.shape == Shape.OVER_UNDER:
            if (
                odd.selection_line not in ("over", "under")
                or odd.points is None
                or odd.points < 0
            ):
                skipped_malformed[odd.market_id] = (
                    skipped_malformed.get(odd.market_id, 0) + 1)
                continue
            entity = normalize_player_name(odd.selection) \
                if mt.scope == Scope.PLAYER else None
            side = odd.selection_line
            line = odd.points

        elif mt in _OUTCOME_YES_NO_TYPES:
            if dc_name_codes is None:
                dc_name_codes = _double_chance_name_codes(fixture, name_codes)
            outcome = _outcome_yes_no(mt, odd, dc_name_codes)
            if outcome is None:
                skipped_malformed[odd.market_id] = (
                    skipped_malformed.get(odd.market_id, 0) + 1)
                continue
            side, grouping_key = outcome

        elif mt.shape == Shape.YES_NO:
            if mt == MarketType.METHOD_OF_VICTORY:
                # Fighter-scoped: entity from team_id/selection, method
                # from "Fighter - Method" name suffix.  Skip Draw and
                # composite Optic buckets.  Emit ``ko_tko`` (no DQ) for
                # Polymarket US ``mov-f*-ko``; Kalshi still uses ko_tko_dq.
                method = parse_optic_mov_name(odd.name)
                if not is_emittable_method(method):
                    continue
                assert method is not None
                assert side_code is not None
                entity = side_code
                grouping_key = method
                side = "yes"
            elif mt == MarketType.METHOD_OF_FINISH:
                # Fight-scoped method_of_ending → grouping_key.  Skip
                # Optic Draw (≠ Kalshi draw_or_nc).
                method = parse_optic_mof_label(
                    odd.selection or "", odd.name or "")
                if not is_emittable_method(method):
                    continue
                assert method is not None
                grouping_key = method
                side = "yes"
            elif mt.scope == Scope.PLAYER:
                name = odd.selection
                if mt == MarketType.TEAM_FIRST_TOUCHDOWN_SCORER:
                    # "Team :: Player"; a player is on one team.
                    name = (name or "").rsplit(" :: ", 1)[-1]
                entity = normalize_player_name(name)
                line_token = (odd.selection_line or "").strip().casefold()
                if not line_token:
                    # Affirmative-only player yes/no (first_goal_scorer,
                    # first_touchdown_scorer). Optic often ships
                    # selection_line="" rather than null — treat blank
                    # like None so one priced player does not abort the
                    # league. side is always "yes"; Kalshi's no sides
                    # stay novel.
                    side = "yes"
                elif line_token in ("over", "under"):
                    # Optic encodes player DD/TD as over/under 0.5.
                    side = "yes" if line_token.startswith("o") else "no"
                else:
                    skipped_malformed[odd.market_id] = (
                        skipped_malformed.get(odd.market_id, 0) + 1)
                    continue
            elif mt is MarketType.WINNING_MARGIN:
                # One affirmative per (team, band); the band is the grouping_key.
                grouping_key = _winning_margin_key(odd)
                if side_code is None or grouping_key is None:
                    skipped_malformed[odd.market_id] = (
                        skipped_malformed.get(odd.market_id, 0) + 1)
                    continue
                entity = side_code
                side = "yes"
            elif mt.scope == Scope.TEAM:
                # Team-scoped (e.g. to_advance): Optic quotes one
                # affirmative odd per team — selection=team name,
                # team_id set, no line.  side is always "yes"; the
                # negative ("team does not advance") has no Optic
                # counterpart, so Kalshi's no side stays novel.
                assert side_code is not None
                entity = side_code
                side = "yes"
                if odd.selection_line in ("yes", "no"):
                    side = odd.selection_line
                elif odd.normalized_selection in ("yes", "no"):
                    side = odd.normalized_selection
            else:
                # Game-scoped yes/no.  Soccer BTTS uses literal Yes/No
                # selections.  UFC round_betting / go_the_distance leave
                # selection blank and put the outcome label only in ``name``
                # (Nick 2026-03-03); those become grouping_key so distinct
                # outcomes do not collide.
                assert mt.scope == Scope.GAME
                if odd.normalized_selection in ("yes", "no"):
                    side = odd.normalized_selection
                elif odd.selection_line in ("yes", "no"):
                    side = odd.selection_line
                elif (
                    mt == MarketType.ROUND_BETTING
                    and (odd.name or "").strip()
                ):
                    # Optic now also supplies the normalized round outcome in
                    # selection (e.g. abdul_hussein_3rd_round).  `name` keeps
                    # the cross-exchange label understood by the canonicalizer.
                    grouping_key = canonicalize_fight_prop_key(odd.name)
                    side = "yes"
                elif (odd.selection or "").strip() == "" and (odd.name or "").strip():
                    # Binary go-the-distance odds keep side=yes with no
                    # grouping_key so they merge with crypto.com Yes/No.
                    if mt != MarketType.FIGHT_GOES_DISTANCE:
                        grouping_key = canonicalize_fight_prop_key(odd.name)
                    side = "yes"
                else:
                    raise ValueError(
                        f"Optic odd {odd.id}: game-scoped YES_NO with "
                        f"normalized_selection "
                        f"{odd.normalized_selection!r} name={odd.name!r}")

        elif mt.shape == Shape.H2H:
            entity = normalize_player_name(odd.selection)
            side = entity
            line = odd.points  # None for moneyline, signed for spread
            grouping_key = odd.grouping_key

        else:
            raise ValueError(
                f"Optic odd {odd.id}: unexpected "
                f"shape {mt.shape.value}")

        row = CanonicalRow(
            league=league,
            start_date=start_date, home=home, away=away,
            market_type=mt.value,
            entity=entity,
            line=line,
            side=side,
            grouping_key=grouping_key,
            optic_id=odd.id,
        )
        rows.append(row)
        odds_used.append(odd)
        odd_lookup[odd.id] = odd
        game_ref_lookup[odd.id] = game_ref

    _report_unresolved_sides(
        unresolved_team_ids, unresolved_selections,
        league=league, fixture=fixture, home=home, away=away)
    if skipped_malformed:
        where = (
            f"optic [{league}] fixture {fixture.fixture_id} "
            f"({away}@{home})")
        detail = ", ".join(
            f"{market_id} (x{count})"
            for market_id, count in sorted(skipped_malformed.items()))
        print(
            f"  {where}: skipped {sum(skipped_malformed.values())} "
            f"malformed odd(s): {detail}",
            file=sys.stderr,
        )

    # Collision guard: markets where grouping_key is not on CanonicalRow
    # must not share (market_type, entity, line, side). Drop both legs
    # rather than aborting the league (Nantes/Nancy both Optic abbr NAN).
    return _drop_grouping_collisions(
        rows, odds_used, odd_lookup, game_ref_lookup,
    )


def _drop_grouping_collisions(
    rows: list[CanonicalRow],
    odds_used: list[Odd],
    odd_lookup: dict[str, Odd],
    game_ref_lookup: dict[str, GameRef],
) -> tuple[list[CanonicalRow], dict[str, Odd], dict[str, GameRef]]:
    """Omit odds that would silently merge distinct grouping_keys."""
    seen_keys: dict[tuple, str] = {}
    drop: set[tuple] = set()
    for row, odd in zip(rows, odds_used, strict=True):
        key = (row.market_type, row.entity, row.line, row.side)
        prev_gk = seen_keys.get(key)
        if prev_gk is None:
            seen_keys[key] = odd.grouping_key
        elif prev_gk != odd.grouping_key and row.grouping_key is None:
            drop.add(key)
            print(
                f"  optic: skipped grouping_key collision {odd.grouping_key!r} "
                f"vs {prev_gk!r} on {key}",
                file=sys.stderr,
            )
    if not drop:
        return rows, odd_lookup, game_ref_lookup
    kept = [
        (row, odd)
        for row, odd in zip(rows, odds_used, strict=True)
        if (row.market_type, row.entity, row.line, row.side) not in drop
    ]
    kept_rows = [row for row, _odd in kept]
    kept_ids = {odd.id for _row, odd in kept}
    return (
        kept_rows,
        {oid: odd for oid, odd in odd_lookup.items() if oid in kept_ids},
        {oid: ref for oid, ref in game_ref_lookup.items() if oid in kept_ids},
    )


# === Source_ids verification ===

def _fixture_prefix(optic_id: str) -> str:
    """Extract the game-level prefix from an Optic odd ID.

    '18107-33911-2026-02-25:moneyline:south_carolina_state'
     → '18107-33911-2026-02-25'
    """
    return optic_id.rsplit(":", 2)[0]


def _clear_kalshi(row: CanonicalRow) -> None:
    row.kalshi_ticker = None
    row.kalshi_scope = None
    row.kalshi_title = None
    row.kalshi_yes_sub_title = None
    row.kalshi_side = None


def verify_source_ids(
    row_index: dict[tuple, CanonicalRow],
    odd_lookup: dict[str, Odd],
    *,
    kalshi_tickers: frozenset[str],
    on_mismatch: str = "strip",
) -> dict[str, int]:
    """Verify that Optic source_ids agree with our PX/Kalshi matching.

    For each merged canonical row that has an optic_id, checks that any
    PX or Kalshi cross-references in the Optic odd's source_ids match
    the row's px_line_id, kalshi_ticker, and kalshi_side.

    Confirmed mismatches (both sides matched but IDs disagree) honour
    ``on_mismatch``: ``"strip"`` (default) clears the exchange stamp
    so the wrong mapping is not loaded (missing > wrong); ``"raise"``
    keeps the historical hard-fail behaviour.  Tolerates a stale Optic
    Kalshi source_id: a ticker Kalshi's open book (``kalshi_tickers``)
    no longer lists, such as a postponed game's old contract.  A ticker
    Kalshi still lists is a real disagreement.  "Optic has a source_id
    but we have no match" is reported once per game, as not in Kalshi's
    open book or listed but unmapped.

    Also reports novel mappings: rows where we matched an exchange but
    Optic had no source_id for it — i.e. mappings we built that Optic
    couldn't provide.
    """
    if on_mismatch not in ("strip", "raise"):
        raise ValueError(f"on_mismatch must be 'strip' or 'raise', got {on_mismatch!r}")
    px_agreed = 0
    px_novel = 0
    px_sibling = 0
    px_stale = 0
    px_stripped = 0
    kalshi_agreed = 0
    kalshi_novel = 0
    kalshi_stale = 0
    kalshi_stripped = 0
    kalshi_stale_warned: set[str] = set()
    kalshi_nomatch_warned: set[str] = set()

    # line_id → row lookup for diagnosing PX mismatches.
    px_line_lookup: dict[str, CanonicalRow] = {}
    for r in row_index.values():
        if r.px_line_id is not None:
            px_line_lookup[r.px_line_id] = r

    for row in row_index.values():
        if row.optic_id is None:
            continue
        odd = odd_lookup.get(row.optic_id)
        if odd is None:
            continue

        px_src = (odd.source_ids or {}).get("Prophet X")
        kalshi_src = (odd.source_ids or {}).get("Kalshi")

        # PX verification — 3 top-level cases, 3 mismatch sub-cases.
        #
        # When we have a PX match (row.px_line_id is set):
        #   1. Optic has no PX source_id → novel mapping.  This is
        #      our value-add: we matched a PX market Optic couldn't.
        #   2. Optic has a PX source_id that agrees → confirmed.
        #   3. Optic has a PX source_id that disagrees → mismatch:
        #      a. Optic's ID not in current PX data → stale.  PX
        #         regenerated/replaced the market; Optic holds a dead
        #         reference.  Warn, keep our mapping.
        #      b. Optic's ID is a sup_moneyline sibling of ours
        #         (same entity, stat, line, game — just a different
        #         PX market object for the same prop).  Warn, keep
        #         ours.  Optic picks total 99.9% of the time (40k
        #         total vs 23 sup_moneyline across all data/); of
        #         those 23, 18 had no total alternative.  The
        #         remaining 5 are unexplained — keep vigilant.
        #         Always using our own total selection keeps the
        #         output deterministic regardless of Optic state.
        #      c. Otherwise → genuine disagreement.  Raise.
        if row.px_line_id is not None:
            if px_src:
                optic_px_id = px_src["selection_id"]
                if optic_px_id != row.px_line_id:
                    sibling = px_line_lookup.get(optic_px_id)
                    if sibling is None:
                        # 3a: stale — Optic's ID not in PX data
                        print(
                            f"  verify: {row.optic_id}: Optic PX "
                            f"selection_id {optic_px_id!r} not in "
                            f"current PX data (stale); keeping our "
                            f"px_line_id={row.px_line_id!r}",
                            file=sys.stderr)
                        px_stale += 1
                    elif (sibling.entity == row.entity
                          and normalize_line(sibling.line)
                              == normalize_line(row.line)
                          and sibling.px_event_id == row.px_event_id
                          and (sibling.market_type
                               == row.market_type + "_yn"
                               or row.market_type
                               == sibling.market_type + "_yn")):
                        # 3b: sup_moneyline sibling — keep ours
                        print(
                            f"  verify: {row.optic_id}: Optic PX "
                            f"selection_id {optic_px_id!r} is "
                            f"sup_moneyline sibling; keeping our "
                            f"total px_line_id={row.px_line_id!r}",
                            file=sys.stderr)
                        px_sibling += 1
                    else:
                        # 3c: genuine disagreement — missing > wrong
                        msg = (
                            f"Optic source_ids mismatch for "
                            f"{row.optic_id}: Optic says PX "
                            f"selection_id={optic_px_id!r}, "
                            f"but row has "
                            f"px_line_id={row.px_line_id!r}"
                        )
                        if on_mismatch == "raise":
                            raise ValueError(msg)
                        print(
                            f"  verify: {msg}; stripping PX "
                            f"(missing > wrong)",
                            file=sys.stderr,
                        )
                        row.px_event_id = None
                        row.px_line_id = None
                        row.px_market_name = None
                        row.px_selection_display_name = None
                        px_stripped += 1
                        # Fall through without counting agreed.
                        px_src = None
                if row.px_line_id is not None and px_src:
                    px_agreed += 1
            else:
                px_novel += 1
        elif px_src:
            print(
                f"  reconcile: {row.optic_id}: has PX source_id "
                f"{px_src['selection_id']!r} but we have no PX match",
                file=sys.stderr)

        # Kalshi: verify agreement or count novel mapping.
        #
        # When a Kalshi game is postponed, Kalshi mints a new contract and
        # closes the old one; Optic's source_id can keep pointing at the
        # old one.  A cited ticker that is not in Kalshi's open book is
        # that stale reference and ours stands.  A cited ticker Kalshi
        # still lists is a real disagreement: strip ours (missing > wrong).
        if row.kalshi_ticker is not None:
            if kalshi_src:
                optic_ticker = kalshi_src["market_id"]
                optic_side = kalshi_src["selection_id"]
                if optic_ticker != row.kalshi_ticker:
                    if optic_ticker not in kalshi_tickers:
                        fixture_prefix = _fixture_prefix(row.optic_id)
                        if fixture_prefix not in kalshi_stale_warned:
                            kalshi_stale_warned.add(fixture_prefix)
                            print(
                                f"  verify: {row.optic_id}: Optic Kalshi "
                                f"ticker {optic_ticker!r} is not in Kalshi's "
                                f"open book; keeping our "
                                f"kalshi_ticker={row.kalshi_ticker!r}",
                                file=sys.stderr)
                        kalshi_stale += 1
                        continue
                    msg = (
                        f"Optic source_ids mismatch for {row.optic_id}: "
                        f"Optic says Kalshi ticker={optic_ticker!r}, "
                        f"but row has kalshi_ticker={row.kalshi_ticker!r}"
                    )
                    if on_mismatch == "raise":
                        raise ValueError(msg)
                    print(
                        f"  verify: {msg}; stripping Kalshi "
                        f"(missing > wrong)",
                        file=sys.stderr,
                    )
                    _clear_kalshi(row)
                    kalshi_stripped += 1
                    continue
                if optic_side != row.kalshi_side:
                    msg = (
                        f"Optic source_ids mismatch for {row.optic_id}: "
                        f"Optic says Kalshi side={optic_side!r}, "
                        f"but row has kalshi_side={row.kalshi_side!r}"
                    )
                    if on_mismatch == "raise":
                        raise ValueError(msg)
                    print(
                        f"  verify: {msg}; stripping Kalshi "
                        f"(missing > wrong)",
                        file=sys.stderr,
                    )
                    _clear_kalshi(row)
                    kalshi_stripped += 1
                    continue
                kalshi_agreed += 1
            else:
                kalshi_novel += 1
        elif kalshi_src:
            src_ticker = kalshi_src["market_id"]
            fixture_prefix = _fixture_prefix(row.optic_id)
            if fixture_prefix not in kalshi_nomatch_warned:
                kalshi_nomatch_warned.add(fixture_prefix)
                reason = (
                    "listed but unmapped (scope or typed side)"
                    if src_ticker in kalshi_tickers
                    else "not in Kalshi's open book"
                )
                print(
                    f"  reconcile: {fixture_prefix}: Kalshi source_id "
                    f"{src_ticker!r} but no match — {reason}",
                    file=sys.stderr)

    print(
        f"reconcile: optic\u2192kalshi {kalshi_agreed} agreed, "
        f"{kalshi_novel} novel"
        + (f", {kalshi_stale} stale" if kalshi_stale else "")
        + (f", {kalshi_stripped} stripped" if kalshi_stripped else ""),
        file=sys.stderr)
    print(
        f"reconcile: optic\u2192px {px_agreed} agreed, "
        f"{px_novel} novel"
        + (f", {px_sibling} sibling" if px_sibling else "")
        + (f", {px_stale} stale" if px_stale else "")
        + (f", {px_stripped} stripped" if px_stripped else ""),
        file=sys.stderr)
    return {"px_stripped": px_stripped, "kalshi_stripped": kalshi_stripped}
