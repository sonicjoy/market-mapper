# Multi-League Refactor Proposal

Companion to `multi-sport-roadmap.md` (the problem statement).
This document is the proposed solution shape, workshopped from
examining NBA, NCAAB, NHL, and soccer data.


## Directory layout

```
mappers/
  run.py                  # CLI entry point, league registry, dispatch
  pipeline.py             # generic merge loop (extracted from nba.py)
  shared.py               # MatchKey, CanonicalRow, Scope, Shape, etc.
  market_types.py          # Scope and Shape enums only

  exchanges/
    kalshi.py             # Market model, parse_market, _require_team,
                          #   _parse_team_line, build_rows — generic
                          #   mechanics, parameterized by league config
    px.py                 # Event/Market models, extract_market_lines,
                          #   resolve_side_label, build_rows — generic
                          #   mechanics, parameterized by league config
    optic.py              # Fixture/Odd models, load_fixtures, build_rows,
                          #   verify_source_ids — generic mechanics

  leagues/
    nba.py
    ncaab.py
    nhl.py                # (future)
    epl.py                # (future — one module per soccer league)
    bundesliga.py         # (future)
```


## Key design decisions

### Per-league MarketType enum

Each league module defines its own `MarketType` enum.  NBA has 23
types, NHL will have different ones (puck_line, player_goals,
player_saves, ...), soccer different again (both_teams_to_score,
clean_sheet, total_corners, ...).

The `Scope` enum (GAME, TEAM, PLAYER) is universal and stays in
`market_types.py`.

### Shape: structural dispatch for parsing and row building

Currently `kalshi.parse_event_ticker`, `kalshi.build_rows`,
`optic.build_rows`, and `px.build_rows` all dispatch on specific
MarketType values (if mt == MONEYLINE ... elif mt == POINT_SPREAD
...).  But the logic is really about *structural shape* — NBA's
POINT_SPREAD and NHL's PUCK_LINE are parsed identically (2 rows,
signed line, side=team).

Shape drives two things, not just one:

1. **Row building** — how many rows, what side labels, how to sign
   the line.  This is the obvious one.
2. **Kalshi suffix parsing** — the suffix pattern for a Kalshi
   market ticker is determined by (scope, shape):

   | (scope, shape)         | suffix pattern            | examples           |
   |------------------------|---------------------------|--------------------|
   | GAME, MONEYLINE        | {TEAM}                    | GAME               |
   | GAME, SPREAD           | {TEAM}{N}                 | SPREAD, 1HSPREAD   |
   | GAME, TOTAL            | {N}                       | TOTAL, 1HTOTAL     |
   | GAME, THREE_WAY        | {TEAM} or TIE             | 1HWINNER, 2HWINNER |
   | TEAM, TOTAL            | {TEAM}{N}                 | TEAMTOTAL          |
   | PLAYER, OVER_UNDER     | {TEAM}{PLAYER_ENC}-{N}    | PTS, AST, GOAL, …  |
   | PLAYER, YES_NO         | {TEAM}{PLAYER_ENC}        | 2D, 3D, FIRSTGOAL  |
   | GAME, YES_NO           | (no suffix)               | BTTS               |

   PLAYER_ENC = {INITIAL}{LASTNAME}{JERSEY}, e.g. ZWILLIAMSON1.
   The {TEAM} prefix in player suffixes is transparent to the
   parser — player names come from titles, lines from `rfind("-")`.

   FIRSTGOAL also has a NOGOAL suffix (no-goal-scored outcome).
   BTTS markets have no suffix (market ticker = event ticker).

   This means `parse_event_ticker` can dispatch on (scope, shape)
   instead of hardcoded ticker_type strings, making it generic
   across leagues.  The code must raise if a suffix does not match
   the expected pattern for its (scope, shape) — these patterns
   were verified across all data and any violation indicates a
   parsing bug or a new Kalshi encoding convention.

Each MarketType carries a `shape` attribute alongside `scope`.
Shape captures the structural form:

```python
# market_types.py

class Scope(Enum):
    GAME = "game"
    TEAM = "team"
    PLAYER = "player"

class Shape(Enum):
    MONEYLINE = "moneyline"      # side=team, no line
    SPREAD = "spread"            # side=team, signed line
    TOTAL = "total"              # side=over/under, unsigned line
    THREE_WAY = "three_way"      # side=team or _TIE, no line
    OVER_UNDER = "over_under"    # side=over/under, line
    YES_NO = "yes_no"            # side=yes/no, no line
```

