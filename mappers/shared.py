"""Shared utilities for market mappers."""

import os
import sys
import tomllib
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

from pydantic import BaseModel, model_validator

from mappers.anytime_scorer import fold_anytime_goalscorer

ET = ZoneInfo("America/New_York")

# Default OpticConfig.horizon_hours. Widened to 168h (2026-07) so
# Polymarket legs for weekly slates (WNBA/MLS/MLB/tennis) still find
# an Optic fixture in the fetch window; fetch and diagnostics both
# read this same value. Changing it only affects diagnostics on
# historical snapshots, not mapping output.
#
# Overridable via the FIXTURE_HORIZON_HOURS env var. This is the DEFAULT
# only — a league whose OpticConfig sets a wider horizon_hours (europa
# league/conference at 60d) keeps it, which is why raising the default is
# the right lever and `fetch.optic --horizon-hours` is not: that flag is
# applied uniformly and would NARROW those leagues.
FIXTURE_HORIZON_HOURS = float(os.environ.get("FIXTURE_HORIZON_HOURS") or 168)

# Canonical side value for the tie outcome in 3-way markets.
# Leading underscore prevents collision with any team abbreviation.
TIE_SIDE = "_TIE"


def double_chance_side(covered: set[str], home: str, away: str) -> str:
    """Canonical DOUBLE_CHANCE side: its two outcomes, home/away/TIE order.

    "LIV/_TIE" is "Liverpool or draw", "LIV/CHE" is "either team wins".
    """
    order = (home, away, TIE_SIDE)
    if len(covered) != 2 or not covered <= set(order):
        raise ValueError(
            f"double chance covers two of {order}, got {sorted(covered)}")
    return "/".join(o for o in order if o in covered)


def correct_score_line(winner_goals: int, loser_goals: int) -> float:
    """Numeric CanonicalRow.line encoding for a CORRECT_SCORE scoreline.

    CanonicalRow.line is typed float (no string field carries a "W:L"-style
    scoreline), so the winner-anchored (winner_goals, loser_goals) pair --
    the same pair both optic.build_rows and polymarket.build_rows compute
    for their CORRECT_SCORE/EXACT_SCORE row -- is packed as
    winner_goals + loser_goals/100. loser_goals is always a single realistic
    soccer goal count (<100), so this is a lossless, order-preserving
    encoding: 2 goals to 1 -> 2.01, 10 goals to 2 -> 10.02, a 1-1 draw ->
    1.01. Shared here (not duplicated per exchange module) so both
    CORRECT_SCORE branches compute the identical float for the same real
    scoreline -- see wave-rescue-probe-findings.md section B.1 and
    .superpowers/sdd/task-r4-report.md for the join-key rationale.
    """
    return winner_goals + loser_goals / 100.0


def margin_band_key(low: int, high: int | None) -> str:
    """WINNING_MARGIN grouping_key for a band: ``11_to_20``, ``21_or_more`` (open top).

    Optic ("11-20", "21+") and the venues must compute the same key, the
    format Kalshi's own "Winning Margin" buckets already use.
    """
    return f"{low}_or_more" if high is None else f"{low}_to_{high}"


class MatchKey(NamedTuple):
    game_date: str  # Eastern date, YYYY-MM-DD
    home: str
    away: str


# === Team alias types ===
#
# Most exchange abbreviations map 1:1 to a canonical (Optic) abbreviation.
# A few collide: PX uses "COL" for both Columbia and Colorado.
# CollisionEntry stores the name and competitor id needed to disambiguate.
#
# This is a lot of machinery for a rare edge case.  A simpler
# alternative would be a complete hardcoded dict of PX competitor
# ids → canonical abbreviations for NCAAB (~360 entries).  We chose
# the collision-aware approach because it's less verbose and preserves
# the "team abbreviation first" design the alias system was built on,
# but if the union types and disambiguation logic prove to be a
# maintenance burden, switching to a flat id-based lookup would be
# a reasonable simplification.

