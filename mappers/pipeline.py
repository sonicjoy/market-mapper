"""Generic merge pipeline for mapping exchange markets to an Optic schedule.

Loads the Optic fixtures file to build the game schedule index, keyed
by (game_date, home_abbrev, away_abbrev).  Same-day doubleheaders share
a MatchKey but keep distinct ScheduleEntry rows (one per Optic game_id);
sources with tip-off times (PX, crypto.com) pick the nearest fixture,
while Kalshi (date-only tickers) skips when more than one candidate
exists.  Parses each PX event, matches it to the index.  Parses each
Kalshi market, matches it to the index.  Builds canonical rows from all
sources and merges them by row key.

Reports matched and unmatched totals.
"""

import json
import os
import re
import sys
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from pathlib import Path
from typing import Any, NamedTuple

from BigQuery.alerts import AlertPublisher
from mappers.canonical_codes import person_league
from mappers.crypto_id_name_bind import pin_crypto_ids_from_selections
from mappers.crypto_name_window import name_window_entries
from mappers.diagnostics import (
    hours_to_game,
    no_match_detail,
    player_orphan_table,
    row_orphan_summary,
)
from mappers.exchanges.kalshi_precedence import keeps_existing
from mappers.exchanges import (
    crypto_com,
    crypto_optic,
    dkex,
    dkex_pass,
    huddle,
    kalshi,
    novig,
    optic,
    optic_verify,
    polymarket,
    px,
    runshop,
    stx_attach,
    sxbet,
    sxbet_pass,
    underdog_pass,
)
from mappers.exchanges import polymarket_usa_structured as pus
from mappers.exchanges.crypto_com import CryptoConfig
from mappers.exchanges.kalshi import KalshiConfig
from mappers.exchanges.optic import OpticConfig
from mappers.exchanges.optic_passthrough_crosscheck import (
    NOVIG_BOOK,
    POLY_BOOK,
    TWO_WAY_NO,
    CrosscheckLedger,
    CrosscheckStats,
    crosscheck_enabled,
    reconcile_tokens,
    rfq_key_from_source_ids,
    strip_passthrough,
)
from mappers.exchanges.polymarket_usa_bind import (
    usa_market_id,
    usa_symbol_of,
)
from mappers.exchanges.polymarket_usa_config import PolyUsaConfig
from mappers.exchanges.polymarket_usa_extra_time import (
    blocks_player_prop,
    held_fixture_keys,
    is_player_type,
)
from mappers.exchanges.polymarket_usa_players import (
    bind_player_entities,
    build_player_index,
)
from mappers.exchanges.polymarket_usa_sides import venue_side
from mappers.exchanges.px import PxConfig
from mappers.exchanges.stx_attach import stx_source_ids
from mappers.exchanges.underdog import UnderdogConfig
from mappers.exchanges.underdog_udx_optic_witness import publish_udx_witness_alerts
from mappers.insurance_stamp import SUFFIX as INSURANCE_SUFFIX
from mappers.insurance_stamp import stamp_insurance_rows
from mappers.kalshi_complement import (
    attach_kalshi_double_chance_complements,
    attach_kalshi_moneyline_complements,
)
from mappers.market_types import MarketType, Scope, Shape
from mappers.optic_abbr_bind import (
    lookup_oriented,
    lookup_pair,
    pin_optic_abbr_codes,
)
from mappers.poly_passthrough_identity import bridge_by_clob, drop_mismatched_passthroughs
from mappers.poly_usa_complement import (
    other_team_key,
    stamp_usa_complements,
    stamp_usa_double_chance,
    usa_no_goal_satellites,
)
from mappers.px_name_bind import pin_px_name_miss, px_event_team_map
from mappers.seed.sot import (
    SotSnapshot,
    entities_to_alias_data,
    load_snapshot,
    overlay_league_config,
    tip_alias_enforcement,
    tip_entity_type,
    tip_league_row,
    tip_player_entity_type,
)
from mappers.shared import (
    TIE_SIDE,
    AliasData,
    AliasMap,
    AliasValue,
    CanonicalRow,
    MatchKey,
    is_crypto_date_placeholder,
    known_alias_codes,
    normalize_line,
    normalize_player_name,
    parse_iso_datetime,
    resolve_team,
    simple_alias_map,
    to_date_str,
    to_et_str,
)
from mappers.snapshot_index import SnapshotIndex, iter_file_or_snapshot
from mappers.sport import Sport, sport_for_league
from mappers.team_bootstrap import bootstrap_empty_abbrs
from mappers.vocab.crypto_team_ids import (
    CRYPTO_TEAM_ID_OVERRIDES,
    CRYPTO_TEAM_IDS,
)
from mappers.vocab.poly_usa_smt import (
    NOT_EQUIVALENT,
    TWO_WAY_OUTCOME_TYPES,
    not_equivalent_types,
)

# === League config ===

@dataclass(frozen=True)
class LeagueConfig:
    """Everything the pipeline needs from a league module."""
    # BQ mapping_leagues slug (or League StrEnum member, which is a str).
    league: str
    # None for leagues with no ProphetX coverage (e.g. World Cup);
    # the pipeline's PX parsing/classification section is skipped,
    # leaving its containers empty so downstream matching no-ops.
    PX: PxConfig | None
    OPTIC: OpticConfig
    OUTPUT_ORDER: tuple[MarketType, ...]
    MarketType: type[MarketType]
    # Optional: None for leagues with no Kalshi coverage; the
    # pipeline's Kalshi parsing/classification section is skipped,
    # leaving its containers empty so downstream matching no-ops
    # (mirrors the PX gating above).
    KALSHI: KalshiConfig | None = None
    # Optional: only set for leagues with crypto.com coverage; None
    # leaves the pipeline's crypto path inactive for that league.
    CRYPTO: CryptoConfig | None = None
    # Optional: Runshop betbuilder price lookup stamps (World Cup).
    RUNSHOP: runshop.RunshopConfig | None = None
    # Optional: only set for leagues with Polymarket combo-RFQ coverage.
    POLYMARKET: polymarket.PolymarketConfig | None = None
    # Optional: Polymarket US (polymarketus) — its own venue; set from code
    # (``with_code_poly_usa``) with the gateway league ids this league reads.
    POLYMARKET_USA: PolyUsaConfig | None = None
    # Optional: only set for leagues Novig quotes; None leaves the
    # pipeline's Novig path inactive for that league.
    NOVIG: novig.NovigConfig | None = None
    # Optional: only set for leagues DKEX lists; None leaves the
    # pipeline's DKEX path inactive for that league.
    DKEX: dkex.DkexConfig | None = None
    UNDERDOG: UnderdogConfig | None = None
    # Optional: set in code for the leagues SX Bet lists (with_code_sxbet);
    # None leaves the pipeline's SX path inactive for that league.
    SXBET: sxbet.SxConfig | None = None
    HUDDLE: huddle.HuddleConfig | None = None
    # Tip row sport when known; filled from the slug when omitted.
    sport: Sport | None = None

    def __post_init__(self) -> None:
        if self.sport is None:
            object.__setattr__(
                self, "sport", sport_for_league(str(self.league)),
            )


def config_slug(cfg: LeagueConfig) -> str:
    """BQ / registry slug for a league config."""
    return str(cfg.league)


def config_sport(cfg: LeagueConfig) -> Sport:
    """Sport from the config (always set after init)."""
    return cfg.sport if cfg.sport is not None else sport_for_league(str(cfg.league))


def _crypto_entity_names(snap: SotSnapshot | None, slug: str) -> dict[str, str]:
    """canonical_key → display name for the crypto.com crossed-id guard."""
    if snap is None:
        return {}
    return {
        ent.canonical_key: str(ent.canonical_name or ent.canonical_key)
        for ent in snap.entities
        if ent.league == slug and not ent.tombstone
    }


def _sot_alias_seed(snap: SotSnapshot, slug: str) -> tuple[set[str], dict[str, str]]:
    """Canonical keys + optic_id overrides from the coalesced BQ tip."""
    used = {
        ent.canonical_key
        for ent in snap.entities
        if ent.league == slug and not ent.tombstone
    }
    optic: dict[str, str] = {}
    for entity_type in ("team", "player", "fighter"):
        _, extra = entities_to_alias_data(
            snap.entities, league=slug, entity_type=entity_type,
        )
        optic.update(extra)
    return used, optic


# === Pipeline result ===

class PipelineResult(NamedTuple):
    """Everything the CLI needs to format output."""
    rows: list[CanonicalRow]
    odd_lookup: dict[str, optic.Odd]
    game_ref_lookup: dict[str, optic.GameRef]
    crosscheck_ledger: CrosscheckLedger | None = None


# === Schedule index ===

class ScheduleEntry:
    """An Optic fixture with mutable slots for exchange matches."""
    __slots__ = (
        "fixture", "px_event", "kalshi_markets", "crypto_selections",
    )

    def __init__(self, fixture: optic.Fixture):
        self.fixture = fixture
        self.px_event: px.ParsedEvent | None = None
        self.kalshi_markets: list[kalshi.Market] = []
        # crypto.com selections matched to this game (empty for leagues
        # without a CryptoConfig, or games with no crypto coverage).
        self.crypto_selections: list[crypto_com.Selection] = []


ScheduleIndex = dict[MatchKey, list[ScheduleEntry]]


def _pick_entry_by_time(
    candidates: list[ScheduleEntry],
    when_iso: str,
) -> ScheduleEntry:
    """Pick the schedule entry whose Optic start_date is nearest to when_iso."""
    when = parse_iso_datetime(when_iso)
    return min(
        candidates,
        key=lambda e: abs(
            (parse_iso_datetime(e.fixture.start_date) - when).total_seconds()
        ),
    )


def _unique_entry(
    candidates: list[ScheduleEntry],
) -> ScheduleEntry | None:
    """Return the sole candidate, or None when empty or ambiguous."""
    if len(candidates) == 1:
        return candidates[0]
    return None


def _unique_pair_entries(
    index: ScheduleIndex, home: str, away: str,
) -> list[ScheduleEntry]:
    """Entries whose sides are this pair in either orientation."""
    return lookup_pair(index, home, away)


def _crypto_schedule_entries(
    index: ScheduleIndex,
    home: str,
    away: str,
    start_date: str,
) -> tuple[list[ScheduleEntry], bool] | None:
    """Exact ET date, else date-only unique pair. None when unmatched."""
    date = to_date_str(to_et_str(start_date))
    found = lookup_oriented(index, date, home, away)
    if found:
        return found, False
    flipped = lookup_oriented(index, date, away, home)
    if flipped:
        return flipped, True
    if not is_crypto_date_placeholder(start_date):
        return None
    pair = _unique_pair_entries(index, home, away)
    if len(pair) != 1:
        return None
    return pair, pair[0].fixture.home != home


# A milestone whose start differs from the Optic fixture by more than
# this is not the same game (a reschedule Optic has, Kalshi hasn't).
_MILESTONE_START_TOLERANCE = timedelta(hours=36)


def _milestone_orientation(
    entry: ScheduleEntry, markets: list[kalshi.Market],
) -> bool | None:
    """True if Kalshi's milestone home is Optic's away; None if unknown.

    Kalshi and Optic can disagree on home (REN v PSG listed both ways),
    so milestone home is never assumed to be Optic home.  Evidence, in
    order, all id joins:
      1. the milestone teams' Optic competitor ids vs the fixture's;
      2. Optic's own source_ids naming a Kalshi ticker on a selection
         whose team_id is known — that ticker's strike team id says
         which Kalshi team is which Optic side.
    Conflicting or absent evidence returns None (the game is skipped).
    """
    fx = entry.fixture
    ms = markets[0].milestone or {}
    h = fx.team_map.get(ms.get("home_optic_id") or "")
    a = fx.team_map.get(ms.get("away_optic_id") or "")
    if (h, a) == (fx.home, fx.away):
        return False
    if (h, a) == (fx.away, fx.home):
        return True
    # One side's Optic id settles a two-sided fixture on its own.
    if a is None and h in (fx.home, fx.away):
        return h == fx.away
    if h is None and a in (fx.home, fx.away):
        return a == fx.home
    team_by_ticker = {
        m.ticker: tid for m in markets
        if (tid := kalshi.strike_team_id(m)) is not None
    }
    votes: set[bool] = set()
    for odd in fx.odds:
        ref = odd.source_ids.get("Kalshi")
        if not isinstance(ref, dict) or ref.get("selection_id") != "yes":
            continue
        tid = team_by_ticker.get(ref.get("market_id") or "")
        side = fx.team_map.get(odd.team_id or "")
        if tid is None or side is None:
            continue
        if tid == ms.get("home_id"):
            votes.add(side != fx.home)
        elif tid == ms.get("away_id"):
            votes.add(side != fx.away)
    if len(votes) == 1:
        return votes.pop()
    return None


def _competitor_pair_index(
    entries: list[ScheduleEntry],
) -> dict[frozenset[str], list[ScheduleEntry]]:
    """Optic competitor ids → fixtures, keyed by each {home, away} pair."""
    out: dict[frozenset[str], list[ScheduleEntry]] = defaultdict(list)
    for e in entries:
        fx = e.fixture
        homes = [k for k, v in fx.team_map.items() if v == fx.home]
        aways = [k for k, v in fx.team_map.items() if v == fx.away]
        for h in homes:
            for a in aways:
                out[frozenset((h, a))].append(e)
    return out


def _optic_player_names(fx: optic.Fixture) -> dict[str, str]:
    """Kalshi ticker → the one Optic selection whose source_ids name it.

    A ticker Optic names on two different selections is left out; the
    Kalshi label then decides, as before.
    """
    names: dict[str, set[str]] = defaultdict(set)
    for odd in fx.odds:
        ref = odd.source_ids.get("Kalshi")
        if isinstance(ref, dict) and ref.get("market_id") and odd.selection:
            names[ref["market_id"]].add(odd.selection)
    return {t: next(iter(s)) for t, s in names.items() if len(s) == 1}


def _optic_ref_index(
    entries: list[ScheduleEntry], markets: list[kalshi.Market],
) -> dict[str, ScheduleEntry]:
    """Milestone id → the Optic fixture whose odds name its tickers.

    Optic stamps Kalshi tickers into its own source_ids; an exact ticker
    match ties that Kalshi game to that fixture where neither the fixture
    id nor the Sportradar id is shared (UFC, much of soccer).  Lifted to
    the milestone so its unreferenced markets follow.  A milestone whose
    tickers point at two fixtures is left out.
    """
    by_ticker: dict[str, set[int]] = defaultdict(set)
    entry_by_id: dict[int, ScheduleEntry] = {}
    for e in entries:
        for odd in e.fixture.odds:
            ref = odd.source_ids.get("Kalshi")
            if isinstance(ref, dict) and ref.get("market_id"):
                by_ticker[ref["market_id"]].add(id(e))
                entry_by_id[id(e)] = e
    hits: dict[str, set[int]] = defaultdict(set)
    for m in markets:
        ms_id = (m.milestone or {}).get("id")
        if ms_id:
            hits[ms_id] |= by_ticker.get(m.ticker, set())
    return {
        ms_id: entry_by_id[next(iter(ids))]
        for ms_id, ids in hits.items() if len(ids) == 1
    }


def _near_start(milestone: dict, entry: ScheduleEntry) -> bool:
    ms_start = milestone.get("start_date")
    if not ms_start:
        return True
    delta = abs(parse_iso_datetime(ms_start)
                - parse_iso_datetime(entry.fixture.start_date))
    return delta <= _MILESTONE_START_TOLERANCE


def _milestone_entry(
    milestone: dict | None,
    by_fixture_id: dict[str, ScheduleEntry],
    by_sportradar_id: dict[str, ScheduleEntry],
    by_competitors: dict[frozenset[str], list[ScheduleEntry]] | None = None,
    by_optic_ref: dict[str, ScheduleEntry] | None = None,
) -> ScheduleEntry | None:
    """The Optic fixture a Kalshi milestone names, else None.

    All id joins, in order: source_2_id (Optic's fixture id), the
    Sportradar sport_event id, Optic's own source_ids naming one of the
    milestone's tickers, then both sides' Optic competitor ids.  Needs
    both side ids so every market's side is an id comparison.
    """
    if not milestone or not milestone.get("home_id") or not milestone.get("away_id"):
        return None
    entry = by_fixture_id.get(milestone.get("optic_fixture_id") or "")
    if entry is None:
        entry = by_sportradar_id.get(milestone.get("sportradar_id") or "")
    if entry is None and by_optic_ref is not None:
        entry = by_optic_ref.get(milestone.get("id") or "")
    if entry is None and by_competitors is not None:
        # Both sides' Optic ids: one side alone is not enough, a player
        # can have two fixtures inside the start tolerance (qualifying
        # and main draw, singles and doubles).
        h, a = milestone.get("home_optic_id"), milestone.get("away_optic_id")
        if h and a:
            near = [e for e in by_competitors.get(frozenset((h, a)), [])
                    if _near_start(milestone, e)]
            if len(near) == 1:
                entry = near[0]
    if entry is None or not _near_start(milestone, entry):
        return None
    return entry