Then each league's MarketType carries both:

```python
# leagues/nba.py

class MarketType(Enum):
    value: str
    scope: Scope
    shape: Shape

    def __new__(cls, value, scope, shape):
        obj = object.__new__(cls)
        obj._value_ = value
        obj.scope = scope
        obj.shape = shape
        return obj

    MONEYLINE          = ("moneyline",        Scope.GAME,   Shape.MONEYLINE)
    POINT_SPREAD       = ("point_spread",     Scope.GAME,   Shape.SPREAD)
    GAME_TOTAL         = ("game_total",       Scope.GAME,   Shape.TOTAL)
    TEAM_TOTAL         = ("team_total",       Scope.TEAM,   Shape.TOTAL)
    FIRST_HALF_TOTAL   = ("1h_total",         Scope.GAME,   Shape.TOTAL)
    PLAYER_POINTS      = ("player_points",    Scope.PLAYER, Shape.OVER_UNDER)
    PLAYER_DOUBLE_DOUBLE = ("player_dd",      Scope.PLAYER, Shape.YES_NO)
    # ...
```

```python
# leagues/nhl.py

class MarketType(Enum):
    # ...same __new__...
    MONEYLINE          = ("moneyline",        Scope.GAME,   Shape.MONEYLINE)
    PUCK_LINE          = ("puck_line",        Scope.GAME,   Shape.SPREAD)
    TOTAL_GOALS        = ("total_goals",      Scope.GAME,   Shape.TOTAL)
    PLAYER_GOALS       = ("player_goals",     Scope.PLAYER, Shape.OVER_UNDER)
    ANYTIME_GOAL_SCORER = ("anytime_gs",      Scope.PLAYER, Shape.YES_NO)
    # ...
```

Exchange `build_rows` dispatches on `(mt.scope, mt.shape)`:

```python
# exchanges/kalshi.py  build_rows (sketch)

if mt.shape == Shape.MONEYLINE:
    rows.append(CanonicalRow(..., side=team, kalshi_side="yes"))

elif mt.shape == Shape.SPREAD:
    rows.append(CanonicalRow(..., line=-line, side=team, kalshi_side="yes"))
    rows.append(CanonicalRow(..., line=+line, side=opp,  kalshi_side="no"))

elif mt.shape == Shape.TOTAL:
    entity = team if mt.scope == Scope.TEAM else None
    rows.append(CanonicalRow(..., entity=entity, side="over",  kalshi_side="yes"))
    rows.append(CanonicalRow(..., entity=entity, side="under", kalshi_side="no"))

elif mt.shape == Shape.THREE_WAY:
    side = team if team is not None else TIE_SIDE
    rows.append(CanonicalRow(..., side=side, kalshi_side="yes"))

elif mt.shape == Shape.OVER_UNDER:
    # Player stat with line (or game-level over/under with entity)
    entity = normalize_player_name(player) if mt.scope == Scope.PLAYER else ...
    rows.append(CanonicalRow(..., entity=entity, line=line, side="over",  kalshi_side="yes"))
    rows.append(CanonicalRow(..., entity=entity, line=line, side="under", kalshi_side="no"))

elif mt.shape == Shape.YES_NO:
    entity = normalize_player_name(player) if mt.scope == Scope.PLAYER else ...
    rows.append(CanonicalRow(..., entity=entity, side="yes", kalshi_side="yes"))
    rows.append(CanonicalRow(..., entity=entity, side="no",  kalshi_side="no"))
```

This is sport-agnostic.  Adding NHL's PUCK_LINE or soccer's
BOTH_TEAMS_TO_SCORE requires no changes to exchange build_rows —
only a new MarketType entry with the right Shape.


### League config flows via typed dataclasses

Each exchange module defines a frozen dataclass describing exactly
what it needs from a league.  The league module constructs one
instance per exchange.  The pipeline passes them through.

This gives single-arg simplicity (one `cfg` parameter) with full
type safety — autocomplete works, typos are caught at construction
time, and each exchange documents its own contract.