@dataclass(frozen=True)
class CollisionEntry:
    """One candidate for an ambiguous exchange abbreviation."""
    canonical: str  # Optic abbreviation (e.g. "COLO")
    id: int         # PX competitor id — consistency check
    name: str       # PX display name (e.g. "Colorado Buffaloes")


AliasValue = str | list[CollisionEntry]
AliasMap = dict[str, AliasValue]


class AliasData(NamedTuple):
    """Result of load_aliases: per-exchange lookup plus canonical set."""
    by_exchange: dict[str, AliasMap]
    canonicals: set[str]


def load_aliases(path: Path) -> AliasData:
    """Load aliases from TOML, inverted for runtime lookup.

    TOML format is canonical-name-first with per-exchange alias lists.
    Each alias is either a string (unambiguous) or a table with abbr,
    id, and name keys (collision requiring name-based disambiguation).

    Simple:
        [GSW]
        px = ["GS"]

    Identity (no exchange keys):
        [ATL]

    Collision:
        [COLO]
        px = [{abbr = "COL", id = 60000250, name = "Colorado Buffaloes"}]

    Returns AliasData with:
      - by_exchange: {"px": {"GS": "GSW", ...}, ...}
      - canonicals: {"GSW", "ATL", "COLO", ...} (all TOML section headers)

    Returns AliasData({}, set()) if the file doesn't exist.
    """
    if not path.exists():
        return AliasData({}, set())
    data = tomllib.load(path.open("rb"))
    result: dict[str, AliasMap] = {}
    canonicals: set[str] = set()
    # "crypto_id" maps crypto.com external team IDs → canonical abbrev.
    # ("crypto" was the earlier full-name key, retired in favour of the
    # ID — names get no resolve_team identity free-ride and can drift;
    # see docs/adding-crypto.md.  Kept valid so a stray entry warns
    # rather than crashes.)
    # "crypto_name" maps a crypto.com player's display name → canonical
    # entity.  It is the NAME-keyed fallback for player props sourced from
    # processed_upstream_us.crypto_underlying_securities, which (unlike the
    # raw FIX feed) carries no PLAYER_ID, so the id-keyed "crypto_id" alias
    # can't apply.  Used only when player_id is absent/unmatched.
    # "optic_id" pins Optic competitor id → canonical (tennis only).
    _valid_keys = {"px", "kalshi", "crypto", "crypto_id", "crypto_name"}
    _meta_keys = {"optic_id", "name"}
    for canonical, exchanges in data.items():
        canonicals.add(canonical)
        bad_keys = set(exchanges) - _valid_keys - _meta_keys
        if bad_keys:
            raise ValueError(
                f"{path.name}: [{canonical}] has unknown key(s): "
                f"{', '.join(sorted(bad_keys))}")
        for exchange, aliases in exchanges.items():
            if exchange in _meta_keys:
                continue
            ex_map = result.setdefault(exchange, {})
            for alias in aliases:
                if isinstance(alias, str):
                    ex_map[alias] = canonical
                elif isinstance(alias, dict):
                    abbr = alias["abbr"]
                    entry = CollisionEntry(
                        canonical=canonical,
                        id=alias["id"],
                        name=alias["name"],
                    )
                    existing = ex_map.get(abbr)
                    if existing is None:
                        ex_map[abbr] = [entry]
                    elif isinstance(existing, list):
                        existing.append(entry)
                    else:
                        raise ValueError(
                            f"Alias {abbr!r} has both simple and "
                            f"collision entries for exchange {exchange!r}")
                else:
                    raise ValueError(
                        f"Unexpected alias type {type(alias)} "
                        f"in {canonical}.{exchange}")
    return AliasData(result, canonicals)