def _resolve_off_milestone_sides(
    entry: ScheduleEntry, markets: list[kalshi.Market],
) -> list[kalshi.Market]:
    """Side ids for markets whose strike id is not one of the milestone's.

    Kalshi can list one competitor under two structured targets (Sergey
    Spivak / Serghei Spivac, different Sportradar ids): the fight market
    names one, the milestone the other.  Optic's own source_ids naming
    that exact ticker on a selection with a team_id settle the side;
    without that the market is left alone and gets skipped, never guessed.
    Expects milestones already oriented to Optic home/away.
    """
    fx = entry.fixture
    optic_side: dict[str, str] = {}
    for odd in fx.odds:
        ref = odd.source_ids.get("Kalshi")
        if not isinstance(ref, dict) or ref.get("selection_id") != "yes":
            continue
        side = fx.team_map.get(odd.team_id or "")
        if side is not None and ref.get("market_id"):
            optic_side[ref["market_id"]] = side
    out: list[kalshi.Market] = []
    for m in markets:
        ms = m.milestone or {}
        tid = kalshi.strike_team_id(m)
        known = {ms.get("home_id"), ms.get("away_id"), ms.get("tie_id")}
        side = optic_side.get(m.ticker)
        if tid is not None and tid not in known and side is not None:
            resolved = ms.get("home_id") if side == fx.home else ms.get("away_id")
            print(
                f"  kalshi: {m.ticker}: strike id {tid} not in milestone — "
                f"side {side} from Optic source_ids",
                file=sys.stderr)
            m = m.model_copy(update={"resolved_side_id": resolved})
        out.append(m)
    return out


# === PX event matching ===

def match_event(
    event: px.ParsedEvent,
    index: ScheduleIndex,
    aliases: AliasMap | None = None,
) -> bool:
    """Match a PX event to a schedule entry.  Returns True if matched.

    Same-day doubleheaders are disambiguated by PX's scheduled tip-off.
    Book codes that equal the Optic competitor abbreviation bind onto
    the fixture canonical (``WHU`` → ``WHUF6``).
    """
    k = event.match_key
    candidates = lookup_oriented(index, k.game_date, k.home, k.away)
    if not candidates:
        return False

    entry = _pick_entry_by_time(candidates, event.raw.scheduled)
    fx = entry.fixture
    if aliases is not None:
        pin_optic_abbr_codes(k.home, k.away, fx, aliases)
    event.match_key = MatchKey(k.game_date, fx.home, fx.away)
    entry.px_event = event
    return True


def _recover_px_event(
    event: px.ParsedEvent,
    index: ScheduleIndex,
    fixture_dates: set[str],
    aliases: AliasMap,
    team_canonicals: set[str],
    event_team_maps: dict[int, dict[str, str]],
    *,
    player: bool,
    fetch_time: datetime,
    horizon_cutoff: datetime,
    league_name: str,
) -> str:
    """Flip, unique-name bind, or skip. Never raise — one miss must not zero the league."""
    k = event.match_key
    if k.game_date not in fixture_dates:
        return "other_date"
    flipped = lookup_oriented(index, k.game_date, k.away, k.home)
    if flipped:
        entry = _pick_entry_by_time(flipped, event.raw.scheduled)
        fx = entry.fixture
        pin_optic_abbr_codes(k.home, k.away, fx, aliases)
        event.match_key = MatchKey(k.game_date, fx.home, fx.away)
        event_team_maps[event.raw.event_id] = px_event_team_map(event, aliases)
        entry.px_event = event
        print(
            f"  px [{league_name}] event {event.raw.event_id}: "
            f"away/home flip — PX has {k.away}@{k.home}, schedule has "
            f"{fx.home}@{fx.away}",
            file=sys.stderr)
        return "flip"
    if pin_px_name_miss(event, index, aliases, player=player):
        event_team_maps[event.raw.event_id] = px_event_team_map(event, aliases)
        if match_event(event, index, aliases):
            return "matched"
        k = event.match_key
    return _skip_unmatched_px(
        event, index, k, team_canonicals, fetch_time, horizon_cutoff,
        league_name,
    )


def _skip_unmatched_px(
    event: px.ParsedEvent,
    index: ScheduleIndex,
    k: MatchKey,
    team_canonicals: set[str],
    fetch_time: datetime,
    horizon_cutoff: datetime,
    league_name: str,
) -> str:
    """Log an unmatched PX event and continue the league (unknown codes included)."""
    detail, has_unknown = no_match_detail(
        index, k.game_date, k.away, k.home, team_canonicals)
    if not has_unknown:
        scheduled = datetime.fromisoformat(event.raw.scheduled)
        hours = hours_to_game(scheduled, fetch_time)
        if scheduled > horizon_cutoff:
            return "beyond"
        detail += f"  (~{hours:.0f}h to game)"
    print(
        f"  px [{league_name}] event {event.raw.event_id}: "
        f"no schedule game for {k.game_date} {k.away}@{k.home}\n  {detail}",
        file=sys.stderr)
    return "skip"


# === Canonical row sorting ===


def _make_sort_key(
    market_type_order: dict[str, int],
    spread_types: set[str],
):
    """Create a sort-key function parameterized by league output order.

    Groups spread pairs (e.g. ATL -7.5 / WAS +7.5) together by
    favored team within each abs(line), negative before positive.
    Totals: over before under.  Moneyline: home before away.
    """
    def _row_sort_key(r: CanonicalRow) -> tuple:
        mt_rank = market_type_order.get(r.market_type, 99)
        abs_line = abs(r.line) if r.line is not None else 0
        # Within a line: favored (negative) first for spreads,
        # over before under for totals, home before away for moneyline
        if r.side in ("over", "yes"):
            side_rank = (0, 0)
        elif r.side in ("under", "no"):
            side_rank = (0, 1)
        elif r.market_type in spread_types:
            # Group opposite sides of the same bet: the favored team
            # (negative line) identifies the pair, then negative before positive.
            if r.line is None:
                side_rank = (r.side, 0)
            else:
                favored = (
                    r.side if r.line < 0
                    else r.away if r.side == r.home else r.home
                )
                side_rank = (favored, r.line)
        elif r.side == TIE_SIDE:
            side_rank = (0, 2)
        else:
            side_rank = (0, 0 if r.side == r.home else 1)
        return (r.league,
                r.start_date, r.home, r.away, mt_rank, r.entity or "",
                abs_line, side_rank)

    return _row_sort_key


# === Row key for merging ===

def row_key(r: CanonicalRow) -> tuple:
    """Merge key: rows from different exchanges with the same key
    represent the same bet.  grouping_key is None for markets where
    (entity, line, side) is sufficient, and set to the raw Optic
    grouping_key for markets like H2H where it carries additional
    disambiguation (e.g. which opponent in a player matchup).
    """
    return (r.league,
            r.start_date, r.home, r.away, r.market_type,
            r.entity, normalize_line(r.line), r.side,
            r.grouping_key)


def _usa_complement_key(key: tuple) -> tuple | None:
    """Other listing of the same US market, or None if there isn't one.

    A US ticker is a market id: Optic stamps it on both complementary
    odds (ARI -1.5 and SF +1.5, or over/under). Spreads flip team and
    negate the line; totals / yes-no swap the label. Moneyline tickers
    name one team in the suffix, so they stay selection-level.
    """
    (
        league, start, home, away, market_type, entity, line, side,
        grouping_key,
    ) = key
    if side in ("over", "under"):
        other = "under" if side == "over" else "over"
        return (
            league, start, home, away, market_type, entity, line, other,
            grouping_key,
        )
    if side in ("yes", "no"):
        other = "no" if side == "yes" else "yes"
        return (
            league, start, home, away, market_type, entity, line, other,
            grouping_key,
        )
    if line is None:
        return None
    if side == home:
        other_side = away
    elif side == away:
        other_side = home
    else:
        return None
    return (
        league, start, home, away, market_type, entity,
        normalize_line(-line), other_side, grouping_key,
    )


def _usa_optic_agree(parsed: tuple, optic_keys: set[tuple]) -> bool:
    """True when Optic already maps this ticker onto this row or its pair."""
    if parsed in optic_keys:
        return True
    complement = _usa_complement_key(parsed)
    return complement is not None and complement in optic_keys


def _build_optic_usa_index(
    row_index: dict[tuple, "CanonicalRow"], odd_lookup: dict[str, "optic.Odd"]
) -> dict[str, set[tuple]]:
    """{market_id ticker -> row_keys} for every US ticker Optic already maps.

    One ticker is a market, not a selection: Optic hangs it on both
    complementary odds. Keep the full set so guard#4 can agree with
    either listing instead of last-write-wins colliding the pair.
    """
    idx: dict[str, set[tuple]] = {}
    for row in row_index.values():
        if row.optic_id is None:
            continue
        odd = odd_lookup.get(row.optic_id)
        if odd is None:
            continue
        src = (odd.source_ids or {}).get("Polymarket (USA)")
        market_id = usa_market_id(src)
        if market_id:
            idx.setdefault(market_id, set()).add(row_key(row))
    return idx


def _check_poly_passthrough_identity(
    league: LeagueConfig,
    entries: list,
    row_index: dict[tuple, CanonicalRow],
    odd_lookup: dict[str, optic.Odd],
    player_types: set[str],
    player_alias_data: AliasData,
    data_dir: Path,
    snapshot: SnapshotIndex | None,
) -> None:
    """Strip Optic Polymarket ids whose own bridge question names someone else."""
    bridge = bridge_by_clob(data_dir, snapshot)
    if not bridge:
        return
    pcfg = league.POLYMARKET
    aliases = {
        normalize_player_name(name): canonical
        for name, canonical in simple_alias_map(
            player_alias_data.by_exchange.get("polymarket", {})).items()
    }
    team_aliases = pcfg.team_name_aliases if pcfg is not None else {}
    with polymarket.team_alias_scope(team_aliases):
        stats = drop_mismatched_passthroughs(
            row_index.values(), odd_lookup, bridge,
            [e.fixture for e in entries],
            league=league.league,
            player_types=frozenset(player_types),
            player_aliases=aliases,
            style=pcfg.question_style if pcfg is not None else "mlb_suffix",
        )
    if stats.dropped_player or stats.dropped_fixture:
        print(
            f"  polymarket [{league.league}] passthrough identity: "
            f"{stats.verified} verified, {stats.unverified} not in bridge, "
            f"{stats.dropped_player} wrong player, "
            f"{stats.dropped_fixture} wrong fixture dropped",
            file=sys.stderr,
        )


def _build_optic_poly_index(
    row_index: dict[tuple, "CanonicalRow"], odd_lookup: dict[str, "optic.Odd"]
) -> dict[str, tuple]:
    """{clob_token_id -> row_key} for every clob OpticOdds already maps.

    Reads each optic-backed row's Odd.source_ids["Polymarket"] (or
    "Polymarket (USA)")["selection_id"] — the clobTokenId optic assigned to that
    (game/market/side). Used by the poly pass to cross-check the matcher's parse
    against optic (guard #4): a clob optic maps to a DIFFERENT row_key than we
    parsed is a side/market disagreement and must be dropped, not stamped.
    """
    idx: dict[str, tuple] = {}
    for row in row_index.values():
        if row.optic_id is None:
            continue
        odd = odd_lookup.get(row.optic_id)
        if odd is None:
            continue
        src = (odd.source_ids or {}).get("Polymarket") or (odd.source_ids or {}).get(
            "Polymarket (USA)"
        )
        clob = src.get("selection_id") if isinstance(src, dict) else None
        if clob:
            idx[str(clob)] = row_key(row)
    return idx


def _build_optic_novig_index(
    row_index: dict[tuple, "CanonicalRow"], odd_lookup: dict[str, "optic.Odd"]
) -> dict[str, tuple]:
    """{novig outcome_id -> row_key} for every outcome OpticOdds already maps.

    Optic's own ``source_ids["Novig"]`` carries the same
    ``{event_id, market_id, selection_id}`` triple the Novig API returns, so
    ``selection_id`` is the outcome id.  Used by the Novig pass the way
    ``_build_optic_poly_index`` is used by the poly pass: an outcome Optic
    maps to a DIFFERENT row_key than we parsed is a side/market
    disagreement and must be dropped rather than stamped, and an outcome
    Optic maps identically is left to the passthrough emit so the two paths
    never both produce a row for the same MERGE key.
    """
    idx: dict[str, tuple] = {}
    for row in row_index.values():
        if row.optic_id is None:
            continue
        odd = odd_lookup.get(row.optic_id)
        if odd is None:
            continue
        src = (odd.source_ids or {}).get("Novig")
        outcome_id = src.get("selection_id") if isinstance(src, dict) else None
        if outcome_id:
            idx[str(outcome_id)] = row_key(row)
    return idx


def _within_one_day(iso_utc_date: str, target: str) -> bool:
    """True when iso_utc_date (YYYY-MM-DD or longer ISO string) is within
    ±1 day of target (YYYY-MM-DD)."""
    try:
        a = _date.fromisoformat(iso_utc_date[:10])
        b = _date.fromisoformat(target)
    except ValueError:
        return False
    return abs((a - b).days) <= 1


def _match_poly_fixture_full(a: str, b: str, target: str, fixtures, style: str):
    """granularity='full' name match: exact date wins, else first ±1-day fallback.

    EXACT pre-task-TN2 behaviour. Name match uses polymarket._norm_name/
    _name_match (gated by style) against each fixture's home_name/away_name
    (Polymarket has no team IDs); both teams must match the fixture's two sides
    in either orientation. Exact-date beats ±1 day (mirrors the maker's proven
    _match_fixture) so MLB's same-matchup-on-consecutive-days series can't map a
    day-D market onto the day D-1 fixture it happens to see first.
    """
    from mappers.exchanges.polymarket import _name_match, _norm_name
    fallback = None
    for fx in fixtures:
        hn, an = _norm_name(fx.home_name, style), _norm_name(fx.away_name, style)
        names_ok = (_name_match(a, hn, style) and _name_match(b, an, style)) or \
                   (_name_match(a, an, style) and _name_match(b, hn, style))
        if not names_ok:
            continue
        if fx.start_date[:10] == target:
            return fx  # exact date wins immediately
        if fallback is None and _within_one_day(fx.start_date, target):
            fallback = fx
    return fallback


def _match_poly_fixture_surname(a: str, b: str, target: str, fixtures, style: str,
                                granularity: str):
    """granularity='surname' collision-safe match: collect ALL, drop if ambiguous.

    Surname matching is lossy, so it must fail safe rather than guess (see
    wave-tennis-probe-findings.md C.2's ITF collision data): unlike the 'full'
    path it does not short-circuit on the first hit — it collects every matching
    fixture and drops (returns None) if a fixture's own two competitors share the
    same last-token surname (inherently ambiguous) or if the surname pair matches
    more than one fixture.
    """
    from mappers.exchanges.polymarket import _fixture_surname_collision, _match_name
    exact_matches = []
    fallback_matches = []
    for fx in fixtures:
        if _fixture_surname_collision(fx.home_name, fx.away_name, style):
            continue  # both competitors share this surname -> inherently ambiguous, skip
        names_ok = (_match_name(a, fx.home_name, style, granularity) and
                    _match_name(b, fx.away_name, style, granularity)) or \
                   (_match_name(a, fx.away_name, style, granularity) and
                    _match_name(b, fx.home_name, style, granularity))
        if not names_ok:
            continue
        if fx.start_date[:10] == target:
            exact_matches.append(fx)
        elif _within_one_day(fx.start_date, target):
            fallback_matches.append(fx)
    if exact_matches:
        return exact_matches[0] if len(exact_matches) == 1 else None
    if fallback_matches:
        return fallback_matches[0] if len(fallback_matches) == 1 else None
    return None


# Tolerance for matching a poly market's own gameStartTime to a fixture's start.
# Feeds disagree by minutes on kickoff (and a postponed game moves by hours), while
# a same-matchup series sits ~24h apart — so a couple of hours separates siblings
# with room to spare.
_POLY_INSTANT_TOLERANCE_S = 2 * 3600


def _parse_instant(value: str | None) -> "datetime | None":
    """Parse a UTC instant from Gamma's ``gameStartTime`` or an optic ``start_date``.

    Handles both shapes seen in the wild: Gamma's ``"2026-08-06 01:40:00+00"`` and
    optic's ISO ``"2026-08-06T01:40:00Z"``. Returns None on anything unparseable
    (the caller then falls back to date matching rather than guessing).
    """
    if not value:
        return None
    s = str(value).strip().replace(" ", "T", 1)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    elif s.endswith("+00"):
        s = s[:-3] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _match_poly_fixture_instant(
    a: str, b: str, instant: "datetime", fixtures, style: str, granularity: str
):
    """Name match + AUTHORITATIVE kickoff-instant match; fail closed if ambiguous.

    Used whenever the poly market carries its own ``gameStartTime``. Unlike the
    date paths there is NO adjacent-day fallback: a market whose own start instant
    matches no fixture is dropped, because the alternative — stamping the sibling
    game of the same matchup — is exactly the mis-map this replaces. Ties (two
    fixtures equidistant inside the tolerance, e.g. a genuine doubleheader) return
    None for the same reason.
    """
    from mappers.exchanges.polymarket import _fixture_surname_collision, _match_name, _name_match, _norm_name
    best = None
    best_delta = None
    for fx in fixtures:
        if granularity == "surname":
            if _fixture_surname_collision(fx.home_name, fx.away_name, style):
                continue
            names_ok = (_match_name(a, fx.home_name, style, granularity) and
                        _match_name(b, fx.away_name, style, granularity)) or \
                       (_match_name(a, fx.away_name, style, granularity) and
                        _match_name(b, fx.home_name, style, granularity))
        else:
            hn, an = _norm_name(fx.home_name, style), _norm_name(fx.away_name, style)
            names_ok = (_name_match(a, hn, style) and _name_match(b, an, style)) or \
                       (_name_match(a, an, style) and _name_match(b, hn, style))
        if not names_ok:
            continue
        fx_start = _parse_instant(getattr(fx, "start_date", None))
        if fx_start is None:
            continue
        delta = abs((fx_start - instant).total_seconds())
        if delta > _POLY_INSTANT_TOLERANCE_S:
            continue
        if best_delta is None or delta < best_delta:
            best, best_delta = fx, delta
        elif delta == best_delta:
            return None  # equidistant siblings -> ambiguous, fail closed
    return best