```python
# exchanges/kalshi.py
@dataclass(frozen=True)
class KalshiConfig:
    prefix: str
    game_ticker_re: re.Pattern
    table_types: dict[str, MarketType]
    ignored_ticker_types: frozenset[str]  # factories ship empty; tip overlay

# exchanges/px.py
@dataclass(frozen=True)
class PxConfig:
    sport: str
    tournament: str
    exact: dict[str, MarketType]
    suffix: list[tuple[str, MarketType]]

# exchanges/optic.py
@dataclass(frozen=True)
class OpticConfig:
    league_id: str
    table_types: dict[str, MarketType]
```

The league module builds all three:

```python
# leagues/nba.py

from mappers.exchanges.kalshi import KalshiConfig
from mappers.exchanges.px import PxConfig
from mappers.exchanges.optic import OpticConfig

class MarketType(Enum):
    # ... (as above, with scope and shape)

OUTPUT_ORDER: tuple[MarketType, ...] = (...)

KALSHI = KalshiConfig(
    prefix="KXNBA",
    game_ticker_re=re.compile(
        r"^KXNBA[A-Z0-9]*-(\d{2})([A-Z]{3})(\d{2})([A-Z]{3})([A-Z]{3})$"
    ),
    table_types={
        "GAME": MarketType.MONEYLINE,
        "SPREAD": MarketType.POINT_SPREAD,
        # ...
    },
    ignored_ticker_types=frozenset(),
)

PX = PxConfig(
    sport="Basketball",
    tournament="NBA",
    exact={
        "Moneyline": MarketType.MONEYLINE,
        "Spread": MarketType.POINT_SPREAD,
        "Total Points": MarketType.GAME_TOTAL,
        # ...
    },
    suffix=[
        (" Points", MarketType.PLAYER_POINTS),
        (": Team Total Points", MarketType.TEAM_TOTAL),
        # ...
    ],
)

OPTIC = OpticConfig(
    league_id="nba",
    table_types={
        "moneyline": MarketType.MONEYLINE,
        "point_spread": MarketType.POINT_SPREAD,
        "total_points": MarketType.GAME_TOTAL,
        # ...
    },
)
```

The pipeline wires them through:

```python
# pipeline.py
def run(league, data_dir, ...):
    kalshi_rows = kalshi.build_rows(markets, cfg=league.KALSHI)
    px_rows = px.build_rows(markets, cfg=league.PX)
    optic_rows = optic.build_rows(fixtures, cfg=league.OPTIC)
```


### League registry and tournament filtering

`run.py` maintains an explicit registry.  Adding a league means
writing `leagues/foo.py` and adding one entry:

```python
# run.py

from mappers.leagues import nba, ncaab

LEAGUES = {
    "nba": nba,
    "ncaab": ncaab,
    # "nhl": nhl,
    # "epl": epl,
}
```

CLI:

```
python -m mappers.run nba data/nba/2026-02-25/ --json
python -m mappers.run ncaab data/ncaab/2026-02-21/ --table
python -m mappers.run epl data/soccer/2026-02-21/ --json
```

Each league module declares its PX and Optic identifiers
(`PX_TOURNAMENT`, Optic `league.id` etc.).  The pipeline uses
these to filter the data files.  Multiple leagues can share a data
directory — soccer's `data/soccer/2026-02-21/` contains EPL,
Bundesliga, Serie A, etc., but `run epl` processes only EPL
fixtures and markets.

Filtering happens early: `parse_event` skips events whose
`tournament_name` doesn't match, `load_fixtures` skips fixtures
whose `league.id` doesn't match, Kalshi ticker parsing skips
tickers whose prefix doesn't match.  The rest of the pipeline
sees only the league's data.


### What stays in shared exchange modules

The exchange modules under `exchanges/` hold the truly generic
parsing mechanics — models, structural parsing, row building
dispatched by Shape.  They define their own config dataclass and
receive a league-provided instance of it.

**`exchanges/kalshi.py`:** KalshiConfig dataclass; Market model,
parse_market, ParsedTicker, _require_team, _parse_team_line,
_parse_int, _extract_player_name; parse_event_ticker (dispatches
on Shape for suffix parsing); build_rows (dispatches on Shape for
row construction).

**`exchanges/px.py`:** PxConfig dataclass; Event, Market,
Selection, Line, Enrichment models; parse_event (uses
cfg.sport, cfg.tournament for filtering); parse_market;
extract_market_lines; validation functions; classify_market (uses
cfg.exact, cfg.suffix for lookup); resolve_side_label; build_rows
(dispatches on Shape).

