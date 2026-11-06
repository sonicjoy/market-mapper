# MMkalshi follow-up: Greg-first resolver and delayed games

> Historical note. Tip/console steps here are retired; see CLAUDE.md.

**Status**: recommendation for MMkalshi (out of mmmapper repo)
**Added**: 2026-07-29
**Context**: CLE@CIN / ATL@NYM / BAL@BOS — Kalshi kept original ticker, Optic
issued a new fixture; stale GREG rows in `markets_us.market_mapping` won
over Optic ORIGINAL via Greg-first `COALESCE`, causing `FIXTURE_STARTED`
RFQ rejections.

## What mmmapper now does

1. **Matcher auto-remap** — when a Kalshi ticker date is missing from the
   Optic index but the same teams have a unique unclaimed forward fixture
   within 7 days, the pipeline remaps automatically (TOML still overrides).
2. **BQ Pass 2** — existing Kalshi-ticker join deletes stale
   `(game_id, start_date)` rows once corrected rows are staged.
3. **BQ Pass 3** — deletes rows whose `start_date` is more than 24 hours
   in the past (scoped to leagues in the current stage batch).

These reduce how often poison rows sit in BQ. They do **not** fix the
resolver preferring a started GREG fixture when a correct ORIGINAL
mapping already exists, nor do they push RFQ's in-memory cache.

## Recommended MMkalshi changes

### 1. Start-time guard on Greg-first resolution

In `mapping_loader` / RFQ leg resolution, when choosing between GREG and
ORIGINAL for the same Kalshi `market_ticker` + side:

- If the GREG fixture's `start_time` (or mapped fixture start) is already
  in the past **and** ORIGINAL has a future fixture for that ticker+side,
  prefer ORIGINAL (or drop the GREG candidate).
- A stale GREG row must never beat a correct Optic ORIGINAL row for
  quoting.

Sketch (conceptual):

```text
resolved_fixture = COALESCE(
  greg_fixture_if_start_in_future,
  original_fixture,
  greg_fixture  -- last resort
)
```

### 2. Refresh mappings after mmmapper loads

After each successful mmmapper → BQ load (or on a short interval), hit
`/refresh-mappings` on the RFQ service so DELETEs and corrected rows
propagate without a manual curl. Alternatives: shorten the periodic
reload interval so the worst-case lag is minutes, not hours.

## Ops until Layer 3 ships

For an active incident: DELETE stale GREG rows for the old `fixture_id`,
hit `/refresh-mappings`, and (if auto-remap did not catch it) add a
`config/<league>/kalshi_rescheduled.toml` entry. See
`mappers/docs/kalshi-missing-game-tickers.md` and knowledge entry
`kalshi-mlb-rescheduled-games.md`.