def _match_poly_fixture(
    parsed: "polymarket.ParsedMarket", fixtures, style: str
) -> "optic.Fixture | None":
    """Find the optic fixture for a parsed poly market by team/player-name + time.

    Dispatches on `parsed.name_granularity` ("full" default | "surname"), read
    directly off the ParsedMarket — see the _match_poly_fixture_* helpers.

    Time matching prefers `parsed.game_start_time` (Polymarket's own kickoff
    instant) over `parsed.date` (the venue-local date scraped from the slug). The
    slug date cannot be compared safely against optic's UTC `start_date` — for a US
    night game the local date is UTC-1, so the exact-date test silently never fires
    and the ±1-day fallback picks an arbitrary game of a consecutive-day series.
    That is how the Aug-5 DET@SEA market landed on the Aug-6 fixture. The date
    paths remain for bridge rows that carry no instant yet.
    """
    # team_a/team_b are already _norm_name'd by parse_question; a player-only form
    # (team_a=None) coerces to "" which _name_match treats as no-match. `date` is
    # guaranteed non-None by the caller's guard, but coerce for the type-checker.
    a, b = parsed.team_a or "", parsed.team_b or ""
    target = parsed.date or ""
    granularity = parsed.name_granularity
    instant = _parse_instant(parsed.game_start_time)
    if instant is not None:
        return _match_poly_fixture_instant(a, b, instant, fixtures, style, granularity)
    # No kickoff instant: legacy bridge rows only. Stale (already-played) markets are
    # excluded upstream by fetch.polymarket.bridge_window_sql, so what reaches here
    # without an instant is a still-upcoming market whose row predates the column.
    if granularity != "surname":
        return _match_poly_fixture_full(a, b, target, fixtures, style)
    return _match_poly_fixture_surname(a, b, target, fixtures, style, granularity)


_POLY_SLUG_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


# legacy: ticker parse — replace with the typed venue field, do not extend
def _poly_market_date(slug: str) -> str | None:
    """Extract the YYYY-MM-DD from a Polymarket single slug, or None."""
    m = _POLY_SLUG_DATE.search(slug or "")
    return m.group(1) if m else None


# legacy: ticker parse — replace with the typed venue field, do not extend
def _poly_slug_teams(slug: str) -> tuple[str, ...]:
    """The team tokens between the league prefix and the date in a poly slug.

    A game slug ("mlb-az-stl-2026-07-21") and a player-prop slug
    ("mlb-az-stl-2026-07-21-hr-<player>-<line>") share the identical
    <prefix>-<teams>-<date> head, so this returns the SAME tuple for both. It is
    the opaque join key the two-phase poly pass uses to resolve a player prop's
    fixture from the game markets that resolved by team NAME — no poly→optic
    abbrev map is needed. Returns () when the slug carries no date (nothing to
    key on). The tokens are never interpreted as team identities; only their
    equality across the game/prop slugs of the same fixture is used.
    """
    m = _POLY_SLUG_DATE.search(slug or "")
    if not m:
        return ()
    head = (slug or "")[: m.start()].rstrip("-")
    tokens = head.split("-")
    return tuple(tokens[1:])  # drop the league-prefix token


def _match_poly_game_fixture(
    parsed: "polymarket.ParsedMarket",
    market: "polymarket.PolyMarket",
    fixtures,
    style: str,
) -> "optic.Fixture | None":
    """Resolve a GAME/TEAM poly market's fixture by team NAME.

    Most forms carry both team names in parsed.team_a/team_b (matched directly).
    SPREAD_TEAM names only ONE team in the question (parsed.entity, the signed-line
    reference), but BOTH outcome LABELS are team names — so its fixture is matched
    from the two labels; build_rows then binds the question-named team's signed
    line. This is name-based (never slug), preserving flip-safety.
    """
    if parsed.side_mode is polymarket.SideMode.SPREAD_TEAM:
        labels = [o.outcome_label for o in market.outcomes]
        if len(labels) != 2:
            return None
        probe = replace(
            parsed,
            team_a=polymarket._norm_name(labels[0], style),
            team_b=polymarket._norm_name(labels[1], style),
        )
        return _match_poly_fixture(probe, fixtures, style)
    return _match_poly_fixture(parsed, fixtures, style)


def _poly_defers_to_phase_b(parsed: "polymarket.ParsedMarket") -> bool:
    """True when a parsed market must resolve in Phase B (by slug-team key), not
    by team name in Phase A.

    Three forms carry no usable second competitor name in the question: PLAYER-
    scope props; single-team GAME 3-way ML ("Will <Team> win?", team_b=None,
    Yes/No labels); and zero-competitor GAME forms (Task-u1 UFC "O/U N Rounds" /
    "Fight to Go the Distance?" / "won by KO or TKO?", team_a=None). SPREAD_TEAM
    is deliberately EXCLUDED from the zero-competitor case: its team_a=None means
    the names live in the outcome LABELS, which _match_poly_game_fixture already
    recovers in Phase A — sweeping it here would change an already-working path
    with no upside (keeps existing SPREAD_TEAM goldens byte-identical; see
    test_resolve_poly_markets_spread_resolves_via_outcome_labels).
    """
    single_team_three_way = (
        parsed.side_mode is polymarket.SideMode.THREE_WAY_FIXED and parsed.team_b is None
    )
    zero_competitor_game_form = (
        parsed.market_type.scope is Scope.GAME
        and parsed.team_a is None
        and parsed.side_mode is not polymarket.SideMode.SPREAD_TEAM
    )
    return (
        parsed.market_type.scope is Scope.PLAYER
        or single_team_three_way
        or zero_competitor_game_form
    )


def _resolve_poly_phase_b(
    deferred: list[tuple["polymarket.PolyMarket", "polymarket.ParsedMarket"]],
    fixture_by_slug_key: dict[tuple[frozenset[str], str], "optic.Fixture"],
    resolved: list[tuple["polymarket.PolyMarket", "polymarket.ParsedMarket", "optic.Fixture"]],
) -> int:
    """Resolve deferred markets by (frozenset{slug teams}, date) lookup in the
    Phase-A-seeded map; append hits to `resolved`, return how many dropped
    (no fixture seeded this run — the caller folds this into no_fixture).
    """
    dropped = 0
    for market, parsed in deferred:
        teams = _poly_slug_teams(market.slug)
        fx = fixture_by_slug_key.get((frozenset(teams), parsed.date or "")) if teams else None
        if fx is None:
            dropped += 1
            continue
        resolved.append((market, parsed, fx))
    return dropped


def _seed_poly_slug_fixture(
    fixture_by_slug_key: dict[tuple[frozenset[str], str], "optic.Fixture"],
    teams: list[str] | tuple[str, ...],
    date: str,
    fx: "optic.Fixture",
) -> None:
    """Phase A: seed (slug teams, date) → fixture for Phase B lookup.

    Doubleheader: same-teams-same-date games collapse to one key; last
    seeded wins (worst case a prop resolves to the sibling game or drops
    at guard #3 — never a cross-matchup mis-stamp).  Warn when a key is
    re-seeded with a different game_id so the collision is observable.
    """
    key = (frozenset(teams), date)
    prev = fixture_by_slug_key.get(key)
    if prev is not None and prev.game_id != fx.game_id:
        print(
            f"  polymarket: doubleheader slug key collision "
            f"{teams!r} {date}: keeping {fx.game_id}, "
            f"overwriting {prev.game_id}",
            file=sys.stderr,
        )
    fixture_by_slug_key[key] = fx


def _resolve_poly_markets(
    markets: list["polymarket.PolyMarket"],
    fixtures,
    pcfg: "polymarket.PolymarketConfig",
) -> tuple[list[tuple["polymarket.PolyMarket", "polymarket.ParsedMarket", "optic.Fixture"]],
           dict[str, int]]:
    """Two-phase resolution of parsed poly markets to optic fixtures.

    Phase A resolves game/team markets by team name (_match_poly_game_fixture)
    and seeds fixture_by_slug_key[(frozenset{slug teams}, date)] from the slug's
    team tokens. Phase B (_resolve_poly_phase_b) resolves the markets that carry
    no usable team name in the question — see _poly_defers_to_phase_b — by
    looking that key up. Returns (resolved, stats) where resolved is
    [(market, parsed, fixture)] and stats counts {unparsed, no_fixture}; the
    caller (run) does the guard-#4 optic cross-check + attach.
    """
    style = pcfg.question_style
    unparsed = no_fixture = 0
    fixture_by_slug_key: dict[tuple[frozenset[str], str], optic.Fixture] = {}
    deferred: list[tuple[polymarket.PolyMarket, polymarket.ParsedMarket]] = []
    resolved: list[tuple[polymarket.PolyMarket, polymarket.ParsedMarket, optic.Fixture]] = []

    for market in markets:
        parsed = polymarket.parse_question(market.question, pcfg)
        if parsed is None:
            unparsed += 1
            continue
        date = _poly_market_date(market.slug)
        if date is None:
            continue
        parsed = replace(parsed, date=date, game_start_time=market.game_start_time)
        if _poly_defers_to_phase_b(parsed):
            deferred.append((market, parsed))  # Phase B (needs the full map)
            continue
        fx = _match_poly_game_fixture(parsed, market, fixtures, style)
        if fx is None:
            no_fixture += 1
            continue
        teams = _poly_slug_teams(market.slug)
        if teams:
            _seed_poly_slug_fixture(fixture_by_slug_key, teams, date, fx)
        resolved.append((market, parsed, fx))

    no_fixture += _resolve_poly_phase_b(deferred, fixture_by_slug_key, resolved)
    return resolved, {"unparsed": unparsed, "no_fixture": no_fixture}


def _update_crypto_stamp(row: CanonicalRow, cr: CanonicalRow) -> None:
    """Copy crypto.com contract fields onto a canonical row."""
    # Keep Optic PM.NPO market_id when a later FIX stamp wins on the
    # same symbol (FIX carries numeric PREDICT_MARKET_ID provenance).
    keep_optic_mid = (
        row.crypto_market_id
        and "PM.NPO" in row.crypto_market_id
        and not (cr.crypto_market_id and "PM.NPO" in cr.crypto_market_id)
    )
    row.crypto_security_id = cr.crypto_security_id
    row.crypto_symbol = cr.crypto_symbol
    if not keep_optic_mid:
        row.crypto_market_id = cr.crypto_market_id
    row.crypto_outcome_id = cr.crypto_outcome_id
    row.crypto_selection_name = cr.crypto_selection_name
    row.crypto_source_ts = cr.crypto_source_ts
    # The Optic fixture ids follow the crypto stamp so any row bearing a
    # crypto_com block can load the real fixture even when the row it
    # landed on had no Optic odd of its own (crypto-only path).
    row.optic_fixture_id = cr.optic_fixture_id
    row.optic_game_id = cr.optic_game_id


def _crypto_security_id_preferred(candidate: str | None, incumbent: str | None) -> bool:
    """True when candidate should replace incumbent (lexicographic SecurityID order)."""
    if candidate is None:
        return False
    if incumbent is None:
        return True
    return candidate > incumbent


def _crypto_stamp_preferred(candidate: CanonicalRow, incumbent: CanonicalRow) -> bool:
    """Latest-wins on source timestamps; else lexicographic SecurityID."""
    verdict = crypto_optic.prefer_candidate_stamp(
        candidate.crypto_source_ts, incumbent.crypto_source_ts,
    )
    if verdict is not None:
        return verdict
    return _crypto_security_id_preferred(
        candidate.crypto_security_id, incumbent.crypto_security_id,
    )


def attach_crypto_row(
    row_index: dict[tuple, CanonicalRow],
    alt_crypto: dict[tuple[tuple, str], CanonicalRow],
    all_rows: list[CanonicalRow],
    cr: CanonicalRow,
) -> None:
    """Merge a crypto row, or append a satellite when symbols differ.

    RFQ lookup keys on exact ``source_ids.symbol``.  Same row_key with
    distinct live FIX symbols become satellites.  Optic-vs-FIX symbol
    disagreement uses latest-wins instead of a satellite.
    """
    assert cr.crypto_symbol is not None
    key = row_key(cr)
    sym = cr.crypto_symbol
    alt_key = (key, sym)

    alt_row = alt_crypto.get(alt_key)
    if alt_row is not None:
        if _crypto_stamp_preferred(cr, alt_row):
            _update_crypto_stamp(alt_row, cr)
        return

    existing = row_index.get(key)
    if existing is None:
        all_rows.append(cr)
        row_index[key] = cr
        alt_crypto[alt_key] = cr
        return

    if existing.crypto_symbol is None:
        _update_crypto_stamp(existing, cr)
        alt_crypto[alt_key] = existing
        return

    if existing.crypto_symbol == sym:
        if _crypto_stamp_preferred(cr, existing):
            _update_crypto_stamp(existing, cr)
        alt_crypto[alt_key] = existing
        return

    if _is_optic_vs_fix_conflict(existing, cr):
        _resolve_optic_fix_conflict(existing, cr, alt_crypto, key, alt_key)
        return

    _inherit_optic_odd(cr, existing)
    all_rows.append(cr)
    alt_crypto[alt_key] = cr


def _inherit_optic_odd(satellite: CanonicalRow, parent: CanonicalRow) -> None:
    """Copy Optic odd identity onto a crypto satellite so load can emit it.

    flatten_rows skips records with no optic_odds. Distinct FIX symbols for
    one Optic bet (MLB To Get A Hit vs Hits Milestone 1+) must share the
    parent's optic_id or the second symbol never reaches market_mapping.
    Mark crypto_satellite so load emits crypto.com only and does not
    re-emit the parent's Optic passthrough books (same MERGE key).
    """
    satellite.crypto_satellite = True
    if satellite.optic_id is None:
        satellite.optic_id = parent.optic_id


def _report_crypto_match_stats(
    league: str,
    fixture_dates: set[str],
    *,
    matched: int,
    flipped: int,
    no_fixture: int,
    other_date: int,
) -> None:
    """Print the crypto match tally, warning on a wholly unmatched slate.

    One other-date game is expected — it maps from its own tick's data
    dir.  A whole slate landing there is not: it means this league's
    catalogue look-back and the Optic fixture horizon never overlap, so
    no tick ever holds both halves of a fixture.  That silent zero kept
    MLS and La Liga at zero crypto.com rows for months while their
    aliases were perfectly correct, because only the no-fixture branch
    logged anything.
    """
    parts = [f"crypto: {matched} games matched"]
    if flipped:
        parts.append(f"{flipped} flipped")
    if no_fixture:
        parts.append(f"{no_fixture} no fixture")
    if other_date:
        parts.append(f"{other_date} other-date skipped")
    print(", ".join(parts), file=sys.stderr)
    if matched == 0 and other_date > 0:
        sample = ", ".join(sorted(fixture_dates)[:3]) or "none"
        print(
            f"WARN: crypto [{league}]: none of {other_date} listed games "
            f"fall on a fetched fixture date ({sample}) — check the "
            f"catalogue look-back against the Optic fixture horizon",
            file=sys.stderr)


def _is_optic_vs_fix_conflict(a: CanonicalRow, b: CanonicalRow) -> bool:
    """True when either stamp carries an Optic PM.NPO market_id."""
    return bool(
        (a.crypto_market_id and "PM.NPO" in a.crypto_market_id)
        or (b.crypto_market_id and "PM.NPO" in b.crypto_market_id)
    )


def _resolve_optic_fix_conflict(
    existing: CanonicalRow,
    cr: CanonicalRow,
    alt_crypto: dict[tuple[tuple, str], CanonicalRow],
    key: tuple,
    alt_key: tuple[tuple, str],
) -> None:
    """Replace the incumbent only when candidate timestamp is strictly later.

    Missing/unparseable timestamps keep the incumbent (plan: do not guess).
    """
    verdict = crypto_optic.prefer_candidate_stamp(
        cr.crypto_source_ts, existing.crypto_source_ts,
    )
    if verdict is None:
        print(
            f"  crypto: Optic/FIX stamp conflict unresolved "
            f"(missing timestamps) for {existing.crypto_symbol} vs "
            f"{cr.crypto_symbol}; keeping incumbent",
            file=sys.stderr,
        )
        return
    if not verdict:
        return
    old_sym = existing.crypto_symbol
    if old_sym is None:
        return
    alt_crypto.pop((key, old_sym), None)
    _update_crypto_stamp(existing, cr)
    alt_crypto[alt_key] = existing