**`exchanges/optic.py`:** OpticConfig dataclass; Game, Fixture,
Odd models; load_fixtures (uses cfg.league_id for filtering);
build_rows (uses cfg.table_types for lookup, dispatches on Shape);
verify_source_ids.

Platform-specific encoding conventions stay in the exchange modules
(not league config):
- Kalshi's ±0.5 integer-to-half-point convention
- Optic's DD/TD encoding as over/under 0.5 → yes/no
- PX outcome_id meanings (4/5=team, 12/13=over-under, 1/2=yes-no)
- PX line sourcing (spreads: per-selection, totals: per-market-line)
- PX type cross-check (see below)

#### PX classify_market and the type cross-check

`classify_market` takes `cfg: PxConfig` and looks up the market
name in `cfg.exact` / `cfg.suffix`.  It returns whatever
MarketType value the league's dicts contain — it never inspects
the enum, so it works with any league's MarketType.

The current code also cross-checks PX's `type` field
(`"moneyline"`, `"spread"`, `"total"`) against the classified
MarketType via a per-type `_EXPECTED_TYPE` dict.  After the
refactor, this dict is replaced by a Shape-based mapping that
lives in px.py as a platform constant:

```python
# exchanges/px.py

_PX_TYPE_FOR_SHAPE: dict[Shape, str] = {
    Shape.MONEYLINE:   "moneyline",
    Shape.SPREAD:      "spread",
    Shape.TOTAL:       "total",
    Shape.THREE_WAY:   "moneyline",
    Shape.OVER_UNDER:  "total",
    Shape.YES_NO:      "moneyline",
}
```

PX uses three structural types; they map directly to Shape.
The cross-check becomes `_PX_TYPE_FOR_SHAPE[mt.shape]` — no
per-league config needed.  This validates that PX's structural
type agrees with the Shape we assigned, and works for all
leagues.


### Alias files: team and player

Team and player aliases map exchange-specific names to canonical
(Optic) names.  Today, team aliases are hardcoded in `shared.py`
(`PX_ALIASES`) and player aliases live in a CSV under
`data/nba/tables/`.  After the refactor, both use the same TOML
format, checked into version control under `config/`.

#### Directory structure

```
config/
  nba/
    team_aliases.toml
    player_aliases.toml
  ncaab/
    team_aliases.toml
    player_aliases.toml
  epl/
    team_aliases.toml
    player_aliases.toml
  bundesliga/
    ...
```

Keyed by league (not sport) — the subdirectory names must match
the keys in `run.py`'s `LEAGUES` registry.  This is enforced at
startup (see below).

#### TOML format

Canonical-name-first, with per-exchange alias lists.  Omission
means the exchange uses the canonical form as-is.

```toml
# config/nba/team_aliases.toml

[GSW]
px = ["GS"]

[NYK]
px = ["NY"]

[NOP]
px = ["NO"]

[PHX]
px = ["PHO"]

[SAS]
px = ["SA"]
```

```toml
# config/epl/team_aliases.toml

[MCI]
px = ["Man City", "Manchester City"]
kalshi = ["MANCITY"]

[ARS]
px = ["Arsenal FC"]
kalshi = ["ARSENAL"]

[MUN]
px = ["Man United", "Manchester United", "Man Utd"]
kalshi = ["MANUNITED"]
```

```toml
# config/nba/player_aliases.toml

[carlton_carrington]
px = ["bub_carrington"]
kalshi = ["bub_carrington"]

[nic_claxton]
px = ["nicolas_claxton"]

[ronald_holland]
px = ["ron_holland"]

[gregory_jackson]
px = ["gg_jackson"]
```

#### Loader

The loader inverts the TOML structure into the runtime form the
pipeline needs — `{exchange: {alias: canonical}}`:

```python
# shared.py

def load_aliases(path: Path) -> dict[str, dict[str, str]]:
    """Load aliases from TOML, inverted for runtime lookup.

    Returns {"px": {"GS": "GSW", ...}, "kalshi": {...}}
    """
    if not path.exists():
        return {}
    data = tomllib.load(path.open("rb"))
    result: dict[str, dict[str, str]] = {}
    for canonical, exchanges in data.items():
        for exchange, aliases in exchanges.items():
            ex_map = result.setdefault(exchange, {})
            for alias in aliases:
                ex_map[alias] = canonical
    return result
```

#### Config directory validation

`run.py` validates at startup that every `config/` subdirectory
matches a known league key.  This prevents stale or misplaced
alias files from silently being ignored:

