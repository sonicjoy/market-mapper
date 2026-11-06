# Exchange market verities

Review conducted 2026-03-03 across the three exchange modules
(PX, Kalshi, Optic) and two league configs (NBA, NCAAB).
Updated 2026-09-18 (Kalshi tip-owned ignore + opt-in fetch).

2026-03-08, Greg: I had Claude rewrite this but won't read it now(!),
I just needed to make sure it was upt to date before I need it next.

## Two layers of verification

The pipeline enforces correctness at two distinct levels:

1. **"Is the input well-formed?"** — Each exchange module
   validates market *type classification* and *structural shape*
   before producing canonical rows.  These are the exchange-level
   verities documented below.

2. **"Did matching work?"** — After all three exchanges have
   produced rows and been merged, pipeline-level diagnostics
   compare matching results against Optic's source_ids and flag
   coverage gaps.  Documented in the final section.

The first layer is about data contracts with exchanges.  The
second is about our own matching quality.

## Exchange-level verities

### PX — strictest

Every market attached to a matching sport/tournament event
**must** classify via `cfg.exact` or `cfg.suffix`, or the
pipeline raises `ValueError`.  There is no ignore list.

This is correct: PX events are pre-filtered by sport and
tournament, so every market on a surviving event is expected to
be one of our known types.  If PX adds a new market name, we
want to know immediately.

Entity resolution (team prefix → canonical abbreviation) is a
separate step.  Markets with a recognized type but unresolvable
team prefix are skipped with a diagnostic — this catches PX data
errors and missing aliases rather than unknown market types.
(`classify_and_enrich` returns None, pipeline warns via
`px_skip_message`.)

PX also cross-checks the `type` field (moneyline, spread, total,
sup_moneyline) against the classified Shape.  A mismatch raises.
`extract_market_lines` further validates per-type structural
invariants: outcome_ids, selection counts, line consistency, and
spread symmetry.

Validated clean across 4 dates of NBA data and 2 dates of NCAAB.

### Kalshi — opt-in fetch, tip-owned ignore

Game tickers (those matching `cfg.prefix`) extract a type string
(e.g. `SPREAD`, `PTS`).  At parse time:

  - `cfg.table_types` — mapped, produces canonical rows (Python
    factory table + tip `map` overlay via `overlay_kalshi`)
  - `cfg.ignored_ticker_types` — tip `ignore` overlay only; Python
    `*_kalshi.py` factories ship `frozenset()` (soccer pattern)
  - anything else — `parse_event_ticker` returns `None`; the
    pipeline warns once per unknown type and skips

Fetch (`fetch/kalshi.series_tickers`) is opt-in on overlayed
`table_types` keys, plus `extra_series`, plus conference tournament
series when `has_tournaments` and `is_tournament_series()` (short
`{type}-YY` shape — not every suffix under the prefix).  Tip ignores
still filter fetch.  Sibling prefixes (`KXATPCHALLENGER*` under
`KXATP`) stay unfetched until the tip maps them.

Non-game tickers (futures, awards — different prefix) are filtered
earlier by `game_suffix()` and never reach type classification.

**History (2026-03-03):** `_extract_ticker_type` used to filter
against `table_types | ignored_ticker_types`, silently skipping
unknowns.  That was fixed so the type string is always returned.

**History (2026-09):** Python ignore catalogs removed from factories;
unknown unmapped types skip instead of raising.  NCAAB awards like
`NAISMITH` / `UNDEFEATED` are tip `mapping_market_rules` ignore pins,
not factory frozensets.

### Optic — permissive (by design)

Odds whose `market_id` is not in `cfg.table_types` are silently
skipped.  No raise, no ignore list.

This is correct: Optic is our canonical source.  Which market
types we map is an editorial choice made by populating
`table_types`.  Optic likely exposes many `market_id` values we
don't care about (quarter totals, alternate lines, etc.).
Discovering new Optic market types to add is an out-of-band step,
not something the pipeline should enforce at runtime.

For opted-in types, the shape dispatch in `build_rows` is strict:
inline asserts verify field presence, an `else: raise` catches
any Shape added to the enum but not handled, and a collision
guard raises if two odds resolve to the same
(market_type, entity, line, side) with different grouping_key
values — preventing silent data corruption from ambiguous dedup.

## Code changes (2026-03-03)

The Kalshi bug fix (`_extract_ticker_type` simplification) and
the four comment corrections in nba.py / ncaab.py were made on
a dirty working tree during the multi-league refactor.

**Superseded (2026-09):** Kalshi unknown types now return `None`
from `parse_event_ticker` (skip + warn), not raise.  Python factories
ship empty `ignored_ticker_types`; tip `mapping_market_rules` own
map/ignore.

## Comments fixed (2026-03-03)

- `nba.py` line 55–56: was "skipped (PX, Optic) or raise
  (Kalshi)" — now "skipped (Optic) or raise (PX, Kalshi)".