def _update_polymarket_usa_stamp(row: CanonicalRow, ur: CanonicalRow) -> None:
    """Copy Polymarket US ticker and its venue side onto a canonical (optic) row."""
    row.polymarket_usa_market_id = ur.polymarket_usa_market_id
    row.polymarket_usa_side = ur.polymarket_usa_side


def attach_polymarket_usa_row(
    row_index: dict[tuple, CanonicalRow], ur: CanonicalRow
) -> str:
    """Stamp a Polymarket US ticker onto the matching optic row, else drop."""
    existing = row_index.get(row_key(ur))
    if existing is None:
        return "dropped_no_optic"
    _update_polymarket_usa_stamp(existing, ur)
    return "stamped"


def _usa_guard_passthrough(
    ur: CanonicalRow,
    optic_keys: set[tuple],
    stats: dict[str, int],
    odd_lookup: dict[str, optic.Odd],
    ticker: str,
    ledger: CrosscheckLedger | None,
) -> None:
    """Count Optic passthrough agree/conflict; Path 2 must not restamp."""
    parsed = row_key(ur)
    if _usa_optic_agree(parsed, optic_keys):
        stats["agree"] += 1
        return
    stats["conflict"] += 1
    shown = sorted(optic_keys)
    print(
        f"  polymarket_usa [{ur.league}] guard#4 CONFLICT: "
        f"ticker {ur.polymarket_usa_market_id} parsed as {parsed} but optic "
        f"maps it to {shown} — dropping optic passthrough (not stamping)",
        file=sys.stderr,
    )
    rfq = ""
    for odd in odd_lookup.values():
        src = (odd.source_ids or {}).get("Polymarket (USA)")
        if usa_market_id(src).casefold() != ticker.casefold():
            continue
        if not rfq and isinstance(src, dict):
            rfq = rfq_key_from_source_ids("Polymarket (USA)", src)
        strip_passthrough(odd, "Polymarket (USA)")
    if ledger is not None and rfq:
        ledger.record_disagree(
            league=ur.league,
            sportsbook="Polymarket (USA)",
            token=ticker,
            our_key=str(parsed),
            optic_key=str(shown[0]) if shown else "",
            rfq_key=rfq,
        )


def _usa_alias_maps(
    team_alias_data: AliasData, kalshi_team_aliases: dict,
) -> tuple[dict[str, str], dict[str, str]]:
    """Polymarket US aliases with Kalshi codes as fallback."""
    return (
        simple_alias_map(team_alias_data.by_exchange.get("polymarket_usa", {})),
        simple_alias_map(kalshi_team_aliases),
    )


def _log_usa_pass(league_slug: str, stats: dict[str, int]) -> None:
    """Print Path 2 stamp / strip / bind counts for this league."""
    binds = ", ".join(
        f"{k.removeprefix('bind_')}={v}" for k, v in sorted(stats.items())
        if k.startswith("bind_") and v
    )
    print(
        f"  polymarket_usa [{league_slug}]: {stats['markets']} markets / "
        f"{stats['events']} events [{binds or 'none'}], "
        f"{stats['stamped']} stamped, "
        f"{stats['dropped_no_optic']} dropped (optic didn't price), "
        f"{stats['no_bets']} unmapped (type not wired / side unbound), "
        f"{stats.get('extra_time', 0)} player props held (extra time possible), "
        f"{stats.get('no_side', 0)} bets with no typed venue side, "
        f"{stats['stripped']} stripped, "
        f"{stats['agree']} agree, {stats['conflict']} conflict-dropped",
        file=sys.stderr,
    )


def _log_usa_complements(league_slug: str, stats: dict[str, int]) -> None:
    """Print one-sided US ticker completion counts for this league."""
    if not any(stats.values()):
        return
    print(
        f"  polymarket_usa [{league_slug}] complements: "
        f"{stats['stamped']} stamped, {stats['no_optic']} no optic row, "
        f"{stats['claimed']} already claimed, "
        f"{stats['not_exhaustive']} not exhaustive (push-capable line)",
        file=sys.stderr,
    )


def _log_usa_double_chance(league_slug: str, stats: dict[str, int]) -> None:
    """Print soccer outcome-No → double chance counts for this league."""
    if not any(stats.values()):
        return
    print(
        f"  polymarket_usa [{league_slug}] double chance: "
        f"{stats['stamped']} stamped, {stats['no_optic']} no optic row, "
        f"{stats['claimed']} already claimed, "
        f"{stats['not_one_outcome']} symbol not one outcome",
        file=sys.stderr,
    )


def _usa_fixture_key(fx: Any) -> tuple[str, str, str]:
    return (fx.start_date, fx.home, fx.away)


def _usa_slug_fixtures(
    optic_usa_index: dict[str, set[tuple]], fixtures: list,
) -> dict[str, set[str]]:
    """{US symbol -> fixture ids whose Optic odds already carry it}."""
    by_key = {_usa_fixture_key(fx): pus.fixture_ref(fx) for fx in fixtures}
    out: dict[str, set[str]] = {}
    for slug, keys in optic_usa_index.items():
        for key in keys:
            fid = by_key.get((key[1], key[2], key[3]))
            if fid is not None:
                out.setdefault(slug, set()).add(fid)
    return out


def _usa_bind_events(
    markets: list[pus.UsMarket],
    fixtures: list,
    aliases: pus.TeamAliases,
    slug_fixtures: dict[str, set[str]],
    *,
    person: bool,
    stats: dict[str, int],
) -> dict[str, pus.EventBind]:
    """{event_id -> bind} for every event that binds to exactly one fixture."""
    by_event: dict[str, list[pus.UsMarket]] = {}
    for market in markets:
        by_event.setdefault(market.event_id, []).append(market)
    binds: dict[str, pus.EventBind] = {}
    evidence_by_event: dict[str, set[str]] = {}
    for event_id, members in by_event.items():
        evidence: set[str] = set()
        for market in members:
            evidence |= slug_fixtures.get(market.slug, set())
        evidence_by_event[event_id] = evidence
        bind, reason = pus.bind_event(
            members[0], fixtures, aliases, evidence, person=person,
        )
        stats[f"bind_{reason}"] = stats.get(f"bind_{reason}", 0) + 1
        if bind is not None:
            binds[event_id] = bind
    stats["events"] = len(by_event)
    return _drop_shared_fixture_binds(binds, evidence_by_event, stats)


def _drop_shared_fixture_binds(
    binds: dict[str, pus.EventBind],
    evidence_by_event: dict[str, set[str]],
    stats: dict[str, int],
) -> dict[str, pus.EventBind]:
    """One fixture, one event: a fixture two events bind to keeps neither.

    NHL preseason split-squads (2026-09-26: MTL@OTT and OTT@MTL, same
    kickoff) are two gateway events with the same teams; Optic lists one
    game. Teams + kickoff cannot tell them apart, so the event Optic's own
    passthrough names for that fixture keeps it, else all of them drop.
    """
    by_fixture: dict[str, list[str]] = {}
    for event_id, bind in binds.items():
        by_fixture.setdefault(pus.fixture_ref(bind.fixture), []).append(event_id)
    out = dict(binds)
    for fid, event_ids in by_fixture.items():
        if len(event_ids) < 2:
            continue
        named = [e for e in event_ids if fid in evidence_by_event.get(e, set())]
        keep = named[0] if len(named) == 1 else None
        for event_id in event_ids:
            if event_id != keep:
                del out[event_id]
                stats["bind_shared_fixture"] = stats.get("bind_shared_fixture", 0) + 1
    return out


def _usa_market_rows(
    markets: list[pus.UsMarket],
    binds: dict[str, pus.EventBind],
    player_index: dict,
    league_slug: str,
    stats: dict[str, int],
) -> dict[str, list[CanonicalRow]]:
    """{US symbol -> canonical rows it prices} for markets on bound events."""
    draws = pus.draw_market_ids(markets)
    out: dict[str, list[CanonicalRow]] = {}
    for market in markets:
        bind = binds.get(market.event_id)
        if bind is None:
            continue
        fx = bind.fixture
        if blocks_player_prop(market.sports_market_type, fx):
            stats["extra_time"] = stats.get("extra_time", 0) + 1
            continue
        bets = bind_player_entities(
            pus.market_bets(market, bind, draws),
            player_index, fx.start_date, fx.home, fx.away,
        )
        if not bets:
            stats["no_bets"] += 1
            continue
        rows = []
        for bet in bets:
            side = venue_side(market, bind, bet)
            if side is None:  # no typed side accounts for it: missing > wrong
                stats["no_side"] = stats.get("no_side", 0) + 1
                continue
            rows.append(pus.build_row(market, bind, bet, league_slug, side))
        if rows:
            out[market.slug] = rows
    return out


def _usa_record_strip(
    odd: optic.Odd,
    row: CanonicalRow,
    ledger: CrosscheckLedger | None,
    reason: str,
    our_key: str,
) -> None:
    """Strip one USA passthrough and block its fold key; ``reason`` says why."""
    src = (odd.source_ids or {}).get("Polymarket (USA)")
    token = usa_symbol_of(src)
    rfq = rfq_key_from_source_ids(
        "Polymarket (USA)", src if isinstance(src, dict) else None,
    )
    strip_passthrough(odd, "Polymarket (USA)")
    if ledger is None or not rfq or not token:
        return
    ledger.record_disagree(
        league=row.league,
        sportsbook="Polymarket (USA)",
        token=token,
        our_key=our_key,
        optic_key=str(row_key(row)),
        rfq_key=rfq,
        detail=reason,
    )


def _usa_strip_reason(
    row: CanonicalRow,
    market: pus.UsMarket,
    bind: pus.EventBind | None,
    rows: list[CanonicalRow] | None,
) -> tuple[str, str] | None:
    """(reason, our row key) when this Optic USA passthrough must go, else None.

    ``TWO_WAY_NO``: Optic hung a per-team two-outcome symbol (set / map
    winner) on the other team. That is the symbol's NO, which
    ``stamp_usa_complements`` stamps back from our YES row: stripped like
    before, but not a disagreement.
    """
    if bind is None:
        return "unbound", ""
    if _usa_fixture_key(bind.fixture) != (row.start_date, row.home, row.away):
        return "pinned_elsewhere", ""
    if market.sports_market_type in NOT_EQUIVALENT:
        return "not_equivalent", ""
    # The venue counts extra time; Optic's player markets stop at 90'.
    if blocks_player_prop(market.sports_market_type, bind.fixture):
        return "extra_time", ""
    if not rows:
        return None
    key = row_key(row)
    if _usa_optic_agree(key, {row_key(r) for r in rows}):
        return None
    for ur in rows:
        two_way_yes = (
            ur.market_type in TWO_WAY_OUTCOME_TYPES and ur.polymarket_usa_side == "yes"
        )
        if two_way_yes and other_team_key(row_key(ur)) == key:
            return TWO_WAY_NO, str(row_key(ur))
    return "contradicts", str(row_key(rows[0]))


def _strip_unverified_usa_passthrough(
    row_index: dict[tuple, CanonicalRow],
    odd_lookup: dict,
    markets: list[pus.UsMarket],
    binds: dict[str, pus.EventBind],
    computed: dict[str, list[CanonicalRow]],
    ledger: CrosscheckLedger | None,
    held: frozenset[tuple[str, str, str]] = frozenset(),
    held_types: frozenset[str] = frozenset(),
) -> int:
    """Drop Optic USA source_ids our structured bind contradicts.

    Symbol unknown to the gateway snapshot → keep (nothing to judge by),
    except a player row on a ``held`` soccer fixture (extra time possible),
    or a row that is one of ``held_types`` (the Optic lookalikes of this
    sport's NOT_EQUIVALENT enums, their only US source).
    Event unbound, or bound to another fixture → strip (the pin: an
    unwired type is still only allowed on the fixture the venue names).
    Bound and typed → strip unless the row (or its complement listing) is
    one we derive. Bound, type not wired, same fixture → keep — unless
    the enum is not confirmed equal to its Optic lookalike (NOT_EQUIVALENT).
    """
    if not markets and not held and not held_types:
        return 0
    by_slug = {m.slug: m for m in markets}
    by_oid = {r.optic_id: r for r in row_index.values() if r.optic_id}
    stripped = 0
    for odd in odd_lookup.values():
        src = (odd.source_ids or {}).get("Polymarket (USA)")
        slug = usa_symbol_of(src)
        row = by_oid.get(odd.id) if slug else None
        market = by_slug.get(slug) if row is not None else None
        if row is not None and market is None and _usa_fixture_key(row) in held \
                and is_player_type(row.market_type):
            _usa_record_strip(odd, row, ledger, "extra_time", "")
            stripped += 1
            continue
        if row is not None and market is None and row.market_type in held_types:
            _usa_record_strip(odd, row, ledger, "not_equivalent", "")
            stripped += 1
            continue
        if row is None or market is None:
            continue
        verdict = _usa_strip_reason(
            row, market, binds.get(market.event_id), computed.get(slug),
        )
        if verdict is not None:
            _usa_record_strip(odd, row, ledger, *verdict)
            stripped += 1
    return stripped


def _usa_stamp_rows(
    computed: dict[str, list[CanonicalRow]],
    optic_usa_index: dict[str, set[tuple]],
    row_index: dict[tuple, CanonicalRow],
    stats: dict[str, int],
    odd_lookup: dict[str, optic.Odd],
    ledger: CrosscheckLedger | None,
) -> list[CanonicalRow]:
    """Stamp derived rows unless Optic already passthroughs the symbol.

    Returns the derived rows no Optic row took.
    """
    dropped: list[CanonicalRow] = []
    for slug, rows in computed.items():
        optic_keys = optic_usa_index.get(slug)
        if optic_keys:
            _usa_guard_passthrough(
                rows[0], optic_keys, stats, odd_lookup, slug, ledger,
            )
            _usa_side_passthrough(rows, optic_keys, row_index)
            continue
        for ur in rows:
            if attach_polymarket_usa_row(row_index, ur) == "stamped":
                stats["stamped"] += 1
            else:
                stats["dropped_no_optic"] += 1
                dropped.append(ur)
    return dropped


def _usa_side_passthrough(
    rows: list[CanonicalRow],
    optic_keys: set[tuple],
    row_index: dict[tuple, CanonicalRow],
) -> None:
    """Give Optic's own US stamp the venue side our typed bind derived.

    Only where the derived row IS the passthrough row: a passthrough the
    bind does not reproduce keeps no side, so it is never guessed.
    """
    for ur in rows:
        key = row_key(ur)
        if key in optic_keys and key in row_index:
            row_index[key].polymarket_usa_side = ur.polymarket_usa_side


def _usa_load_markets(
    data_dir: Path, snapshot: SnapshotIndex | None, league_ids: frozenset[int],
) -> list[pus.UsMarket]:
    lines = snapshot.polymarket_usa_markets_for_leagues(league_ids) if snapshot else None
    return pus.load_markets(
        iter_file_or_snapshot(
            data_dir / "polymarket_usa_markets.jsonl", lines or None,
            missing_label="polymarket_usa_markets.jsonl",
        ),
        league_ids,
    )


def _run_polymarket_usa_pass(
    league: LeagueConfig,
    entries: list,
    row_index: dict[tuple, CanonicalRow],
    all_odd_lookup: dict,
    team_alias_data: AliasData,
    kalshi_team_aliases: dict,
    data_dir: Path,
    snapshot: SnapshotIndex | None,
    ledger: CrosscheckLedger | None,
) -> list[CanonicalRow]:
    """Stamp Polymarket US symbols onto optic rows from structured gateway data.

    Returns the derived rows no Optic row took.
    """
    if league.POLYMARKET_USA is None or not league.POLYMARKET_USA.league_ids:
        return []
    ucfg = league.POLYMARKET_USA
    stats = {
        "markets": 0, "events": 0, "stamped": 0, "dropped_no_optic": 0,
        "no_bets": 0, "agree": 0, "conflict": 0, "stripped": 0,
    }
    markets = _usa_load_markets(data_dir, snapshot, ucfg.league_ids)
    stats["markets"] = len(markets)
    fixtures = [e.fixture for e in entries]
    binds = _usa_bind_events(
        markets, fixtures,
        pus.TeamAliases(*_usa_alias_maps(team_alias_data, kalshi_team_aliases)),
        _usa_slug_fixtures(
            _build_optic_usa_index(row_index, all_odd_lookup), fixtures),
        person=person_league(league.league),
        stats=stats,
    )
    computed = _usa_market_rows(
        markets, binds,
        build_player_index(row_index, league.league),
        league.league, stats,
    )
    held = held_fixture_keys(fixtures) if config_sport(league) is Sport.SOCCER else frozenset()
    stats["stripped"] = _strip_unverified_usa_passthrough(
        row_index, all_odd_lookup, markets, binds, computed, ledger, held,
        held_types=not_equivalent_types(config_sport(league).value))
    dropped = _usa_stamp_rows(
        computed, _build_optic_usa_index(row_index, all_odd_lookup),
        row_index, stats, all_odd_lookup, ledger,
    )
    _log_usa_pass(league.league, stats)
    return dropped


def _update_polymarket_stamp(row: CanonicalRow, pr: CanonicalRow) -> None:
    """Copy Polymarket contract fields onto a canonical (optic) row."""
    row.polymarket_clob_token_id = pr.polymarket_clob_token_id
    row.polymarket_condition_id = pr.polymarket_condition_id
    row.polymarket_position_id = pr.polymarket_position_id
    row.polymarket_slug = pr.polymarket_slug
    row.polymarket_question = pr.polymarket_question