```python
# run.py

def _validate_config_dir():
    config = Path("config")
    if not config.exists():
        return
    for child in config.iterdir():
        if child.is_dir() and child.name not in LEAGUES:
            raise SystemExit(
                f"config/{child.name}/ does not match any "
                f"league in LEAGUES: {sorted(LEAGUES)}")
```

#### What this replaces

- `shared.py` `PX_ALIASES` dict → `config/nba/team_aliases.toml`
- `shared.py` `CANONICAL_ABBRS` frozenset → dropped for NCAAB
  (as per roadmap); for NBA, team validation can optionally use
  the set of canonical names from the team alias file
- `shared.py` `check_abbr()`, `normalize_px_abbr()` → replaced
  by generic alias lookup
- `data/nba/tables/player_aliases.csv` → `config/nba/player_aliases.toml`

Team and player aliases are loaded by the pipeline and passed
to exchange functions as parameters — they are runtime data, not
structural config, and do not appear in `PxConfig`, `KalshiConfig`,
or `OpticConfig`.


### Pipeline extraction and League Protocol

`pipeline.py` is extracted from `nba.py`.  It owns the entire
data processing pipeline.  `run.py` owns the CLI and output
formatting — the edges.

#### Interface

```python
# pipeline.py

class PipelineResult(NamedTuple):
    """Everything the CLI needs to format output."""
    rows: list[CanonicalRow]
    odd_lookup: dict[str, optic.Odd]
    game_ref_lookup: dict[str, optic.GameRef]


def run(data_dir: Path, league: League) -> PipelineResult:
    """Execute the full merge pipeline for one league and date."""
    ...
```

```python
# run.py

LEAGUES = {"nba": nba, "ncaab": ncaab}

def main():
    _validate_config_dir()
    league_key = args.league
    league = LEAGUES[league_key]
    result = pipeline.run(args.dir, league, league_key)

    if args.json:
        for r in result.rows:
            obj = canonical_row_to_json(r, result.odd_lookup,
                                        result.game_ref_lookup)
            print(json.dumps(obj))
    elif args.table:
        ...
```

#### League Protocol

The `league` parameter is typed via a Protocol — Python's
structural typing.  League modules satisfy it automatically by
having the right attributes; they never mention `League` or
inherit from anything.

```python
# pipeline.py

from typing import Protocol

class League(Protocol):
    KALSHI: KalshiConfig
    PX: PxConfig
    OPTIC: OpticConfig
    OUTPUT_ORDER: tuple
    MarketType: type[Enum]
```

#### What moves from nba.py into pipeline.py

Everything except the CLI:

- `ScheduleEntry` — generic, unchanged
- `match_event()` — generic, unchanged
- `_row_sort_key()` — parameterized by league's OUTPUT_ORDER and
  MarketType; derives `market_type_order` (dict) and
  `spread_types` (set) at pipeline startup, passes them in.
  The sort logic itself (favored team first, over before under,
  etc.) is sport-universal.
- `canonical_row_to_json()` — generic, unchanged
- `_Suspect` and the player name diagnostic — generic, unchanged
- The merge loop — generic, unchanged (operates on CanonicalRow
  and row keys, never on specific MarketType values)

#### What pipeline.run() does

```python
def run(data_dir: Path, league: League,
        league_key: str) -> PipelineResult:
    cfg_px = league.PX
    cfg_kalshi = league.KALSHI
    cfg_optic = league.OPTIC

    # Derive lookups from the league's MarketType enum
    market_type_order = {
        mt.value: i for i, mt in enumerate(league.OUTPUT_ORDER)
    }
    player_types = {
        mt.value for mt in league.MarketType
        if mt.scope == Scope.PLAYER
    }
    spread_types = {
        mt.value for mt in league.MarketType
        if mt.shape == Shape.SPREAD
    }

    # Load aliases from config/<league_key>/
    config_dir = Path("config") / league_key
    team_aliases = load_aliases(config_dir / "team_aliases.toml")
    player_aliases = load_aliases(config_dir / "player_aliases.toml")

    # Parse PX events (cfg_px.sport, cfg_px.tournament filter;
    #   team_aliases["px"] for abbreviation normalization)
    # Classify PX markets (cfg_px.exact, cfg_px.suffix)
    # Load Optic fixtures (cfg_optic.league_id filters)
    # Parse+match Kalshi markets (cfg_kalshi.prefix, etc.)
    # Merge loop: PX → Kalshi → Optic (unchanged logic)
    # Player name diagnostic (uses player_types)
    # Optic source_ids verification
    # Sort (uses market_type_order, spread_types)

    return PipelineResult(all_rows, all_odd_lookup,
                          all_game_ref_lookup)
```