- `nba.py` line 85: was "PX ... are skipped" — now "... raise".
- `ncaab.py` line 57–58: same inversion as NBA — fixed.
- `ncaab.py` line 81: same "skipped" wording for PX — fixed.

## Optic table_types coverage policy

NCAAB's Optic config (ncaab.py lines 106–109) documents a
deliberate policy: only include Optic market types that have
cross-exchange coverage (i.e. a corresponding PX or Kalshi
mapping).  Types that Optic offers but neither exchange covers
(e.g. player_blocks, player_steals in NCAAB) are excluded to
avoid source_id verification noise — `verify_source_ids` would
flag them as unmatched since no exchange row exists to merge onto.

NBA doesn't state this policy explicitly but follows it in
practice: every Optic table_type in nba.py has at least one
exchange counterpart.

To review: is this the right long-term policy?  Adding
Optic-only types would give us canonical rows with optic_id but
no kalshi_ticker or px_line_id — valid output, but
source_id verification would need adjustment.

## Potential Optic validations to add

For opted-in market types, we could strengthen the contract
within `build_rows`.  Candidates, roughly by likelihood of
catching real issues:

1. **`team_map` result is `home` or `away`** — not needed.
   `team_map` is built from exactly two competitors
   (`{home_id: home_abbrev, away_id: away_abbrev}`), so the
   lookup can only return home or away.  An unknown `team_id`
   raises `KeyError` — stricter than any assert.  Verified:
   0 mismatches across 82k odds with `team_id`.

2. ~~**`selection_line` is `"over"` or `"under"`**~~ — done.
   TOTAL, OVER_UNDER, and YES_NO now assert
   `selection_line in ("over", "under")`.  Optic does use
   `"even"`/`"odd"` selection_line values, but only on
   `team_total_odd_even` and `2nd_quarter_team_total_odd_even`,
   which are out-of-scope market types (not in table_types).

3. ~~**`odd.points` is not None for SPREAD**~~ — done.
   SPREAD, TOTAL, and OVER_UNDER all assert `points is not None`.
   TOTAL and OVER_UNDER additionally assert `>= 0`.
   SPREAD does not — spread points are signed.

4. **Half-point lines are half-points** — not assertable.
   Whole-number lines are legitimate (they create push
   scenarios).  Data shows ~9% of spreads and ~2% of totals
   are whole numbers.

5. ~~**YES_NO `selection_line`**~~ — done (special case of #2).

All items resolved.

## Pipeline-level diagnostics: did matching work?

After all three exchanges produce canonical rows and the merge
is complete, the pipeline runs a series of diagnostics that check
*matching quality* — not input validity, but whether our game
resolution and row merging found the right counterparts.

### verify_source_ids (optic.py)

Compares our PX/Kalshi matches against Optic's `source_ids`
field (Optic's own cross-references to PX and Kalshi).

- **Confirmed mismatch → raises.**  Both we and Optic matched
  the same row to an exchange, but the IDs disagree.  This is a
  mapping bug.
- **Optic has source_id, we have no match → classified warning**
  (one per game).  Skip reasons:
    - *Stale Optic source_id* — ticker date doesn't match fixture
      date (Optic carried over a source_id from a previous
      matchup between the same teams).
    - *Disambiguation failure* — no GAME-type moneyline market
      for Kalshi team-code splitting; game group skipped.
    - *Fixture miss* — Kalshi game resolved but didn't match an
      Optic fixture.
    - *Not in data* — Kalshi ticker not present in our data file.
    - *Ignored by config* — the cited ticker type is in the
      overlayed `ignored_ticker_types` (tip `ignore` pin), so no
      canonical row can own it (tennis: Optic maps
      `1st/2nd_set_moneyline` while Kalshi `SETWINNER` is tip-
      ignored).
    - *Unexpected* — none of the above; possible mapping bug.
- **We matched, Optic had no source_id → novel mapping count.**
  Printed as summary counts (PX and Kalshi separately).  These
  are matches we built that Optic couldn't provide — the
  pipeline's value-add.

### Team alias coverage (pipeline.py)

Checks every Optic abbreviation appears in `team_aliases.toml`.
Prints missing abbreviations so the operator can add them.

### PX skip messages (pipeline.py + diagnostics.py)

When `classify_and_enrich` returns None (team prefix not in
`event_team_map`), the pipeline prints a deduplicated diagnostic
per (event, prefix) pair, distinguishing unknown abbreviations
from PX data errors.

### Kalshi disambiguation failures (pipeline.py)

Games where no GAME-type market exists to split team codes from
the concatenated regex match.  Tracked in `kalshi_skip_reasons`
and reported during source_id reconciliation.

### Other-date skips (pipeline.py)

PX and Kalshi events whose date doesn't match the fixture date
are counted and reported.  These are expected when exchange data
spans multiple game dates.

### Player orphan table (diagnostics.py)

Per-game player rosters with edit-distance metrics between
exchange and Optic player names.  Surfaces name normalization
near-misses that would otherwise silently fail to merge.