def attach_polymarket_row(
    row_index: dict[tuple, CanonicalRow], pr: CanonicalRow
) -> str:
    """Stamp a Polymarket source-id onto the matching optic row, else drop.

    Guard #3: a Polymarket row is emitted ONLY when an optic row for the same
    (game, market_type, line, side) already exists this run — the maker can only
    price a market optic priced. No optic row -> drop (return "dropped_no_optic"),
    never append a standalone poly row. The clob_token_id (source-id stamp) is
    added to the optic row so load_mappings emits a constructed Polymarket
    source_ids for it.

    Guard #4 (cross-clob optic-disagreement check) is enforced UPSTREAM of this
    call, in the poly pass: ``_build_optic_poly_index`` + the agree/conflict/novel
    verdict drop any token optic already maps to a different row_key before it ever
    reaches here, so this function only ever sees novel tokens.
    """
    existing = row_index.get(row_key(pr))
    if existing is None:
        return "dropped_no_optic"
    _update_polymarket_stamp(existing, pr)
    return "stamped"


def _update_novig_stamp(row: CanonicalRow, nr: CanonicalRow) -> None:
    """Copy Novig contract fields onto a canonical (optic) row."""
    row.novig_outcome_id = nr.novig_outcome_id
    row.novig_market_id = nr.novig_market_id
    row.novig_event_id = nr.novig_event_id
    row.novig_market_type = nr.novig_market_type
    row.novig_description = nr.novig_description


def attach_novig_row(
    row_index: dict[tuple, CanonicalRow], nr: CanonicalRow,
    all_rows: list[CanonicalRow],
) -> str:
    """Stamp a Novig source-id onto the matching optic row, else drop.

    Same guard #3 discipline as attach_polymarket_row: a Novig row is
    emitted ONLY when an optic row for the same (game, market_type, line,
    side) already exists this run.  No optic row -> "dropped_no_optic",
    never a standalone Novig row — without an Optic market_id there is
    nothing for load_mappings to join on.

    The cross-check against Optic's own Novig source_ids (the guard #4
    analog) is enforced upstream in the Novig pass, so this function only
    ever sees outcomes Optic did not already map.

    Exception: Optic never prices ``*_insurance`` (Novig ``*_PROTECTED``), so
    such a row is inserted like Kalshi's and stamp_insurance_rows later gives
    it the base prop's Optic odd (or nothing, when Optic has no base row).
    """
    existing = row_index.get(row_key(nr))
    if existing is None and nr.market_type.endswith(INSURANCE_SUFFIX):
        all_rows.append(nr)
        row_index[row_key(nr)] = nr
        return "stamped"
    if existing is None:
        return "dropped_no_optic"
    _update_novig_stamp(existing, nr)
    return "stamped"


def _update_dkex_stamp(row: CanonicalRow, dr: CanonicalRow) -> None:
    """Copy DKEX contract fields onto a canonical (optic) row."""
    row.dkex_symbol = dr.dkex_symbol
    row.dkex_side = dr.dkex_side
    row.dkex_event_id = dr.dkex_event_id
    row.dkex_market = dr.dkex_market
    row.dkex_period = dr.dkex_period


def attach_dkex_row(
    row_index: dict[tuple, CanonicalRow],
    alt_dkex: dict[tuple[tuple, str], CanonicalRow],
    all_rows: list[CanonicalRow],
    dr: CanonicalRow,
) -> str:
    """Stamp a DKEX (symbol, side) onto the matching optic row, else drop.

    Same guard #3 discipline as attach_novig_row: no optic row for this
    (game, market_type, line, side) means "dropped_no_optic", never a
    standalone DKEX row -- without an Optic market_id there is nothing
    for load_mappings to join on.

    There is no guard #4 cross-check here: OpticOdds does not carry DKEX
    in source_ids at all, so unlike Novig and Polymarket there is no
    passthrough path this could double-emit against.

    Satellites, exactly as ``attach_crypto_row``: DKEX lists two tickers
    for one moneyline (one per team) and a bare/"OU" pair for one player
    prop, so several symbols legitimately land on one canonical row.  The
    responder resolves an RFQ leg BY TICKER, so the second symbol becomes
    its own row rather than overwriting the first -- measured 2026-09-15,
    overwriting lost one of the two moneyline tickers on 92 of 92 matched
    events, i.e. half the moneyline flow could not have been quoted.
    """
    assert dr.dkex_symbol is not None
    key = row_key(dr)
    alt_key = (key, dr.dkex_symbol)
    if alt_key in alt_dkex:
        return "duplicate"

    existing = row_index.get(key)
    if existing is None:
        return "dropped_no_optic"

    if existing.dkex_symbol is None:
        _update_dkex_stamp(existing, dr)
        alt_dkex[alt_key] = existing
        return "stamped"

    # A different symbol for the same bet: carry it as its own row.
    _inherit_optic_odd_dkex(dr, existing)
    all_rows.append(dr)
    alt_dkex[alt_key] = dr
    return "satellite"


def _inherit_optic_odd_dkex(
    satellite: CanonicalRow, parent: CanonicalRow,
) -> None:
    """Copy Optic odd identity onto a DKEX satellite so load can emit it.

    ``flatten_rows`` skips records with no optic_odds, so a second symbol
    for one Optic bet must share the parent's optic_id or it never
    reaches market_mapping.  ``dkex_satellite`` makes load emit DKEX only,
    so the satellite does not re-emit the parent's Optic passthrough books
    under the same MERGE key.
    """
    satellite.dkex_satellite = True
    if satellite.optic_id is None:
        satellite.optic_id = parent.optic_id


def _update_underdog_stamp(row: CanonicalRow, ur: CanonicalRow) -> None:
    row.underdog_ticker = ur.underdog_ticker
    row.underdog_side = ur.underdog_side


def attach_underdog_row(
    row_index: dict[tuple, CanonicalRow],
    alt_udx: dict[tuple[tuple, str], CanonicalRow],
    all_rows: list[CanonicalRow],
    ur: CanonicalRow,
) -> str:
    """Stamp Underdog (ticker, yes/no) onto the matching optic row."""
    assert ur.underdog_ticker is not None
    key = row_key(ur)
    alt_key = (key, ur.underdog_ticker)
    if alt_key in alt_udx:
        return "duplicate"
    existing = row_index.get(key)
    if existing is None:
        return "dropped_no_optic"
    if existing.underdog_ticker is None:
        _update_underdog_stamp(existing, ur)
        alt_udx[alt_key] = existing
        return "stamped"
    satellite = ur
    satellite.underdog_satellite = True
    if satellite.optic_id is None:
        satellite.optic_id = existing.optic_id
    all_rows.append(satellite)
    alt_udx[alt_key] = satellite
    return "satellite"


def _run_underdog_pass(
    league: LeagueConfig,
    entries: list,
    row_index: dict[tuple, CanonicalRow],
    all_rows: list[CanonicalRow],
    data_dir: Path,
    *,
    alert_publisher: AlertPublisher | None = None,
) -> None:
    ucfg = league.UNDERDOG
    if ucfg is None:
        return
    catalogue = underdog_pass.read_catalogue(data_dir / "underdog_markets.jsonl")
    if not catalogue:
        return
    reject_alerts: list[str] = []
    tally = underdog_pass.run_pass(
        catalogue, ucfg, entries, league=str(league.league),
        attach=attach_underdog_row, row_index=row_index, all_rows=all_rows,
        witness_reject_alerts=reject_alerts,
    )
    print(f"  underdog [{league.league}]: {tally}", file=sys.stderr)
    publish_udx_witness_alerts(
        str(league.league),
        reject_alerts,
        alert_publisher=alert_publisher,
    )


def attach_sxbet_row(
    row_index: dict[tuple, CanonicalRow],
    odd_lookup: dict,
    sr: CanonicalRow,
) -> str:
    """Stamp an SX (hash, taker outcome) onto the matching optic row, else drop.

    Guard #3, as for Novig / DKEX: no optic row for this (game,
    market_type, line, side) is "dropped_no_optic", never a standalone row.
    One marketHash carries both outcomes, so a second hash on a row already
    stamped is "duplicate" and dropped rather than kept as a satellite (no
    SX market lists the same canonical bet twice today; the tally would show
    it).  A row whose Optic odd already carries ANOTHER SX hash is
    "optic_other_hash": load emits Optic's passthrough for it, so a stamp
    would never reach the table.
    """
    if sr.sx_market_hash is None or sr.sx_outcome is None:  # sxbet.build_rows always stamps both
        return "dropped_no_optic"
    existing = row_index.get(row_key(sr))
    if existing is None:
        return "dropped_no_optic"
    if existing.sx_market_hash is not None:
        return "duplicate"
    odd = odd_lookup.get(existing.optic_id) if existing.optic_id else None
    if (getattr(odd, "source_ids", None) or {}).get(sxbet.SPORTSBOOK):
        return "optic_other_hash"
    existing.sx_market_hash = sr.sx_market_hash
    existing.sx_outcome = sr.sx_outcome
    existing.sx_event_id = sr.sx_event_id
    existing.sx_type = sr.sx_type
    return "stamped"


def _run_sxbet_pass(
    league: LeagueConfig,
    entries: list,
    row_index: dict[tuple, CanonicalRow],
    data_dir: Path,
    odd_lookup: dict,
) -> None:
    """Match one league's SX catalogue onto this run's optic rows."""
    cfg = league.SXBET
    if cfg is None:
        return
    tally = sxbet_pass.SxTally()
    events = sxbet_pass.read_catalogue_file(data_dir, cfg.slug, tally)
    if not events:
        print(f"  sxbet [{league.league}]: no catalogue rows", file=sys.stderr)
        return
    sxbet_pass.run_pass(
        cfg, entries, list(row_index.values()), odd_lookup, events,
        key_of=row_key,
        attach=lambda sr: attach_sxbet_row(row_index, odd_lookup, sr),
        tally=tally,
    )
    print(tally.line(str(league.league)), file=sys.stderr)
    if os.environ.get("SXBET_DEBUG") == "1":
        for line in sxbet_pass.debug_lines(tally):
            print(line, file=sys.stderr)


def _run_dkex_pass(
    league: LeagueConfig,
    entries: list,
    row_index: dict[tuple, CanonicalRow],
    all_rows: list[CanonicalRow],
    data_dir: Path,
) -> None:
    """Match one league's DKEX catalogue onto this run's optic rows."""
    dcfg = league.DKEX
    if dcfg is None:
        return
    dkex_pass.run_pass(
        str(league.league),
        dcfg,
        entries,
        row_index,
        all_rows,
        data_dir,
        attach=attach_dkex_row,
    )


# === Golden file helpers ===

def gold_row(r: CanonicalRow) -> dict:
    """Extract the golden-file fields from a canonical row.

    The 12 fields that fully identify a mapping: the merge key
    (what bet) plus the exchange IDs (what we mapped it to).
    """
    return {
        "start_date": r.start_date,
        "home": r.home,
        "away": r.away,
        "market_type": r.market_type,
        "entity": r.entity,
        "line": normalize_line(r.line),
        "side": r.side,
        "grouping_key": r.grouping_key,
        "optic_id": r.optic_id,
        "px_line_id": r.px_line_id,
        "kalshi_ticker": r.kalshi_ticker,
        "kalshi_side": r.kalshi_side,
    }


def gold_sort_key(r: CanonicalRow) -> tuple:
    """Deterministic sort key for golden file output.

    Wraps row_key() but replaces None with sort-friendly sentinels
    so Python 3 doesn't raise on mixed-type comparisons.
    """
    k = row_key(r)
    return (
        k[0],                                             # league
        k[1], k[2], k[3], k[4],                          # start_date, home, away, market_type
        k[5] or "",                                       # entity
        (0, 0.0) if k[6] is None else (1, k[6]),         # line
        k[7],                                             # side
        k[8] or "",                                       # grouping_key
    )


# === JSON serializer ===

def _apply_coarse_provenance(rows: list[CanonicalRow]) -> None:
    """Stamp Tier-B match-method enums when not already set."""
    for row in rows:
        if row.fixture_match_method is None:
            row.fixture_match_method = "optic_schedule"
        if row.market_match_method is not None:
            continue
        if row.kalshi_ticker is not None:
            row.market_match_method = "kalshi_ticker"
        elif row.polymarket_clob_token_id is not None:
            row.market_match_method = "poly_rule"
        elif row.novig_outcome_id is not None:
            row.market_match_method = "novig_optic_id"
        elif row.dkex_symbol is not None:
            row.market_match_method = "dkex_symbol"
        elif row.sx_market_hash is not None:
            row.market_match_method = "sxbet_catalogue"
        elif row.stx_market_id is not None:
            row.market_match_method = "stx_rules"
        elif row.crypto_security_id is not None:
            row.market_match_method = "crypto_fixture"
        elif row.huddle_selection_id is not None:
            row.market_match_method = "huddle_sr_id"
        elif row.px_line_id is not None:
            row.market_match_method = "px_event"
        elif row.optic_id is not None:
            row.market_match_method = "optic_passthrough"


def canonical_row_to_json(
    row: CanonicalRow,
    odd_lookup: dict[str, optic.Odd],
    game_ref_lookup: dict[str, optic.GameRef],
    *,
    run_provenance: dict | None = None,
    sport: Sport | None = None,
) -> dict:
    """Serialize a merged canonical row to the benchmark JSON format.

    Each source sub-object is None when that source has no match.
    """
    odd = odd_lookup[row.optic_id] if row.optic_id is not None else None
    row_sport = sport if sport is not None else sport_for_league(row.league)

    result: dict = {
        "key": {
            "sport": row_sport,
            "league": row.league,
            "start_date": row.start_date,
            "home": row.home,
            "away": row.away,
            "market_type": row.market_type,
            "entity": row.entity,
            "line": row.line,
            "side": row.side,
            "grouping_key": row.grouping_key,
        },
        "check": {
            "optic_selection": odd.selection if odd is not None else None,
            "kalshi_title": row.kalshi_title,
            "px_market_name": row.px_market_name,
            "px_selection": row.px_selection_display_name,
        },
    }

    # Optic
    if odd is not None:
        assert row.optic_id is not None
        ref = game_ref_lookup[row.optic_id]
        result["optic_odds"] = {
            "fixture_id": ref.fixture_id,
            "game_id": ref.game_id,
            "market_id": odd.market_id,
            "selection": odd.selection,
            # Coerced to match Optic's prices_dedup_state in BQ, which
            # stores "" and 0.0 rather than null for these fields.
            # In TF these are nullable when, given the above, they
            # could actually be NOT NULL...
            "selection_line": odd.selection_line or "",
            "points": odd.points if odd.points is not None else 0.0,
            "grouping_key": odd.grouping_key,
            "source_ids": odd.source_ids or None,
        }
    else:
        result["optic_odds"] = None
    result["optic_is_live"] = row.optic_is_live
    if row.crypto_satellite:
        result["crypto_satellite"] = True
    if row.dkex_satellite:
        result["dkex_satellite"] = True
    if row.underdog_satellite:
        result["underdog_satellite"] = True
    if row.stx_satellite:
        result["stx_satellite"] = True
    if row.polymarket_usa_satellite:
        result["polymarket_usa_satellite"] = True
    if row.kalshi_complement:
        result["kalshi_complement"] = True

    # Kalshi
    if row.kalshi_ticker is not None:
        result["kalshi"] = {
            "market_ticker": row.kalshi_ticker,
            "side": row.kalshi_side,
        }
    else:
        result["kalshi"] = None

    # Prophet X
    if row.px_line_id is not None:
        result["prophet_x"] = {
            "event_id": row.px_event_id,
            "line_id": row.px_line_id,
        }
    else:
        result["prophet_x"] = None

    # crypto.com — novel rows, no Optic cross-check.  security_id (the
    # FIX SecurityID) is the source-id stamp, the px_line_id / Kalshi
    # ticker analog.
    if row.crypto_security_id is not None:
        result["crypto_com"] = {
            "security_id": row.crypto_security_id,
            "symbol": row.crypto_symbol,
            "market_id": row.crypto_market_id,
            "outcome_id": row.crypto_outcome_id,
            "selection_name": row.crypto_selection_name,
            # Optic fixture of the matched game — lets crypto-only rows
            # load the real fixture_id/game_id (see _crypto_only_base).
            "fixture_id": row.optic_fixture_id,
            "game_id": row.optic_game_id,
        }
    else:
        result["crypto_com"] = None

    # Polymarket — novel rows, no Optic cross-check for the token map.
    # clob_token_id is the source-id stamp (crypto_security_id analog).
    if row.polymarket_clob_token_id is not None:
        result["polymarket"] = {
            "clob_token_id": row.polymarket_clob_token_id,
            "condition_id": row.polymarket_condition_id,
            "position_id": row.polymarket_position_id,
            "slug": row.polymarket_slug,
            "question": row.polymarket_question,
        }
    else:
        result["polymarket"] = None

    # market_id is None on an Optic passthrough row: its symbol is Optic's,
    # only the typed venue side is ours (flatten_rows merges the two).
    if row.polymarket_usa_market_id is not None or row.polymarket_usa_side is not None:
        result["polymarket_usa"] = {
            "market_id": row.polymarket_usa_market_id,
            "selection_id": row.polymarket_usa_side,
        }
    else:
        result["polymarket_usa"] = None

    # Novig — novel rows matched by Optic id. outcome_id is the source-id
    # stamp; the triple mirrors Optic's own Novig source_ids exactly.
    if row.novig_outcome_id is not None:
        result["novig"] = {
            "event_id": row.novig_event_id,
            "market_id": row.novig_market_id,
            "outcome_id": row.novig_outcome_id,
            "market_type": row.novig_market_type,
            "description": row.novig_description,
        }
    else:
        result["novig"] = None

    # DKEX -- novel rows matched by name off the venue catalogue.  The
    # stamp is the (symbol, side) PAIR: one symbol is one binary market
    # carrying both canonical sides, so the symbol alone is not a key.
    if row.dkex_symbol is not None and row.dkex_side is not None:
        result["dkex"] = {
            "market_ticker": row.dkex_symbol,
            "side": row.dkex_side,
            "event_id": row.dkex_event_id,
            "market": row.dkex_market,
            "period": row.dkex_period,
        }
    else:
        result["dkex"] = None

    if row.underdog_ticker is not None and row.underdog_side is not None:
        result["underdog"] = {
            "market_id": row.underdog_ticker,
            "selection_id": row.underdog_side,
        }
    else:
        result["underdog"] = None

    if row.stx_market_id is not None and row.stx_side is not None:
        result["stx"] = stx_source_ids(row.stx_market_id, row.stx_side, row.stx_event_id, row.stx_tie_pays_half)

    # SX Bet -- novel rows matched off the venue catalogue.  The stamp is the
    # (hash, taker outcome) PAIR; load writes Optic's own id shape from it.
    # Present only when stamped, so records (and golden files) of leagues
    # without SX are unchanged.
    if row.sx_market_hash is not None and row.sx_outcome is not None:
        result["sxbet"] = {
            "event_id": row.sx_event_id,
            "market_id": row.sx_market_hash,
            "selection_id": sxbet.selection_id(row.sx_market_hash, row.sx_outcome),
            "type": row.sx_type,
        }

    if row.runshop_tx_odds_fixture_id is not None and row.runshop_market_id is not None:
        result["runshop"] = {
            "tx_odds_fixture_id": row.runshop_tx_odds_fixture_id,
            "market_id": row.runshop_market_id,
        }

    if row.huddle_selection_id is not None:
        result["huddle"] = {
            "selection_id": row.huddle_selection_id,
            "event_id": row.huddle_event_id,
            "market_id": row.huddle_market_id,
        }

    if run_provenance is not None:
        prov: dict = dict(run_provenance)
        for key in (
            "fixture_match_method", "market_match_method", "verify_tier",
            "mapping_audit_event_id", "market_rule_id", "entity_alias_ids",
            "fixture_rule_id",
        ):
            val = getattr(row, key, None)
            if val is not None:
                prov[key] = val
        result["provenance"] = prov

    return result