#### PX validation stays in px.py

`px.group_markets` and `px.validate_markets` stay in the
exchange module — they check PX-specific structural contracts
(one GAME-scoped market per type, two TEAM-scoped per type,
etc.).  Other exchanges would have their own validation with
different invariants.

These functions are refactored to not require the league's
MarketType enum.  `group_markets` uses `defaultdict(list)`
instead of pre-populating from the enum, and `validate_markets`
iterates only the types present in data, getting scope from
each market's already-classified `wsd.market_type`.  This works
because the current validation skips absent types immediately
(`if n == 0: continue`), so removing those empty iterations
changes nothing.


## Kalshi variable-length team codes: chosen approach

For background, data investigations, and alternative approaches
considered, see `kalshi-abbrevs-notes.md`.


### The problem (summary)

NBA Kalshi event tickers encode both team abbreviations as
adjacent uppercase strings with no delimiter (`KXNBAGAME-
26FEB26DETOTT` → `DET` + `OTT`).  NBA works because all codes
are exactly 3 characters.  NCAAB, NHL, and soccer have
variable-length codes, making the concatenation ambiguous.


### Solution: GAME-market suffix disambiguation

The key insight is that Kalshi **market** tickers (not event
tickers) have a suffix after a second dash that provides the
missing information.

A Kalshi event ticker groups all markets for one game:

    KXNCAAMB1HSPREAD-26FEB21ECUCHAR    (event ticker)

Individual market tickers add a suffix:

    KXNCAAMB1HSPREAD-26FEB21ECUCHAR-ECU13   (market ticker)

For GAME-type markets, the suffix is a bare team code (no line
number).  Every game has exactly two GAME markets (three for
soccer, with a `TIE` suffix), one per team:

    KXNCAAMBGAME-26FEB21ECUCHAR-ECU
    KXNCAAMBGAME-26FEB21ECUCHAR-CHAR

The two suffixes partition the concatenated team string.  First
is away, second is home.

#### Algorithm

```python
# Extract the two non-TIE suffixes from GAME-type markets
s1, s2 = game_suffixes  # e.g. "ECU", "CHAR"
concat = team_string     # e.g. "ECUCHAR"

if s1 + s2 == concat and s2 + s1 != concat:
    away, home = s1, s2
elif s2 + s1 == concat and s1 + s2 != concat:
    away, home = s2, s1
elif s1 + s2 == concat and s2 + s1 == concat:
    raise ValueError(
        f"ambiguous: both orderings match for {concat}")
else:
    raise ValueError(
        f"neither ordering matches for {concat}")
```

The dual assertion (exactly one ordering matches, or fail loudly)
makes this bulletproof at runtime.  No mathematical proof about
collision impossibility is needed — if reality ever surprises us,
we find out immediately.

#### Verification

Tested against all available Kalshi data: **499 GAME events
across 10 leagues, 100% success.**  Every event has exactly 2
non-TIE GAME markets whose suffixes partition the concatenated
string.  No ambiguous cases (both orderings matching) were found
in actual data.

Specific variable-length cases confirmed:

| Event ticker | Concat | Suffixes | Split |
|-------------|--------|----------|-------|
| `KXNHLGAME-26FEB26EDMLA` | `EDMLA` | `EDM`, `LA` | `EDM` + `LA` |
| `KXNHLGAME-26FEB26CGYSJ` | `CGYSJ` | `CGY`, `SJ` | `CGY` + `SJ` |
| `KXNHLGAME-26FEB26NJPIT` | `NJPIT` | `NJ`, `PIT` | `NJ` + `PIT` |
| `KXNCAAMBGAME-26FEB21BCSMU` | `BCSMU` | `BC`, `SMU` | `BC` + `SMU` |
| `KXMLSGAME-26FEB21LAFCMIA` | `LAFCMIA` | `LAFC`, `MIA` | `LAFC` + `MIA` |

#### Runtime assertions

The code must assert at processing time:

