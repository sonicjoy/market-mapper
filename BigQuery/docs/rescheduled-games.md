# Rescheduled games and market_mapping dupes (RESOLVED 2026-03-16)

**Problem:** `start_date` is part of the MERGE key in `load_mappings.py`.
When a game is rescheduled between fetches, the new `start_date` doesn't
match the existing row, so MERGE inserts a duplicate.

**Fix implemented:** `_clean_reschedules()` in `load_mappings.py` runs
two detection passes before the MERGE, deleting stale rows:

1. Join on `game_id` — catches time shifts where game_id is stable.
2. Join on Kalshi `source_ids.market_id` + `source_ids.selection_id` —
   catches cross-date reschedules where Optic changed the game_id but
   Kalshi kept the same ticker.

See the detailed comment block in `load_mappings.py` for design
rationale, evidence, and known limitations.

**Cleaned up existing dupes:** Deleted 130 stale rows from 3 games
(Houston/Arizona, NC State/Texas, Howard/UMBC) on 2026-03-16.

## Pipeline side: does the mapper produce correct output after a reschedule?

- **PX:** Matches fine.  PX events carry the actual scheduled time;
  the pipeline matches by (date, home, away) against Optic fixtures.
  Both sources update to the new time, so they agree.
- **Kalshi:** Same-date time shifts work (ticker date still matches).
  Cross-date reschedules: the pipeline **auto-remaps** when the ticker
  date is missing from Optic and there is a unique unclaimed forward
  fixture within 7 days.  Ambiguous cases still need a manual
  `kalshi_rescheduled.toml` entry (see docs/kalshi-missing-game-tickers.md).

## Loader side: does the BQ load avoid dupes?

| Scenario | game_id stable? | Has Kalshi? | Pass 1 | Pass 2 | Pass 3 | Status |
|---|---|---|---|---|---|---|
| Time shift | Yes | Yes/No | Catches | (redundant) | — | **Fixed** |
| Cross-date, auto-remap or toml | No | Yes | Misses | Catches | — | **Fixed** |
| Cross-date, not yet remapped | No | No | Misses | Can't help | GC after 24h | **Temporary gap** |
| Cross-date, PX-only game | No | Never | Misses | Can't help | GC after 24h | **Narrowed** |
| Started fixture still in table | — | — | — | — | Deletes >24h past | **Fixed** |

**Pass 3 (stale started-fixture GC):** Before MERGE, delete rows for
leagues in the current stage batch whose `start_date` is more than
24 hours in the past.  Such mappings can only produce `FIXTURE_STARTED`
poison in a Greg-first RFQ resolver; downstream `mapping_loader`
already filters to future games.

**Temporary gap** (cross-date, not yet remapped): The pipeline may
produce PX-only rows with the new game_id/start_date while old Kalshi
rows persist until auto-remap (or TOML) stages corrected Kalshi data
and Pass 2 fires — or until Pass 3 ages them out after 24h.

**Permanent gap** (PX-only cross-date reschedule before Pass 3): No
Kalshi ticker to anchor Pass 2.  Pass 3 eventually removes the old
started rows.  We haven't observed PX-only games often — games with
PX data almost always have Kalshi data too.

RFQ resolver follow-up (prefer ORIGINAL over past-start GREG): see
`docs/mmkalshi-greg-first-reschedule.md`.

## Not a reschedule: two `fixture_id`s, same `game_id`

Optic can leave a mint-date clone beside the listing that actually
went live (same `game_id` and `start_date`). Pass 1–3 never see a
time or ticker move, so they do not delete the extra board.

The mapper collapses those clones in `load_fixtures` (one Fixture per
`game_id`). See `mappers/docs/optic-game-id-clones.md`. That pass does
not DELETE leftover `market_mapping` rows already written under the
loser `fixture_id`.

## Timing: Kalshi mappings can be temporarily lost

When Pass 1 fires (time shift, game_id stable), it deletes all
old-time rows — including Kalshi rows.  If the incoming batch doesn't
have Kalshi data (e.g. Kalshi hasn't updated yet), those mappings are
temporarily gone.  This is correct: the old rows had the wrong
`start_date`, and `mapping_loader.py` filters on
`start_date >= CURRENT_TIMESTAMP()`, so stale-time mappings would
produce wrong join results downstream anyway.

## What we considered but didn't do

- **Change the MERGE key** to use `game_id` instead of `start_date`.
  Rejected: `game_id` is not stable across cross-date reschedules
  (verified in BQ — the date suffix changes, e.g.
  `18107-33911-2026-02-14` → `18107-33911-2026-02-25`).
- **Drop `start_date` from the key entirely.**  Rejected: same-team
  rematches on different dates would collide (common in NBA).
- **Make downstream consumers tolerate dupes** (DISTINCT, ROW_NUMBER).
  Simpler, but changes production code during March Madness freeze.
  Also, picking latest `start_date` only works if reschedules always
  push forward — a game moved earlier would keep the wrong row.