def _check_alias_completeness(
    league: LeagueConfig,
    index: ScheduleIndex,
    team_canonicals: set[str],
    abbr_overrides: dict[str, str],
    *,
    alias_enforcement: str = "raise",
) -> None:
    """Warn when Optic abbreviations are missing from mapping_entities."""
    optic_teams = {t for k in index for t in (k.home, k.away)}
    known = known_alias_codes(team_canonicals, abbr_overrides)
    missing = sorted(optic_teams - known)
    if not missing:
        return
    if alias_enforcement == "warn":
        print(
            f"  optic [{league.league}]: {len(missing)} abbreviation(s) not "
            f"in mapping_entities (alias_enforcement=warn): "
            f"{', '.join(missing)}",
            file=sys.stderr,
        )
        return
    if (
        config_sport(league) == Sport.ESPORTS
        or config_slug(league) == "international_club_friendlies"
    ):
        print(
            f"  optic [{league.league}]: {len(missing)} abbreviation(s) not "
            f"in mapping_entities (roster churn, not enforced): "
            f"{', '.join(missing)}",
            file=sys.stderr,
        )
        return
    print(
        f"  optic [{league.league}]: {len(missing)} abbreviation(s) not "
        f"in mapping_entities (BQ SoT; pin via console): "
        f"{', '.join(missing)}",
        file=sys.stderr,
    )


def _apply_crypto_id_overrides(
    out: dict[str, AliasValue], slug: str, canonicals: set[str],
) -> None:
    """Apply CRYPTO_TEAM_ID_OVERRIDES in place: code beats the tip alias."""
    for cid, canonical in CRYPTO_TEAM_ID_OVERRIDES.get(slug, {}).items():
        if canonical not in canonicals:
            print(
                f"  crypto [{slug}]: code override {cid} → {canonical} "
                f"not a known key this run; keeping {out.get(cid)!r}",
                file=sys.stderr,
            )
            continue
        if out.get(cid) not in (None, canonical):
            print(
                f"  crypto [{slug}]: code override {cid} → {canonical} "
                f"replaces tip {out[cid]!r}",
                file=sys.stderr,
            )
        out[cid] = canonical


def _with_code_crypto_team_ids(
    tip_aliases: Mapping[str, AliasValue],
    slug: str,
    canonicals: set[str],
) -> dict[str, AliasValue]:
    """Tip crypto_id aliases plus the code-owned CRYPTO_TEAM_IDS for this league.

    The code table only fills ids the tip lacks; on a disagreement the tip
    wins and the conflict is printed.  An entry whose canonical is unknown
    (neither a tip canonical nor, at the call site, an Optic schedule key)
    is skipped.  CRYPTO_TEAM_ID_OVERRIDES are the exception: code beats a
    known-wrong tip alias (CLAUDE.md: code should win).
    """
    out: dict[str, AliasValue] = dict(tip_aliases)
    _apply_crypto_id_overrides(out, slug, canonicals)
    unknown: list[str] = []
    for cid, canonical in CRYPTO_TEAM_IDS.get(slug, {}).items():
        existing = out.get(cid)
        if existing is not None:
            if existing != canonical:
                print(
                    f"  crypto [{slug}]: code team id {cid} → {canonical} "
                    f"conflicts with tip {existing!r}; keeping tip",
                    file=sys.stderr,
                )
            continue
        if canonical not in canonicals:
            unknown.append(canonical)
            continue
        out[cid] = canonical
    if unknown:
        print(
            f"  crypto [{slug}]: {len(unknown)} code team id(s) skipped — "
            f"key neither a tip canonical nor on this run's schedule",
            file=sys.stderr,
        )
    return out


def _crypto_alias_canonicals(
    team_canonicals: set[str], entries: list[ScheduleEntry],
) -> set[str]:
    """Canonicals a code crypto id may target: tip keys plus schedule keys.

    UEL/UECL / atp_challenger keys are Optic schedule abbreviations with no
    tip entity (2026-10-22); restricting to tip keys skipped every one.
    """
    return team_canonicals | {
        k for e in entries for k in (e.fixture.home, e.fixture.away)}


def _aliases_for_run(
    *,
    league: LeagueConfig,
    abbr_overrides: dict[str, str],
    snap: SotSnapshot,
) -> tuple[AliasData, AliasData, dict[str, str]]:
    """Invert the coalesced BQ tip into alias maps."""
    slug = config_slug(league)
    team_type = tip_entity_type(snap, slug)
    player_type = tip_player_entity_type(snap, slug)
    team_alias_data, bq_optic = entities_to_alias_data(
        snap.entities, league=slug, entity_type=team_type,
    )
    player_alias_data, _ = entities_to_alias_data(
        snap.entities, league=slug, entity_type=player_type,
    )
    return (
        team_alias_data,
        player_alias_data,
        {**bq_optic, **abbr_overrides},
    )


# === Main pipeline ===