1. Every event group contains at least one GAME-type market
   (or `2GAME` for La Liga 2).  This has been verified across
   all available data for same-day games.  Previous-day stale
   markets (e.g. NHL player props after game-level markets
   closed) are filtered by date before this assertion applies.

2. Exactly one of the two orderings matches (the algorithm
   above).

3. All other markets in the group (SPREAD, TOTAL, etc.) inherit
   the game identity from the GAME-derived team codes.

#### Edge case: team codes containing digits

Mainz 05 uses Kalshi ticker code `M05`.  Stripping trailing
digits from a SPREAD suffix like `M052` yields `M`, not `M05`.
Therefore: **always derive team codes from GAME markets first**
(where the suffix is a bare code), then use those as ground
truth for all other market types in the group.

#### What this means for alias tables

All three exchanges use abbreviations as team identifiers.  The
alias table maps each exchange's abbreviations to the canonical
(Optic) abbreviation.  The TOML format from the alias section
above handles this uniformly:

```toml
# config/ncaab/team_aliases.toml

[CLT]
px = ["CHARLT"]
kalshi = ["CHAR"]

[ACU]
kalshi = ["AC"]

[DETM]
kalshi = ["DET"]
```

Estimated alias table sizes for NCAAB:

| Exchange | Aliases needed | Type |
|----------|---------------|------|
| PX       | ~212          | abbrev → abbrev |
| Kalshi   | ~72           | abbrev → abbrev |

For NBA, Kalshi ticker codes match Optic abbreviations exactly
(~0 aliases needed).  For NHL and soccer, the tables will be
small (~32 and ~20 teams per league respectively).

#### Bootstrapping task

The ~72 Kalshi and ~212 PX NCAAB alias entries were estimated
from two dates of data covering ~320 of ~360 D1 teams.  The
285 Kalshi codes that string-match Optic abbreviations have NOT
been verified team-by-team.  Bootstrapping requires:

- An offline discovery tool that matches markets to fixtures by
  date and game pairing, auto-suggests aliases where codes agree,
  and flags mismatches for manual resolution.
- Incremental growth as new dates surface unseen teams.
- Verification that string-identical codes (e.g. both exchanges
  use `ARMY`) actually refer to the same team.


## Migration path

All steps are behavior-preserving until the final one.  Tests
pass at each step.

0. **Verify Shape assumption against NCAAB/NHL Kalshi data.  DONE.**
   Verified via `scripts/verify_shape_and_ordering.py` across
   16,508 game-scoped markets in 10 leagues (NBA, NCAAB, NHL,
   EPL, Bundesliga, La Liga, La Liga 2, Serie A, Ligue 1, MLS).
   All 56 unique (league, ticker_type) combinations have suffix
   patterns consistent with the proposed Shape dispatch.

   Corrections to the original proposal:
   - Player suffixes include a {TEAM} prefix the original table
     omitted: `{TEAM}{PLAYER_ENC}-{N}` for OVER_UNDER,
     `{TEAM}{PLAYER_ENC}` for YES_NO.  The parser is unaffected
     (player names come from titles, lines from `rfind("-")`).
   - FIRSTGOAL has a NOGOAL suffix for the no-goal outcome.
   - BTTS has no suffix (market ticker = event ticker).
   - M05 (Mainz 05) is a team code containing digits — already
     documented in the "Edge case" section above.

   The suffix pattern table in the "Shape" section has been
   corrected.  **The code must raise if a suffix does not match
   the expected pattern for its (scope, shape)** — any violation
   at runtime indicates a parsing bug or a new Kalshi encoding
   convention and must not pass silently.

0b. **Verify away+home ordering in Kalshi ticker concatenation.
   DONE.**  Verified via the same script.  499/499 GAME events
   split unambiguously using the two non-TIE GAME-market suffixes.
   Title cross-check (`"{Away} at {Home} Winner?"`) bridged via
   `yes_sub_title` and code-to-name substring matching: 491
   confirmed away-first, 0 home-first, 8 unclear (name-matching
   gaps where codes like CBJ/CGY don't substring-match city names
   like Columbus/Calgary — no counter-examples).

   **The code must raise if the GAME-suffix split fails** (neither
   ordering matches the concatenated string, or both do).  This
   is the dual assertion described in the "Algorithm" section
   above.  The away+home ordering is additionally validated by
   the title cross-check during development, but at runtime the
   split itself is the assertion — if the split succeeds, the
   first code is away.