def load_alias_multimap(path: Path, exchange: str) -> dict[str, list[str]]:
    """Every canonical claiming each simple alias code, in TOML order.

    load_aliases collapses duplicate simple aliases last-wins, losing
    claimants when an exchange reuses codes across entities (Kalshi
    tennis: "SHE" is Shelton in one event, Shevchenko in another); the
    pipeline retries fixture lookups against every claimant.  Collision
    entries (dict form) are skipped — resolve_team already handles them.
    """
    if not path.exists():
        return {}
    multimap: dict[str, list[str]] = {}
    for canonical, section in tomllib.load(path.open("rb")).items():
        for alias in section.get(exchange, []):
            if (isinstance(alias, str)
                    and canonical not in multimap.setdefault(alias, [])):
                multimap[alias].append(canonical)
    return multimap


def load_optic_abbr_overrides(path: Path) -> dict[str, str]:
    """Build {optic_competitor_id: canonical_code} from team_aliases.toml."""
    if not path.exists():
        return {}
    data = tomllib.load(path.open("rb"))
    overrides: dict[str, str] = {}
    for code, section in data.items():
        optic_id = section.get("optic_id")
        if optic_id:
            overrides[str(optic_id)] = code
    return overrides


def known_alias_codes(
    canonicals: set[str],
    abbr_overrides: dict[str, str],
) -> set[str]:
    """Canonicals that count as present for the Optic completeness check.

    Unions disk-loaded canonicals with in-memory optic_id → code pins
    from tennis/UFC bootstrap. A concurrent deploy can wipe uncommitted
    bootstrap writes before load_aliases; load_fixtures still sees the
    in-memory pins, so completeness must too.
    """
    return set(canonicals) | set(abbr_overrides.values())


def resolve_team(
    abbr: str,
    aliases: Mapping[str, AliasValue],
    name: str | None = None,
    competitor_id: int | None = None,
) -> str:
    """Resolve an exchange abbreviation to canonical form.

    Fast path: alias is a simple string → return it.
    Collision path: alias maps to CollisionEntry list →
      match by name, assert competitor_id matches.
    Identity path: abbreviation not in aliases → return as-is.
    """
    value = aliases.get(abbr)
    if value is None:
        return abbr
    if isinstance(value, str):
        return value
    # Collision: list[CollisionEntry]
    if name is None:
        canonicals = [e.canonical for e in value]
        raise ValueError(
            f"Ambiguous abbreviation {abbr!r} → {canonicals}; "
            f"name required for disambiguation")
    for entry in value:
        if entry.name == name:
            if competitor_id is not None:
                assert entry.id == competitor_id, (
                    f"ID mismatch for {abbr!r}/{name!r}: "
                    f"TOML has {entry.id}, data has {competitor_id}")
            return entry.canonical
    canonicals = [(e.canonical, e.name) for e in value]
    raise ValueError(
        f"Abbreviation {abbr!r} with name {name!r} matches none of "
        f"{canonicals}")


def simple_alias_map(alias_map: AliasMap) -> dict[str, str]:
    """Extract simple string aliases, raising on collision entries.

    Player aliases are always simple string→string mappings.
    This validates that assumption and returns a plain dict that
    build_rows can accept.
    """
    result: dict[str, str] = {}
    for k, v in alias_map.items():
        if not isinstance(v, str):
            raise ValueError(
                f"Unexpected collision entry for alias {k!r}")
        result[k] = v
    return result


def normalize_line(v: float | None) -> float | None:
    """Snap a betting line to 2 decimal places for safe equality.

    Valid lines (integer, half-point, quarter-point) are exact in
    IEEE 754, so this is a no-op on clean data.  It guards against
    drift from floating point arithmetic (e.g. 220.50000000000003 → 220.5).
    """
    if v is None:
        return None
    return round(v, 2)


def lines(path: str | Path):
    """Yield stripped non-blank lines from a file."""
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield line