def run(
    data_dir: Path,
    league: LeagueConfig,
    orphan_dist: int = 5,
    *,
    snapshot: SnapshotIndex | None = None,
) -> PipelineResult:
    """Execute the full merge pipeline for one league and date."""

    cc_ledger = CrosscheckLedger() if crosscheck_enabled() else None
    snap = load_snapshot()
    league_row = tip_league_row(snap, config_slug(league))
    if snap is not None:
        league = overlay_league_config(league, snap.market_rules, league_row)

    # Derive lookups from the league's MarketType enum
    market_type_order: dict[str, int] = {
        mt.value: i for i, mt in enumerate(league.OUTPUT_ORDER)
    }
    player_types: set[str] = {
        mt.value for mt in league.MarketType
        if mt.scope == Scope.PLAYER
    }
    spread_types: set[str] = {
        mt.value for mt in league.MarketType
        if mt.shape == Shape.SPREAD
    }

    # === Load aliases from the coalesced BQ tip ===
    _optic_lines = (
        snapshot.optic_lines(
            league.OPTIC.league_id, league.OPTIC.extra_league_ids,
        )
        if snapshot is not None else None
    )
    seed_used, seed_overrides = _sot_alias_seed(snap, config_slug(league))
    abbr_overrides = bootstrap_empty_abbrs(
        data_dir, league.OPTIC.league_id, Path(),
        extra_league_ids=league.OPTIC.extra_league_ids,
        optic_lines=_optic_lines,
        seed_used=seed_used,
        seed_overrides=seed_overrides,
    )

    team_alias_data, player_alias_data, abbr_overrides = (
        _aliases_for_run(
            league=league,
            abbr_overrides=abbr_overrides,
            snap=snap,
        )
    )
    team_canonicals = team_alias_data.canonicals

    px_team_aliases = team_alias_data.by_exchange.get("px", {})
    # Polymarket US falls back to these code aliases (_usa_alias_maps);
    # Kalshi itself maps by typed ids and reads no aliases.
    kalshi_team_aliases = team_alias_data.by_exchange.get("kalshi", {})
    crypto_entity_names = _crypto_entity_names(snap, config_slug(league))
    px_player_aliases = simple_alias_map(
        player_alias_data.by_exchange.get("px", {}))
    # crypto player aliases key on the feed's PLAYER_ID, not a name —
    # the same id-over-name rationale as the crypto_id team submap.
    crypto_player_aliases = simple_alias_map(
        player_alias_data.by_exchange.get("crypto_id", {}))
    # Name-keyed fallback for props sourced from crypto_underlying_securities,
    # which carry no PLAYER_ID.  Keyed on the normalized crypto display name
    # so it lines up with normalize_player_name(participant) at match time.
    crypto_name_player_aliases = {
        normalize_player_name(name): canonical
        for name, canonical in simple_alias_map(
            player_alias_data.by_exchange.get("crypto_name", {})).items()
    }

    # === Fetch time and fixture horizon ===
    #
    # The data directory name encodes the UTC fetch timestamp
    # (e.g. data/2026-03-13/18_30).  Games starting after
    # fetch_time + the league's Optic horizon were never requested
    # from Optic, so their absence is expected, not an error.
    fetch_time = datetime.strptime(
        f"{data_dir.parent.name}T{data_dir.name}", "%Y-%m-%dT%H_%M",
    ).replace(tzinfo=UTC)
    horizon_hours = league.OPTIC.horizon_hours
    horizon_cutoff = fetch_time + timedelta(hours=horizon_hours)

    # === Parse PX events ===
    #
    # First pass: collect ALL event IDs before league filtering.
    # Used in the market loop to distinguish "other league" (skip)
    # from "genuinely missing parent event" (raise).
    all_px_event_ids: set[int] = set()

    # Second pass: parse events filtered by tournament_id.
    events: list[px.ParsedEvent] = []
    event_by_id: dict[int, px.ParsedEvent] = {}
    # Per-event resolved abbreviation maps for classify_and_enrich.
    # Built from the event's competitors so ambiguous abbreviations
    # (e.g. PX "COL" = both Columbia and Colorado) are already
    # disambiguated by name before market classification.
    event_team_maps: dict[int, dict[str, str]] = {}
    event_raw_markets: dict[int, list[px.Market]] = defaultdict(list)
    px_skipped_count = 0
    event_team_id_maps: dict[int, dict[int, str]] = {}

    # Local for pyright narrowing; None means the league has no PX
    # coverage and the whole PX section is skipped (containers above
    # stay empty, so PX matching and output no-op downstream).
    px_cfg = league.PX
    if px_cfg is not None:
        px_ev_lines = (
            snapshot.px_event_lines(str(px_cfg.tournament_id)) if snapshot else None
        )
        px_mk_lines = (
            snapshot.px_market_lines(str(px_cfg.tournament_id)) if snapshot else None
        )
        for line in iter_file_or_snapshot(
            data_dir / "prophetx_events.jsonl", px_ev_lines,
            missing_label="prophetx_events.jsonl",
        ):
            all_px_event_ids.add(json.loads(line)["event_id"])

        for line in iter_file_or_snapshot(
            data_dir / "prophetx_events.jsonl", px_ev_lines,
            missing_label="prophetx_events.jsonl",
        ):
            event = px.parse_event(line, px_cfg, px_team_aliases)
            if event is None:
                continue
            events.append(event)
            event_by_id[event.raw.event_id] = event
            etm: dict[str, str] = {}
            for c in event.raw.competitors:
                canonical = resolve_team(
                    c.abbreviation, px_team_aliases, c.name, c.id)
                etm[c.abbreviation] = canonical
                etm[canonical] = canonical
            for c in event.raw.competitors:
                if c.name:
                    etm.setdefault(c.name, etm[c.abbreviation])
            event_team_maps[event.raw.event_id] = etm

        # === Parse PX markets and attach to events (unclassified) ===
        for line in iter_file_or_snapshot(
            data_dir / "prophetx_markets.jsonl", px_mk_lines,
            missing_label="prophetx_markets.jsonl",
        ):
            market = px.parse_market(line)
            event = event_by_id.get(market.sport_event_id)
            if event is None:
                if market.sport_event_id in all_px_event_ids:
                    continue
                raise ValueError(
                    f"PX market {market.id} ({market.name!r}): "
                    f"sport_event_id {market.sport_event_id} not found "
                    f"in prophetx_events.jsonl")
            event_raw_markets[event.raw.event_id].append(market)

        # === Filter out unrecognized PX market names ===
        # Had to add this so pipeline doesn't raise for typos: "Howie Fleming Total Asissts"
        px_skipped: list[str] = []
        for eid, raw_markets in event_raw_markets.items():
            known = []
            for m in raw_markets:
                if px.is_known_market(m.name, px_cfg):
                    known.append(m)
                else:
                    px_skipped.append(m.name)
            event_raw_markets[eid] = known
        px_skipped_count = len(px_skipped)

        # === Resolve team total markets via market ID modulo ===
        for eid, etm in event_team_maps.items():
            event = event_by_id[eid]
            raw_markets = event_raw_markets.get(eid, [])
            team_totals = [
                m for m in raw_markets
                if px.classify_market(m.name, m.type, px_cfg).market_type.scope
                == Scope.TEAM
            ]
            event_team_id_maps[eid] = px.build_team_id_map(
                event.raw.competitors, team_totals, etm, eid)

        # === Classify PX markets ===
        for eid, raw_markets in event_raw_markets.items():
            event = event_by_id[eid]
            team_id_map = event_team_id_maps[eid]
            etm = event_team_maps[eid]
            for market in raw_markets:
                classified = px.classify_and_enrich(
                    market, px_cfg, team_id_map, etm)
                event.markets.append(classified)

    # === Build schedule index from Optic fixtures ===
    optic_cfg = replace(league.OPTIC, abbr_overrides=abbr_overrides)
    optic_src: Path | list[str] = (
        snapshot.optic_lines(
            league.OPTIC.league_id, league.OPTIC.extra_league_ids,
        )
        if snapshot is not None
        else data_dir / "optic_fixtures_odds.jsonl"
    )
    optic_fixtures = optic.load_fixtures(optic_src, optic_cfg)
    index: ScheduleIndex = {
        key: [ScheduleEntry(f) for f in fixtures]
        for key, fixtures in optic_fixtures.items()
    }
    all_entries = [e for entries in index.values() for e in entries]
    live_count = sum(1 for e in all_entries if e.fixture.is_live)
    dh_keys = sum(1 for entries in index.values() if len(entries) > 1)
    print(f"\n--- {league.league} ---", file=sys.stderr)
    parts = [f"optic: {len(all_entries)} fixtures loaded"]
    if dh_keys:
        parts.append(f"{dh_keys} doubleheader MatchKeys")
    if live_count:
        parts.append(f"{live_count} live (add-only)")
    print(", ".join(parts), file=sys.stderr)

    enforcement = tip_alias_enforcement(snap, config_slug(league))
    _check_alias_completeness(
        league,
        index,
        team_canonicals,
        abbr_overrides,
        alias_enforcement=enforcement,
    )

    fixture_dates = {key.game_date for key in index}
    # Built after the schedule: code-owned crypto ids may target an Optic
    # schedule key the tip has no entity for (UEL/UECL, atp_challenger).
    crypto_team_aliases = _with_code_crypto_team_ids(
        team_alias_data.by_exchange.get("crypto_id", {}),
        config_slug(league),
        _crypto_alias_canonicals(team_canonicals, all_entries),
    )

    # === Match PX events to schedule ===
    #
    # Away/home flips: PX sometimes swaps home and away relative to
    # Optic, especially for NCAAB neutral-site games.  Auto-recovery
    # is safe because PX side resolution is identity-based: each
    # selection carries a numeric competitor_id, resolved via
    # build_comp_map → resolve_side_label to a canonical team
    # abbreviation.  The PX event's home/away labeling is consumed
    # only by _sides() for the initial match key and is never used
    # in row building.  See docs/match-logic.md for the full argument.
    px_other_date = 0
    px_flip = 0
    px_no_fixture = 0
    px_beyond_horizon = 0
    px_live_mismatch = 0

    for event in events:
        attached = match_event(event, index, px_team_aliases)
        if attached:
            event_team_maps[event.raw.event_id] = px_event_team_map(
                event, px_team_aliases)
        if not attached:
            recovered = _recover_px_event(
                event, index, fixture_dates, px_team_aliases,
                team_canonicals, event_team_maps,
                player=person_league(config_slug(league)),
                fetch_time=fetch_time,
                horizon_cutoff=horizon_cutoff,
                league_name=str(league.league),
            )
            if recovered == "other_date":
                px_other_date += 1
                continue
            if recovered == "flip":
                px_flip += 1
                continue
            if recovered == "beyond":
                px_beyond_horizon += 1
                continue
            if recovered == "skip":
                px_no_fixture += 1
                continue

        # PX event matched. In-play for load is Optic is_live, not PX.
        k = event.match_key
        candidates = lookup_oriented(index, k.game_date, k.home, k.away) or (
            lookup_oriented(index, k.game_date, k.away, k.home))
        entry = (
            _pick_entry_by_time(candidates, event.raw.scheduled)
            if candidates else None
        )
        if (event.is_live
                and entry is not None
                and not entry.fixture.is_live):
            print(
                f"  px [{league.league}] event {event.raw.event_id}: "
                f"PX status {event.raw.status!r} but Optic says "
                f"unplayed for {k.game_date} {k.away}@{k.home}",
                file=sys.stderr)
            px_live_mismatch += 1

    px_matched = (len(events) - px_other_date - px_flip
                  - px_no_fixture - px_beyond_horizon)
    px_parts = [f"px: {px_matched} events matched"]
    if px_flip:
        px_parts.append(f"{px_flip} flipped")
    if px_no_fixture:
        px_parts.append(f"{px_no_fixture} no fixture")
    if px_other_date:
        px_parts.append(f"{px_other_date} other-date skipped")
    if px_beyond_horizon:
        px_parts.append(
            f"{px_beyond_horizon} events beyond {horizon_hours}h horizon")
    if px_live_mismatch:
        px_parts.append(f"{px_live_mismatch} live/unplayed mismatch")
    if px_skipped_count:
        px_parts.append(f"{px_skipped_count} markets skipped (no matching type)")
    print(", ".join(px_parts), file=sys.stderr)

    # === Parse Kalshi markets and match to schedule ===
    #
    # A Kalshi game is an Optic fixture by id, never by ticker: the
    # market's milestone carries Optic's fixture id, the Sportradar id and
    # the sides' Optic competitor ids, and Optic's own source_ids name
    # Kalshi tickers.  A market whose milestone joins no fixture of this
    # league belongs to another league (or an unscheduled game).
    #
    # None means the league has no Kalshi coverage and the containers
    # below stay empty, so downstream matching no-ops.
    kalshi_cfg = league.KALSHI

    kalshi_events = 0
    kalshi_game = 0
    kalshi_unscoped_skipped = 0
    kalshi_unoriented = 0
    kalshi_split = 0
    kalshi_game_markets: list[kalshi.Market] = []
    # Every ticker in Kalshi's open book for this sport: tells a stale
    # Optic source_id (a closed contract) from a real disagreement.
    kalshi_tickers: set[str] = set()
    if kalshi_cfg is not None:
        kalshi_lines = (
            snapshot.kalshi_lines_for_sport(kalshi_cfg.sport) if snapshot else None
        )
        for line in iter_file_or_snapshot(
            data_dir / "kalshi_markets.jsonl", kalshi_lines,
            missing_label="kalshi_markets.jsonl",
        ):
            market = kalshi.parse_market_line(line)
            if market is None or market.sport != kalshi_cfg.sport:
                continue
            kalshi_tickers.add(market.ticker)
            if kalshi.scoped_market_type(market, kalshi_cfg) is None:
                kalshi_unscoped_skipped += 1
                continue
            kalshi_game_markets.append(market)

    kalshi_by_fixture_id = {e.fixture.fixture_id: e for e in all_entries}
    kalshi_by_sportradar_id = {
        e.fixture.sportradar_id: e for e in all_entries if e.fixture.sportradar_id}
    kalshi_by_competitors = _competitor_pair_index(all_entries)
    kalshi_by_optic_ref = _optic_ref_index(all_entries, kalshi_game_markets)
    kalshi_groups: dict[int, tuple[ScheduleEntry, list[kalshi.Market]]] = {}
    for market in kalshi_game_markets:
        entry = _milestone_entry(
            market.milestone, kalshi_by_fixture_id, kalshi_by_sportradar_id,
            kalshi_by_competitors, kalshi_by_optic_ref)
        if entry is not None:
            kalshi_groups.setdefault(id(entry), (entry, []))[1].append(market)

    for entry, markets in kalshi_groups.values():
        milestone_ids = {(m.milestone or {}).get("id") for m in markets}
        if len(milestone_ids) != 1:
            # Two Kalshi games joined one fixture: neither is trusted.
            print(
                f"  kalshi: fixture {entry.fixture.fixture_id}: "
                f"{len(milestone_ids)} milestones join it — skipping",
                file=sys.stderr)
            kalshi_split += len(markets)
            continue
        flipped = _milestone_orientation(entry, markets)
        if flipped is None:
            print(
                f"  kalshi: fixture {entry.fixture.fixture_id}: no id "
                f"evidence for which side is home — skipping "
                f"{len(markets)} market(s)",
                file=sys.stderr)
            kalshi_unoriented += len(markets)
            continue
        if flipped:
            markets = [
                m.model_copy(update={"milestone": {
                    **(m.milestone or {}),
                    "home_id": (m.milestone or {}).get("away_id"),
                    "away_id": (m.milestone or {}).get("home_id"),
                }})
                for m in markets
            ]
        entry.kalshi_markets = _resolve_off_milestone_sides(entry, markets)
        kalshi_events += 1
        kalshi_game += len(markets)

    kalshi_parts = [f"kalshi: {kalshi_events} games matched",
                    f"{kalshi_game} markets matched"]
    if kalshi_unscoped_skipped:
        kalshi_parts.append(
            f"{kalshi_unscoped_skipped} with an unmapped Kalshi scope skipped")
    if kalshi_unoriented:
        kalshi_parts.append(f"{kalshi_unoriented} without home/away evidence skipped")
    if kalshi_split:
        kalshi_parts.append(f"{kalshi_split} on a fixture two milestones join skipped")
    print(", ".join(kalshi_parts), file=sys.stderr)

    # === Parse crypto.com selections and match to schedule ===
    #
    # Gated per-league: only leagues with a CryptoConfig (league.CRYPTO)
    # have FIX-feed coverage, so leagues without it are untouched.  The
    # consolidated input file carries every sport, so filter to this
    # league's feed label before matching.  Teams are resolved from the
    # feed's external team IDs (immune to name drift, can't be guessed)
    # via the "crypto_id" submap; the match-key date is derived the same way the
    # other exchanges derive it — ET date from the UTC timestamp.  An
    # away/home flip recovers like PX/Kalshi: it only re-attaches the
    # game to the correct schedule entry.  It does NOT decide which team
    # a bet is on — build_rows resolves the side from the selection's own
    # participant (identity-based), so a flipped orientation (real for
    # neutral-site soccer) doesn't cross-wire teams.  Unmatched games are
    # skipped here; matched games build rows below.
    crypto_matched = 0
    crypto_flip = 0
    crypto_no_fixture = 0
    crypto_other_date = 0
    crypto_superseded = 0
    crypto_unmapped_game_lines: list[str] = []
    crypto_name_mismatch: list[str] = []
    crypto_catalogue: dict[str, crypto_optic.CatalogueEntry] = {}
    if league.CRYPTO is not None:
        crypto_line_src = (
            [ln for lg in (league.CRYPTO.league, *league.CRYPTO.also_leagues)
             for ln in snapshot.crypto_lines(lg)] if snapshot else None
        )
        crypto_catalogue = crypto_optic.load_catalogue_index(
            crypto_line_src
            if crypto_line_src is not None
            else data_dir / "crypto_com_markets.jsonl"
        )
        # Group by crypto EXTERNAL_GAME_ID so same-day doubleheaders
        # (two EXTERNAL_GAME_IDs, same teams+date) stay separate until
        # each is time-aligned onto its Optic fixture.
        crypto_by_egid: dict[str, list[crypto_com.Selection]] = (
            defaultdict(list))
        crypto_lines = crypto_line_src
        for line in iter_file_or_snapshot(
            data_dir / "crypto_com_markets.jsonl", crypto_lines,
            missing_label="crypto_com_markets.jsonl",
        ):
            # The file is the full unfiltered catalogue; parse_selection
            # returns None for anything that isn't a mappable game line.
            sel = crypto_com.parse_selection(line)
            if sel is None or sel.league not in (
                    league.CRYPTO.league, *league.CRYPTO.also_leagues):
                continue
            crypto_by_egid[sel.external_game_id].append(sel)

        pinned_crypto = pin_crypto_ids_from_selections(
            crypto_by_egid,
            index,
            crypto_team_aliases,
            player=person_league(config_slug(league)),
        )
        if pinned_crypto:
            print(
                f"  crypto [{league.league}]: in-memory "
                f"{pinned_crypto} crypto_id pin(s) from catalogue names",
                file=sys.stderr,
            )

        for egid, sels in crypto_by_egid.items():
            # Resolve the group's schedule fields from the freshest
            # listing (max security_id = latest issuance), not scan
            # order.  After a reschedule the catalogue keeps stale
            # vintages whose EVENT_DATE is the *old* start time; on
            # the PIT@CLE 2026-07-18 doubleheader, sels[0] carried
            # the pre-reschedule 20:10 and attached Game 2 (23:10)
            # to Game 1's 17:10 fixture.
            first = max(sels, key=lambda s: s.security_id)
            c_home = resolve_team(first.external_home_id, crypto_team_aliases)
            c_away = resolve_team(first.external_away_id, crypto_team_aliases)
            c_date = to_date_str(to_et_str(first.start_date))
            matched = _crypto_schedule_entries(
                index, c_home, c_away, first.start_date,
            )
            if matched is None and league.CRYPTO.sport_grouping == "TENNIS":
                matched = name_window_entries(
                    index, first.home_participant, first.away_participant,
                    first.start_date,
                )
            if matched is None:
                if c_date not in fixture_dates:
                    # Other-date selections are processed from their own
                    # date's data dir — expected, not an error.
                    crypto_other_date += 1
                else:
                    crypto_no_fixture += 1
                    print(
                        f"  crypto [{league.league}]: no schedule game "
                        f"for {c_date} {c_away}@{c_home} "
                        f"(external_game_id={egid})",
                        file=sys.stderr)
                continue
            candidates, flipped = matched
            entry = _pick_entry_by_time(candidates, first.start_date)
            if flipped:
                crypto_flip += 1
                print(
                    f"  crypto [{league.league}]: away/home flip "
                    f"— crypto has {c_away}@{c_home}, schedule "
                    f"has {entry.fixture.home}@{entry.fixture.away} "
                    f"(external_game_id={egid} → {entry.fixture.game_id})",
                    file=sys.stderr)
            entry.crypto_selections.extend(sels)
            crypto_matched += 1

        _report_crypto_match_stats(
            league.league,
            fixture_dates,
            matched=crypto_matched,
            flipped=crypto_flip,
            no_fixture=crypto_no_fixture,
            other_date=crypto_other_date,
        )

    # === Build canonical rows: PX first, then merge Kalshi, then Optic ===
    entries = sorted(
        (e for es in index.values() for e in es),
        key=lambda e: e.fixture.start_et,
    )

    all_rows: list[CanonicalRow] = []
    row_index: dict[tuple, CanonicalRow] = {}
    alt_crypto: dict[tuple[tuple, str], CanonicalRow] = {}
    all_odd_lookup: dict[str, optic.Odd] = {}
    all_game_ref_lookup: dict[str, optic.GameRef] = {}
    # optic odd id → fixture team_map for post-merge side checks.
    optic_team_maps: dict[str, dict[str, str]] = {}

    for e in entries:
        # Optic-live fixtures still emit so first-seen in-play listings
        # can land. load_mappings is insert-only for Optic is_live
        # game_ids (not start_date). Skip PX validation on Optic live
        # (collapsed board fails pre-game invariants); emit PX only
        # when markets actually landed.
        row_begin = len(all_rows)
        home = e.fixture.home
        away = e.fixture.away
        start_date = e.fixture.start_date
        et_date = to_date_str(e.fixture.start_et)

        # PX rows
        if e.px_event is not None and e.px_event.markets:
            label = f"{et_date} {away}@{home}"
            if not e.fixture.is_live:
                grouped = px.group_markets(e.px_event.markets)
                px.validate_markets(grouped, home, away, label=label)

            comp_map = px.build_comp_map(e.px_event.raw, px_team_aliases)
            px_rows = px.build_rows(
                start_date=start_date, home=home, away=away,
                markets=e.px_event.markets,
                comp_map=comp_map,
                player_aliases=px_player_aliases,
                league=league.league,
            )
            for r in px_rows:
                all_rows.append(r)
                row_index[row_key(r)] = r

        # Kalshi rows — merge onto existing PX rows or append new.
        # Gated per-league (league.KALSHI); leagues with no Kalshi
        # coverage never populate e.kalshi_markets (see the guarded
        # parsing section above), so this is skipped entirely rather
        # than calling build_rows with markets=[].
        if kalshi_cfg is not None:
            kalshi_rows = kalshi.build_rows(
                start_date=start_date, home=home, away=away,
                markets=e.kalshi_markets,
                cfg=kalshi_cfg,
                league=league.league,
                optic_player_names=_optic_player_names(e.fixture),
            )
            for kr in kalshi_rows:
                existing = row_index.get(row_key(kr))
                if existing is not None:
                    if keeps_existing(existing, kr):
                        continue
                    existing.kalshi_ticker = kr.kalshi_ticker
                    existing.kalshi_scope = kr.kalshi_scope
                    existing.kalshi_title = kr.kalshi_title
                    existing.kalshi_yes_sub_title = kr.kalshi_yes_sub_title
                    existing.kalshi_side = kr.kalshi_side
                else:
                    all_rows.append(kr)
                    row_index[row_key(kr)] = kr

        # Optic rows — merge onto existing rows or append new
        optic_rows, game_odd_lookup, game_ref_lookup = optic.build_rows(
            start_date=start_date, home=home, away=away,
            fixture=e.fixture,
            cfg=league.OPTIC,
            league=league.league,
        )
        all_odd_lookup.update(game_odd_lookup)
        all_game_ref_lookup.update(game_ref_lookup)
        for oid in game_odd_lookup:
            optic_team_maps[oid] = e.fixture.team_map
        for orow in optic_rows:
            existing = row_index.get(row_key(orow))
            if existing is not None:
                existing.optic_id = orow.optic_id
            else:
                all_rows.append(orow)
                row_index[row_key(orow)] = orow

        # Optic crypto.com source_ids → FIX Symbol (primary stamp when
        # market_id decodes uniquely against the catalogue).
        if league.CRYPTO is not None and crypto_catalogue:
            stamped_rows = [
                row_index.get(row_key(orow), orow)
                for orow in optic_rows
            ]
            crypto_optic.stamp_from_optic_odds(
                stamped_rows, game_odd_lookup, crypto_catalogue,
                league=league.league,
            )
            for row in stamped_rows:
                if row.crypto_symbol is None:
                    continue
                row.optic_fixture_id = e.fixture.fixture_id
                row.optic_game_id = e.fixture.game_id
                alt_crypto[(row_key(row), row.crypto_symbol)] = row

        # crypto.com FIX semantic rows — fill Optic gaps / crypto-only
        # markets. Superseded vintages are dropped first.
        if league.CRYPTO is not None and e.crypto_selections:
            crypto_sels = crypto_com.dedupe_superseded(e.crypto_selections)
            crypto_superseded += len(e.crypto_selections) - len(crypto_sels)
            crypto_rows = crypto_com.build_rows(
                start_date=start_date, home=home, away=away,
                selections=crypto_sels,
                cfg=league.CRYPTO,
                aliases=crypto_team_aliases,
                league=league.league,
                player_aliases=crypto_player_aliases,
                crypto_name_aliases=crypto_name_player_aliases,
                entity_names=crypto_entity_names,
                fixture_names={
                    e.fixture.home: e.fixture.home_name,
                    e.fixture.away: e.fixture.away_name,
                },
                skipped_unmapped_game_lines=crypto_unmapped_game_lines,
                skipped_name_mismatch=crypto_name_mismatch,
            )
            for cr in crypto_rows:
                # Stamp the matched Optic fixture ids so crypto-only rows
                # (no Optic odd) still load the real fixture_id/game_id.
                cr.optic_fixture_id = e.fixture.fixture_id
                cr.optic_game_id = e.fixture.game_id
                entry = crypto_catalogue.get(cr.crypto_symbol or "")
                if entry is not None:
                    cr.crypto_source_ts = crypto_optic.stamp_ts_from_catalogue(
                        entry.publish_time,
                    )
                attach_crypto_row(row_index, alt_crypto, all_rows, cr)

        for r in all_rows[row_begin:]:
            r.optic_is_live = e.fixture.is_live

    if crypto_superseded:
        print(
            f"  crypto [{league.league}]: {crypto_superseded} superseded "
            f"contract vintages dropped (re-issued; kept latest "
            f"security_id per question)",
            file=sys.stderr)
    if crypto_unmapped_game_lines:
        distinct = sorted(set(crypto_unmapped_game_lines))
        print(
            f"  crypto [{league.league}]: {len(crypto_unmapped_game_lines)} "
            f"game-line selection(s) skipped — unmapped contract_type(s): "
            f"{', '.join(distinct)} (gap-check will surface)",
            file=sys.stderr)
    if crypto_name_mismatch:
        print(
            f"  crypto [{league.league}]: {len(crypto_name_mismatch)} "
            f"selection(s) skipped — crossed crypto_id vs catalogue name",
            file=sys.stderr,
        )

    _check_poly_passthrough_identity(
        league, entries, row_index, all_odd_lookup, player_types,
        player_alias_data, data_dir, snapshot,
    )

    # === Polymarket: parse the bridge feed, match by name, stamp onto optic ===
    # Gated per-league (league.POLYMARKET). Poly rows merge onto existing optic
    # rows only (attach_polymarket_row) — a market optic didn't price is dropped.
    if league.POLYMARKET is not None:
        pcfg = league.POLYMARKET
        fixtures = [e.fixture for e in entries]
        optic_poly_index = _build_optic_poly_index(row_index, all_odd_lookup)
        pm_stamped = pm_dropped_no_optic = 0
        pm_optic_agree = pm_optic_conflict = 0
        if pcfg.slug_prefix:
            # Read the bridge feed, keep this league's slugs, then resolve fixtures
            # in two phases (game markets by name → player props by slug-team key).
            poly_markets: list[polymarket.PolyMarket] = []
            poly_lines = (
                snapshot.polymarket_lines_for_prefix(pcfg.slug_prefix)
                if snapshot else None
            )
            for line in iter_file_or_snapshot(
                data_dir / "polymarket_markets.jsonl", poly_lines,
                missing_label="polymarket_markets.jsonl",
            ):
                market = polymarket.parse_market(line)
                if market is None:
                    continue
                # legacy: ticker parse — replace with the typed venue field, do not extend
                if not market.slug.startswith(pcfg.slug_prefix + "-"):
                    continue
                poly_markets.append(market)
            # team_alias_scope: makes pcfg.team_name_aliases visible to every
            # _name_match call in this league's pass, including the ones build_rows
            # (frozen) makes directly — see the alias-overlay comment on
            # PolymarketConfig.team_name_aliases in exchanges/polymarket.py.
            with polymarket.team_alias_scope(pcfg.team_name_aliases):
                resolved, pm_stats = _resolve_poly_markets(poly_markets, fixtures, pcfg)
                matcher_poly_index: dict[str, tuple] = {}
                poly_stamp_batches: list[tuple] = []
                for market, parsed, fx in resolved:
                    rows = polymarket.build_rows(
                        market, parsed, home=fx.home, away=fx.away,
                        home_name=fx.home_name, away_name=fx.away_name,
                        start_date=fx.start_date, cfg=pcfg, league=league.league)
                    poly_stamp_batches.append((market, parsed, fx, rows))
                    for pr in rows:
                        clob = pr.polymarket_clob_token_id
                        if clob:
                            matcher_poly_index[str(clob)] = row_key(pr)
                if cc_ledger is not None:
                    cc_stats = CrosscheckStats()
                    reconcile_tokens(
                        league=league.league,
                        sportsbook=POLY_BOOK,
                        matcher_index=matcher_poly_index,
                        optic_index=optic_poly_index,
                        odd_lookup=all_odd_lookup,
                        ledger=cc_ledger,
                        stats=cc_stats,
                    )
                    pm_optic_conflict = cc_stats.disagree
                    optic_poly_index = _build_optic_poly_index(
                        row_index, all_odd_lookup,
                    )
                for _market, _parsed, _fx, rows in poly_stamp_batches:
                    for pr in rows:
                        clob = pr.polymarket_clob_token_id
                        optic_key = optic_poly_index.get(clob) if clob else None
                        if optic_key is not None:
                            if optic_key == row_key(pr):
                                pm_optic_agree += 1
                            elif cc_ledger is None:
                                pm_optic_conflict += 1
                                print(
                                    f"  polymarket [{league.league}] guard#4 CONFLICT: "
                                    f"clob {clob} parsed as {row_key(pr)} but optic "
                                    f"maps it to {optic_key} — dropping (not stamping)",
                                    file=sys.stderr,
                                )
                            continue
                        if attach_polymarket_row(row_index, pr) == "stamped":
                            pm_stamped += 1
                        else:
                            pm_dropped_no_optic += 1
            print(
                f"  polymarket [{league.league}]: {pm_stamped} stamped, "
                f"{pm_dropped_no_optic} dropped (optic didn't price), "
                f"{pm_stats['no_fixture']} no fixture, {pm_stats['unparsed']} non-game-line, "
                f"{pm_optic_agree} agree, {pm_optic_conflict} conflict-dropped",
                file=sys.stderr)

    usa_dropped = _run_polymarket_usa_pass(
        league, entries, row_index, all_odd_lookup, team_alias_data,
        kalshi_team_aliases, data_dir, snapshot, cc_ledger,
    )
    _log_usa_complements(
        league.league, stamp_usa_complements(row_index, all_odd_lookup))
    _log_usa_double_chance(league.league, stamp_usa_double_chance(
        row_index, all_odd_lookup, soccer=config_sport(league) is Sport.SOCCER))
    usa_no_goal, no_goal_stats = usa_no_goal_satellites(
        row_index, usa_dropped, soccer=config_sport(league) is Sport.SOCCER,
        odd_lookup=all_odd_lookup)
    all_rows.extend(usa_no_goal)
    if any(no_goal_stats.values()):
        print(
            f"  polymarket_usa [{league.league}] no team scores: YES → under 0.5 "
            f"{no_goal_stats['stamped']} stamped, {no_goal_stats['no_optic']} no optic row; "
            f"NO → over 0.5 {no_goal_stats['no_stamped']} stamped, "
            f"{no_goal_stats['no_no_optic']} no optic row",
            file=sys.stderr,
        )

    # === Novig: parse the market feed, join by Optic id, stamp onto optic ===
    # Gated per-league (league.NOVIG). Unlike every other exchange pass this
    # one does no name matching: Novig returns Optic's own fixture / team /
    # player ids, so an unresolvable id is a drop, never a guess.
    if league.NOVIG is not None:
        ncfg = league.NOVIG
        nv_league = novig.novig_league_key(ncfg.league)
        optic_novig_index = _build_optic_novig_index(row_index, all_odd_lookup)
        # Optic fixture_id -> the schedule entry we built for it.
        entry_by_fixture = {e.fixture.fixture_id: e for e in entries}
        # Optic player_id -> the CANONICAL entity, so a Novig player prop's
        # entity is an id lookup rather than a name normalization that could
        # drift from Optic's own spelling.
        #
        # This must be normalize_player_name(odd.selection) — the exact
        # expression optic.build_rows uses for a Scope.PLAYER entity — NOT
        # Optic's own `normalized_selection` field, which keeps generational
        # suffixes and periods that the canonical form strips
        # ("bobby_witt_jr_" vs "bobby_witt", "t_j_rumfield" vs "tj_rumfield").
        # Using the raw field keyed every player prop one character off its
        # optic twin, which the source_ids cross-check below caught as a
        # CONFLICT on every Jr/II/period player.
        player_names: dict[str, str] = {}
        for entry in entries:
            for odd in entry.fixture.odds:
                if odd.player_id and odd.selection:
                    player_names[odd.player_id] = normalize_player_name(
                        odd.selection)

        # Novig event_id -> Optic fixture_id, from the events snapshot.
        event_fixture: dict[str, str] = {}
        nv_ev_lines = (
            snapshot.novig_event_lines(ncfg.league) if snapshot else None
        )
        nv_mk_lines = (
            snapshot.novig_market_lines(ncfg.league) if snapshot else None
        )
        for line in iter_file_or_snapshot(
            data_dir / "novig_events.jsonl", nv_ev_lines,
            missing_label="novig_events.jsonl",
        ):
            event = novig.parse_event(line)
            if event is None or not event.opticOddsId:
                continue
            if novig.novig_league_key(event.league) != nv_league:
                continue
            event_fixture[event.id] = event.opticOddsId

        nv_stamped = nv_dropped_no_optic = nv_no_fixture = 0
        nv_unmapped_rows = nv_agree = nv_conflict = 0
        nv_unknown_types: set[str] = set()
        matcher_novig_index: dict[str, tuple] = {}
        novig_stamp_batches: list[list[CanonicalRow]] = []
        for line in iter_file_or_snapshot(
            data_dir / "novig_markets.jsonl", nv_mk_lines,
            missing_label="novig_markets.jsonl",
        ):
            market = novig.parse_market(line)
            if market is None or novig.novig_league_key(market.league) != nv_league:
                continue
            mt = ncfg.market_types.get(market.type)
            if mt is None:
                if market.type not in ncfg.ignored_types:
                    nv_unknown_types.add(market.type)
                continue
            fixture_id = event_fixture.get(market.eventId)
            entry = entry_by_fixture.get(fixture_id) if fixture_id else None
            if entry is None:
                nv_no_fixture += 1
                continue
            fx = entry.fixture
            rows = novig.build_rows(
                market, mt, home=fx.home, away=fx.away,
                start_date=fx.start_date, league=league.league,
                team_map=fx.team_map, player_names=player_names)
            if not rows:
                nv_unmapped_rows += 1
                continue
            novig_stamp_batches.append(rows)
            for nr in rows:
                outcome_id = nr.novig_outcome_id
                if outcome_id:
                    matcher_novig_index[str(outcome_id)] = row_key(nr)
        if cc_ledger is not None:
            nv_cc = CrosscheckStats()
            reconcile_tokens(
                league=league.league,
                sportsbook=NOVIG_BOOK,
                matcher_index=matcher_novig_index,
                optic_index=optic_novig_index,
                odd_lookup=all_odd_lookup,
                ledger=cc_ledger,
                stats=nv_cc,
            )
            nv_conflict = nv_cc.disagree
            optic_novig_index = _build_optic_novig_index(
                row_index, all_odd_lookup,
            )
        for rows in novig_stamp_batches:
            for nr in rows:
                outcome_id = nr.novig_outcome_id
                optic_key = (optic_novig_index.get(outcome_id)
                             if outcome_id else None)
                if optic_key is not None:
                    if optic_key == row_key(nr):
                        nv_agree += 1
                    elif cc_ledger is None:
                        nv_conflict += 1
                        print(
                            f"  novig [{league.league}] CONFLICT: outcome "
                            f"{outcome_id} parsed as {row_key(nr)} but optic "
                            f"maps it to {optic_key} — dropping (not stamping)",
                            file=sys.stderr,
                        )
                    continue
                if attach_novig_row(row_index, nr, all_rows) == "stamped":
                    nv_stamped += 1
                else:
                    nv_dropped_no_optic += 1
        if nv_unknown_types:
            print(
                f"  novig [{league.league}]: unknown market type(s) "
                f"{', '.join(sorted(nv_unknown_types))} — add to "
                f"market_types or ignored_types",
                file=sys.stderr)
        print(
            f"  novig [{league.league}]: {nv_stamped} stamped, "
            f"{nv_dropped_no_optic} dropped (optic didn't price), "
            f"{nv_no_fixture} no fixture, {nv_unmapped_rows} unbuildable, "
            f"{nv_agree} agree, {nv_conflict} conflict-dropped",
            file=sys.stderr)

    # === DKEX: typed venue catalogue, name-match, stamp onto optic ===
    # Gated per-league (league.DKEX).  DKEX publishes no Optic ids, but its
    # REST catalogue types every market (statAchievement, timePeriod,
    # participant, strikePrice, competitionId, home/away roles), so this
    # pass matches the fixture on start time + the two role-tagged team
    # names, and resolves teams by participant id and players by name.
    # The ticker is never parsed.  Anything that does not resolve is
    # dropped, never guessed.
    if league.DKEX is not None:
        _run_dkex_pass(league, entries, row_index, all_rows, data_dir)

    # === Underdog UDX: typed Optic ids + venue sentence, stamp onto optic ===
    # Market and period come from the venue's Optic market id, league
    # membership from its Optic fixture id, teams / YES side / line / player
    # from the contract sentence.  The ticker is carried as the RFQ key only.
    if league.UNDERDOG is not None:
        _run_underdog_pass(league, entries, row_index, all_rows, data_dir)

    # === STX (Ontario exchange): typed catalogue, Optic fixture join, stamp onto optic ===
    # Runs only where fetch.stx wrote stx_markets.jsonl and the league is an STX competition's run-set
    # league (stx_leagues). A failure here must not stop the league's other books: the tick is shared.
    try:
        stx_attach.run_league(str(league.league), entries, row_index, all_rows, data_dir, key_of=row_key)
    except Exception as exc:  # noqa: BLE001 -- STX is additive; never freeze the other books' mapping
        print(f"  stx [{league.league}]: FAILED, rows skipped: {type(exc).__name__}: {exc}", file=sys.stderr)

    # === SX Bet: venue catalogue, Optic event link / kickoff + names ===
    # Before this pass SX rows were only Optic's passthrough (Optic carries
    # SX odds for ~41% of the live book).  Fixture by Optic's own SX event
    # link, else kickoff + both team names; every (hash, side) Optic also
    # maps is cross-checked and a disagreement is dropped.
    if league.SXBET is not None:
        _run_sxbet_pass(league, entries, row_index, data_dir, all_odd_lookup)

    player_orphan_table(all_rows, player_types, orphan_dist)
    row_orphan_summary(all_rows)

    stamp_insurance_rows(row_index, all_odd_lookup, all_game_ref_lookup)

    # === Verify against Optic (missing mapping > wrong mapping) ===
    # Side/line/crypto always; PX/Kalshi source_ids when KalshiConfig
    # is present (same gate as historical verify_source_ids).
    optic_verify.verify_against_optic(
        row_index, all_rows, all_odd_lookup,
        team_maps=optic_team_maps,
        crypto_catalogue=crypto_catalogue if league.CRYPTO is not None else None,
        kalshi_tickers=frozenset(kalshi_tickers) if kalshi_cfg is not None else None,
    )

    if league.RUNSHOP is not None:
        chain_path = data_dir / league.RUNSHOP.chain_filename
        fixtures = [e.fixture for e in entries]
        stamped = runshop.stamp_runshop_rows(
            all_rows,
            all_game_ref_lookup,
            fixtures,
            chain_path,
            league.RUNSHOP,
        )
        if stamped:
            print(f"  runshop [{league.league}]: stamped {stamped} rows",
                  file=sys.stderr)

    if league.HUDDLE is not None:
        fixtures = [e.fixture for e in entries]
        hd_stamped, hd_dropped = huddle.run_huddle_pass(
            data_dir=data_dir,
            cfg=league.HUDDLE,
            league=str(league.league),
            fixtures=fixtures,
            row_index=row_index,
        )
        print(
            f"  huddle [{league.league}]: {hd_stamped} stamped, "
            f"{hd_dropped} dropped (optic didn't price)",
            file=sys.stderr,
        )

    # Kalshi 2-way moneyline No → the opponent's Optic odd.  Runs last so the
    # satellites are copied from fully-stamped rows and no later stamper can
    # re-add a book the satellite must not carry.  all_rows only: complements
    # share the parent's row_key, and verify_source_ids (which walks
    # row_index) would strip a Kalshi "no" off an odd Optic marks "yes".
    kalshi_ml_complements = attach_kalshi_moneyline_complements(
        row_index, league=league.league, sport=config_sport(league))
    if kalshi_ml_complements:
        all_rows.extend(kalshi_ml_complements)
        print(
            f"  kalshi [{league.league}]: {len(kalshi_ml_complements)} "
            f"moneyline No complement(s)",
            file=sys.stderr,
        )
    # Soccer 3-way GAME / 1H No → the Optic double chance excluding that outcome.
    kalshi_dc_complements = attach_kalshi_double_chance_complements(row_index)
    if kalshi_dc_complements:
        all_rows.extend(kalshi_dc_complements)
        print(
            f"  kalshi [{league.league}]: {len(kalshi_dc_complements)} "
            f"double chance No complement(s)",
            file=sys.stderr,
        )

    sort_key = _make_sort_key(market_type_order, spread_types)
    _apply_coarse_provenance(all_rows)
    if snap is not None:
        from mappers.provenance_bq import apply_bq_provenance

        apply_bq_provenance(
            all_rows,
            league_slug=config_slug(league),
            sport=config_sport(league),
            snap=snap,
        )
    all_rows.sort(key=sort_key)

    return PipelineResult(
        all_rows, all_odd_lookup, all_game_ref_lookup, cc_ledger,
    )