1. **Add Shape to market_types.py.  DONE.**
   Added Shape enum (MONEYLINE, SPREAD, TOTAL, THREE_WAY,
   OVER_UNDER, YES_NO) and shape attribute to all 23 MarketType
   members.  Purely additive — no code reads .shape yet.

2. **Create `exchanges/`, move exchange modules there.  DONE.**
   Moved kalshi.py, px.py, optic.py into `mappers/exchanges/`.
   Updated all imports.  No logic changes.

3. **Create `leagues/nba.py` with NBA exchange configs.  DONE.**
   Added frozen config dataclasses to exchange modules
   (KalshiConfig, PxConfig, OpticConfig).  Created
   `mappers/leagues/nba.py` with NBA-specific config instances
   (KALSHI, PX, OPTIC) and OUTPUT_ORDER.  `mappers/nba.py` now
   imports OUTPUT_ORDER from the league module.  Exchange
   module-level constants kept until step 4.  PxConfig stores
   sport/tournament lowercased (e.g. "basketball", "nba").

4. **Parameterize exchange functions to take league config.  DONE.**
   Exchange functions take config objects instead of reading
   module-level constants.  League-specific dicts and regexes
   deleted from exchange modules; derived values (player_stat_types,
   player_suffix) computed from config at call time.  parse_event
   filters by config sport/tournament (returns None on mismatch).
   _EXPECTED_TYPE, TABLE_TYPES, _IGNORED_TYPES remain in px.py
   (deferred to step 5).
5. **Refactor exchange parse + build_rows to dispatch on Shape.  DONE.**
   All three exchange modules dispatch on `mt.shape` / `mt.scope`
   instead of specific MarketType values.  Kalshi `parse_event_ticker`
   dispatches suffix parsing on (scope, shape) instead of ticker_type
   strings; `player_stat_types` derivation removed.  PX `_EXPECTED_TYPE`
   (21-entry MarketType→str dict) replaced by `_PX_TYPE_FOR_SHAPE`
   (6-entry Shape→str dict).  `TABLE_TYPES` and `_IGNORED_TYPES`
   deleted — every classified market produces rows.  `group_markets`
   uses `defaultdict`; `validate_markets` iterates the grouped dict
   instead of the MarketType enum.  Optic GAME_TOTAL and TEAM_TOTAL
   branches merged under `Shape.TOTAL` with a scope check for entity.
   Verified byte-for-byte identical JSON output across all 4 data
   dates (60,394 rows) against main.
6. **Extract `pipeline.py` from `nba.py`.  DONE.**
   Moved ScheduleEntry, match_event, _row_sort_key,
   canonical_row_to_json, the merge loop, and the player name
   diagnostic into `pipeline.py`.  `nba.py` becomes a thin CLI
   wrapper calling `pipeline.run()`.  `_row_sort_key` parameterized
   via `_make_sort_key` closure so `spread_types` derives from the
   league config.  `League` Protocol defines the structural type
   that league modules satisfy.  Verified byte-for-byte identical
   JSON output across all 4 data dates.
7. **Wire `run.py` to dispatch through the league module.  DONE.**
   Created `mappers/run.py` with `LEAGUES` registry, argparse
   (positional league + dir, --json/--table), and
   `_validate_config_dir()`.  `pipeline.run()` gains `league_key`
   parameter.  Deleted `mappers/nba.py` — integration test updated
   to call `mappers.run nba`.

   Migrated alias system from NBA-hardcoded dicts in `shared.py`
   to per-league TOML files under `config/<league>/`.  Created
   `config/nba/team_aliases.toml` (5 PX aliases) and
   `config/nba/player_aliases.toml` (4 player aliases).  Added
   `load_aliases()` to `shared.py` (TOML loader, inverts
   canonical→exchange to exchange→{alias: canonical}).

   Removed from `shared.py`: `CANONICAL_ABBRS`, `PX_ALIASES`,
   `check_abbr()`, `normalize_px_abbr()`, `load_player_aliases()`.
   PX functions (`_sides`, `parse_event`, `extract_team`,
   `build_comp_map`) take `team_aliases` dict parameter.  Kalshi
   `try_parse_game_ticker()` returns raw ticker codes; pipeline
   normalizes via alias lookup before fixture matching.

   Verified byte-for-byte identical JSON output across all 4 data
   dates (60,394 rows).
8. Add `leagues/ncaab.py` and process NCAAB data