def lines_if_exists(path: str | Path):
    """Like lines(), but returns empty if the file is missing.

    Logs a warning so partial-fetch gaps are visible in the pipeline log.
    Used for exchange files (PX, Kalshi) that may be absent when their
    fetcher fails.  Optic is required and should use lines() directly.
    """
    path = Path(path)
    if not path.exists():
        print(f"  {path.name} not found — skipping", file=sys.stderr)
        return []
    return lines(path)


def to_date_str(dt: str) -> str:
    """Extract the YYYY-MM-DD date from a datetime string."""
    return dt[:10]


def time_of_day(dt: str) -> str:
    """Extract HH:MM from a datetime string, e.g. '2026-02-27T19:00:00' → '19:00'."""
    return dt[11:16]


def parse_iso_datetime(iso: str) -> datetime:
    """Parse an ISO timestamp that may use ``Z`` or an explicit offset."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def to_et_str(utc_iso: str) -> str:
    """Convert a UTC ISO timestamp to a naive ET datetime string.

    Respects DST: uses America/New_York so EST/EDT is chosen correctly.
    """
    dt = datetime.fromisoformat(utc_iso).astimezone(ET)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def is_et_midnight(utc_iso: str) -> bool:
    """True when the instant is 00:00 Eastern."""
    try:
        dt = parse_iso_datetime(utc_iso)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        return False
    et = dt.astimezone(ET)
    return et.hour == 0 and et.minute == 0 and et.second == 0


def is_crypto_date_placeholder(utc_iso: str) -> bool:
    """True for crypto date-only EVENT_DATE (ET midnight or fixed 04:00 UTC).

    Catalogue often carries ``…T04:00:00+00:00`` for a matchweek ticker even
    when Eastern midnight would be ``05:00 UTC`` in winter.
    """
    try:
        dt = parse_iso_datetime(utc_iso)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        return False
    utc = dt.astimezone(UTC)
    if utc.hour == 4 and utc.minute == 0 and utc.second == 0:
        return True
    return is_et_midnight(utc_iso)


# === Canonical output model ===

class CanonicalRow(BaseModel):
    """One side of one line in one market for one game.

    This is the atomic betting unit in our canonical domain:
    Game → Market → Line → Side.
    """
    league: str                     # e.g. "nba", "ncaab", "epl"
    start_date: str                 # UTC ISO timestamp, e.g. "2026-02-26T01:00:00Z"
    home: str                       # home team abbrev
    away: str                       # away team abbrev
    market_type: str                # MarketType.value
    entity: str | None = None       # team abbrev for TEAM-scoped; None for GAME-scoped
    line: float | None = None       # signed for spread; unsigned threshold for totals; None for moneyline
    side: str                       # team abbrev for moneyline/spread; "over"/"under" for totals
    grouping_key: str | None = None # pairs sides of a bet; None when redundant with (entity, line, side)
    px_event_id: int | None = None  # PX sport_event_id (parent event)
    px_line_id: str | None = None   # PX selection's globally unique line_id
    px_market_name: str | None = None  # PX market name (e.g. "IND: Team Total Points")
    px_selection_display_name: str | None = None  # PX selection display_name (e.g. "over 107.5")
    kalshi_ticker: str | None = None  # Kalshi market ticker
    kalshi_scope: str | None = None  # Kalshi's typed scope (e.g. "1st Half Spread")
    kalshi_title: str | None = None    # Kalshi market title (e.g. "Will the team total...")
    kalshi_yes_sub_title: str | None = None  # Kalshi yes outcome label (e.g. "Seattle")
    kalshi_side: str | None = None    # "yes" or "no" on the Kalshi contract
    optic_id: str | None = None       # Optic odd id
    crypto_security_id: str | None = None  # crypto.com FIX SecurityID (source-id stamp)
    crypto_symbol: str | None = None  # crypto.com FIX Symbol (e.g. "NX.F.OPT.FIFA-00002-260626-M.O.1.1")
    crypto_market_id: str | None = None  # crypto.com market id (Optic PM.NPO or FIX PREDICT_MARKET_ID)
    crypto_outcome_id: str | None = None  # crypto.com outcome id
    crypto_selection_name: str | None = None  # crypto.com selection label (e.g. "Cabo Verde to win")
    # Epoch seconds for Optic-vs-FIX crypto stamp latest-wins; not loaded to BQ.
    crypto_source_ts: float | None = None
    # Extra FIX symbol for this bet; load emits crypto.com only (not Optic books).
    crypto_satellite: bool = False
    # Opponent-ticker No on this team's 2-way ML; load emits Kalshi only.
    kalshi_complement: bool = False
    # Polymarket — novel rows matched by team name (no stable team IDs).
    # clob_token_id is the source-id stamp; position_id is provenance.
    # See docs/adding-polymarket.md.
    polymarket_clob_token_id: str | None = None  # source-id stamp (functional key)
    polymarket_condition_id: str | None = None   # underlying single condition_id (provenance)
    polymarket_position_id: str | None = None     # combo-leg NegRisk token id (provenance)
    polymarket_slug: str | None = None            # single-market slug (provenance)
    polymarket_question: str | None = None        # single-market question/title (provenance)
    polymarket_usa_market_id: str | None = None  # US ticker stamp (market_id)
    # "no" only where the row prices the venue's NO on that symbol and the
    # maker cannot infer it (soccer outcome No → double chance). Written as
    # source_ids.selection_id, the Kalshi (ticker, selection_id) convention.
    polymarket_usa_side: str | None = None
    # A US symbol priced off another bet's Optic odd (soccer "no team
    # scores" → total under 0.5); load emits Polymarket (USA) only.
    polymarket_usa_satellite: bool = False
    # Novig (NBX) — novel rows, but matched by ID rather than by name: the
    # Novig API returns Optic's own fixture / team / player ids, so there is
    # no alias map and no name normalization on this path.  outcome_id is the
    # source-id stamp (the clob_token_id / kalshi_ticker analog); event and
    # market ids are carried because Optic's own Novig source_ids use the
    # same {event_id, market_id, selection_id} triple, so a row we construct
    # and a row Optic passes through are indistinguishable downstream.
    # See docs/adding-novig.md.
    novig_outcome_id: str | None = None    # Novig outcome id — the source-id stamp
    novig_market_id: str | None = None     # Novig market id
    novig_event_id: str | None = None      # Novig event id
    novig_market_type: str | None = None   # raw Novig market type (e.g. "SPREAD")
    novig_description: str | None = None   # Novig market description (provenance)
    # DKEX (DraftKings Exchange) — novel rows matched by NAME, like
    # Polymarket: the venue publishes no Optic ids, no display names and
    # no team/player ids, so everything is recovered from the symbol
    # itself (mappers/exchanges/dkex.py).  The symbol is a Kalshi-shaped
    # binary market carrying BOTH canonical sides, so the source-id stamp
    # is the PAIR (symbol, side) — the symbol alone is not a functional
    # key.  See docs/adding-dkex.md.
    dkex_symbol: str | None = None       # DKEX market symbol — half the source-id stamp
    dkex_side: str | None = None         # "yes" / "no" on that symbol — the other half
    dkex_event_id: str | None = None     # DKEX fixture handle (provenance)
    dkex_market: str | None = None       # raw DKEX market token, e.g. "MOVY" (provenance)
    dkex_period: str | None = None       # raw DKEX period token, e.g. "FG" (provenance)
    # Second DKEX ticker for the same canonical bet; load emits DKEX only.
    # DKEX lists BOTH moneyline tickers for a game (one per team), and the
    # bare/"OU" player-prop tokens are two tickers for one contract, so a
    # single canonical row legitimately has more than one symbol.  The
    # responder looks a leg up BY TICKER, so dropping the loser would make
    # half the moneyline RFQ flow unquotable.
    dkex_satellite: bool = False
    # Underdog UDX. The ticker is the RFQ key. side is yes/no on that
    # binary contract. No Optic source_ids exist for this book.
    underdog_ticker: str | None = None
    underdog_side: str | None = None
    underdog_satellite: bool = False
    # STX (Ontario exchange). market_id is the RFQ leg key, side is yes/no on that binary
    # market. tie_pays_half: a level game settles the leg at half (the maker refuses it).
    stx_market_id: str | None = None
    stx_side: str | None = None
    stx_event_id: str | None = None
    stx_tie_pays_half: bool = False
    stx_satellite: bool = False
    # SX Bet -- novel rows matched off SX's own catalogue (fixture by
    # Optic's event link, else kickoff + both team names).  One marketHash
    # is one binary carrying both canonical sides, so the stamp is the PAIR
    # (hash, taker outcome 1|2); load writes Optic's own id shape from it
    # (``sxbet.selection_id``: the suffix is the MAKER's outcome).  See
    # docs/adding-sxbet.md.
    sx_market_hash: str | None = None    # lowercase marketHash -- half the stamp
    sx_outcome: int | None = None        # taker outcome 1 / 2 -- the other half
    sx_event_id: str | None = None       # sportXeventId (provenance)
    sx_type: int | None = None           # SX market type id (provenance)
    # Optic fixture-level ids carried on crypto rows.  The fixture is
    # always known (crypto selections are matched to an Optic schedule
    # entry) even when no Optic *odd* matched the selection, so crypto-
    # only rows can load the real Optic fixture_id/game_id instead of a
    # "crypto-only" placeholder.
    optic_fixture_id: str | None = None  # Optic fixture_id of the matched game
    optic_game_id: str | None = None     # Optic game_id of the matched game
    # Optic /fixtures/active is_live. Load uses this (not start_date) to
    # insert-only so a live board cannot update pre-match rows.
    optic_is_live: bool = False
    # Huddle is a pricing supplier (augments Optic), joined to Optic by
    # the shared Sportradar match id, so its rows are novel like
    # crypto's.  The functional key is the single immutable selectionId
    # (the source-id stamp); everything else is provenance carried for
    # the novelty reason — there is no Optic row to lean on.  See
    # docs/adding-huddle.md ("source-id stamp").
    huddle_selection_id: str | None = None    # Huddle selectionId — the source-id stamp (functional key)
    huddle_event_id: str | None = None        # Huddle eventId — key insurance + sr-join provenance
    huddle_market_id: str | None = None       # Huddle marketId (provenance)
    huddle_market_code: str | None = None     # e.g. "RESULT" (provenance)
    huddle_selection_code: str | None = None  # e.g. "HOME"/"DRAW" (provenance)
    huddle_betradar_extid: str | None = None  # Sportradar match id the row joined on (provenance)
    runshop_tx_odds_fixture_id: int | None = None  # tx live / betbuilder txOddsFixtureID
    runshop_market_id: int | None = None           # Runshop market id for this Optic leg
    # Mapping provenance (M1 market_mapping columns + audit)
    fixture_match_method: str | None = None
    market_match_method: str | None = None
    verify_tier: str | None = None
    mapping_audit_event_id: str | None = None
    market_rule_id: str | None = None
    entity_alias_ids: list[str] | None = None
    fixture_rule_id: str | None = None

    @model_validator(mode="after")
    def _fold_anytime_goalscorer(self) -> "CanonicalRow":
        """Soccer player_goals over 0.5 is the anytime goalscorer market."""
        folded = fold_anytime_goalscorer(
            self.league, self.market_type, self.line, self.side)
        if folded is not None:
            self.market_type, self.line, self.side = folded
        return self


# Generational suffixes stripped during player name normalization.
# Ordered longest-first so "III" is tried before "II".
_GENERATIONAL = ("Jr", "Sr", "III", "II", "IV")

# Latin base letters that NFD decomposition cannot fold to ASCII:
# unlike é→e+◌́, these carry no combining mark, so the Mn-strip in
# normalize_player_name passes them through ("Ødegaard" stayed
# "ødegaard" while crypto.com's ASCII "Odegaard" became "odegaard",
# and the entities silently failed to merge).  Hand-audited table,
# deliberately NOT a library transliterator (unidecode etc.), so
# every folded letter is one we chose and verified.  Adding a letter
# changes merge-key entities — check gold files and loaded
# market_mapping rows for the letter first (2026-06-11: all nine
# letters absent from prod-VM gold, 3.35M entity rows, and from BQ
# test+prod).
_BASE_LETTER_FOLD = str.maketrans({
    "ı": "i",              # Turkish dotless i (Yılmaz); İ decomposes, ı doesn't
    "ß": "ss",             # German sharp s (Groß)
    "ø": "o", "Ø": "O",    # Norwegian/Danish (Ødegaard, Sørloth)
    "ł": "l", "Ł": "L",    # Polish (Łukasz)
    "đ": "d", "Đ": "D",    # Croatian/Serbian (Đorđe)
    "æ": "ae", "Æ": "Ae",  # Norwegian/Danish/Icelandic (Sælebakke)
    "œ": "oe", "Œ": "Oe",  # French
    "ð": "d", "Ð": "D",    # Icelandic eth (Guðmundsson)
    "þ": "th", "Þ": "Th",  # Icelandic thorn (Þórður)
})


def normalize_player_name(name: str) -> str:
    """Normalize a player name for use as a merge-key entity.

    All sources (Optic, PX, Kalshi, crypto.com) run names through
    this single function so their entity values agree.

    Steps: NFD decompose → strip combining marks (diacritics) →
    fold NFD-immune base letters (ø → o, ß → ss) → strip periods →
    strip generational suffixes → lowercase → collapse whitespace →
    replace spaces with underscores.

    Hyphens and apostrophes are deliberately KEPT: every source
    spells them consistently for the players we map (de'aaron_fox,
    karl-anthony_towns live in gold and in loaded market_mapping
    rows), so stripping them would change persisted entities for no
    merge gain.  A source that drops them where another keeps them
    (crypto "N'Dicka" vs Optic "Ndicka") is an alias-map problem,
    not a normalization one.

    >>> normalize_player_name("Nikola Jokić")
    'nikola_jokic'
    >>> normalize_player_name("Wendell Carter Jr.")
    'wendell_carter'
    >>> normalize_player_name("P.J. Washington")
    'pj_washington'
    >>> normalize_player_name("Martin Ødegaard")
    'martin_odegaard'
    >>> normalize_player_name("Barış Alper Yılmaz")
    'baris_alper_yilmaz'
    >>> normalize_player_name("Pascal Groß")
    'pascal_gross'
    """
    # NFD decompose and strip combining marks (é → e, ć → c)
    decomposed = unicodedata.normalize("NFD", name)
    stripped = "".join(
        ch for ch in decomposed
        if unicodedata.category(ch) != "Mn"  # Mn = Mark, Nonspacing
    )

    # Fold base letters NFD can't decompose (ı, ß, ø, ł, đ, æ, œ, ð, þ)
    stripped = stripped.translate(_BASE_LETTER_FOLD)

    # Strip periods (handles "P.J." → "PJ", leftover "Jr." → "Jr")
    stripped = stripped.replace(".", "")

    # Strip generational suffixes
    for suffix in _GENERATIONAL:
        if stripped.rstrip().endswith(suffix):
            stripped = stripped.rstrip()[:len(stripped.rstrip()) - len(suffix)]
            break

    # Lowercase, collapse whitespace, replace spaces with underscores
    return "_".join(stripped.lower().split())


def opponent(team: str, home: str, away: str) -> str:
    """Return the other team in a game."""
    if team == home:
        return away
    if team == away:
        return home
    raise ValueError(
        f"Team {team!r} is neither home ({home!r}) nor away ({away!r})")
