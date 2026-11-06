# Optic fixture clones (same `game_id`, two ids)

Optic sometimes lists **one match twice**: two `fixture_id`s, the same
`game_id`, usually the same `start_date`. The mapper schedule index
used to keep both. Same `(date, home, away)` then looked like an MLB
doubleheader, so Kalshi fail-closed and Polymarket passthrough emitted
two boards.

**Fix:** `load_fixtures` in `mappers/exchanges/optic.py` keeps **one
Fixture per `game_id`**. True doubleheaders still have two `game_id`s
and stay a list.

## How this differs from a reschedule

| Shape | `fixture_id` | `game_id` | Who handles it |
|-------|--------------|-----------|----------------|
| Same-day time shift | same | same | MERGE / Pass 1 in `load_mappings` |
| Cross-date resume (MLB rainout) | new | new date suffix | auto-remap + Pass 2/3 |
| **Clone leftover** (this doc) | **two** | **same** | `load_fixtures` collapse |

Example: Uruguay Primera Albion vs Progreso (2026-09-07). Optic minted
`202609057767889F` for the original 5 Sep listing, then
`20260907261BED6B` after the move to the 7th, and rewrote both rows
onto `game_id=10814-17438-2026-09-07` / kickoff 18:00 UTC. Kalshi had
already minted `26SEP05` and `26SEP07` tickers; Optic glued both ticker
families onto both boards. The id prefix is mint date, not kickoff.

## Keep rank

Lower wins: **live > completed > delayed > unplayed > cancelled**.

- `live` — in-play board. Keep it even when the id still has the old
  YYYYMMDD prefix (Albion went live on `20260905…`).
- `completed` — that board already went through live. Beats a leftover
  `delayed` clone (Hungary/Argentina date-matching completed vs stuck
  delayed). One Optic smash still wins this way: Portugal Campeonato
  Machico 4 Sep keeps rewritten `20270130…` (week-16 1–1) over the
  delayed week-3 Machico listing.
- `delayed` — current listing that has not gone live. Beats leftover
  `unplayed`.
- `cancelled` — inactive. Drop it when any other clone exists; keep
  it only if it is the sole row for that `game_id`.
- `unplayed` — normal pre-kickoff status (`/fixtures/active` is almost
  always unplayed or live). Indecisive when two clones are both
  unplayed: prefer the id whose YYYYMMDD prefix matches UTC
  `start_date`, else lexicographic `fixture_id`.

Do not rank on price volume or Optic Kalshi `source_ids`. The ghost
board can have more ticks, and Optic cross-wires both ticker families.

Drops log to stderr:

```
optic: collapse clone {loser} → {winner} game_id=…
```

Tests: `tests/mappers/test_doubleheader.py`.

## What this does not do

- Does **not** delete loser rows from `markets_us.market_mapping`.
  Loader DELETEs (`_clean_reschedules`, stale-started) look for a
  changed `start_date` or ticker/token on a **new** `game_id`. Clones
  share both, so those passes miss them. Pre-match MERGE can rewrite
  `fixture_id` on matching keys; in-play is insert-only for that
  `game_id`, so a split already in BQ freezes until after the match
  (or until stale-started GC >24h).
- Does **not** delete Optic warehouse rows
  (`opticodds_us.opticodds_fixtures`). Harvest can still see both
  clones.
- Does **not** union both odds books onto the winner, and does **not**
  load Kalshi from Optic `source_ids` (that would import the 2×2).
