# MLB market types across exchanges

Investigated 2026-03-24.  MLB has a much larger tail of PX market
types than NBA/NCAAB.  This document captures what we found so we
don't have to re-derive it.

## PX market names (from data/2026-03-24/01_18)

### Game-level (mapped)

- `Moneyline` — type: moneyline
- `Run Line` — type: spread
- `Total Runs` — type: total

### Player props — batting (not yet mapped)

All type: total.

- `{Player} Total Hits` (269 markets)
- `{Player} Total Bases` (269)
- `{Player} Total RBIs` (263)
- `{Player} Total Runs` (271 — ambiguous with game "Total Runs",
  but game-level is in `exact`, player-level would be suffix)
- `{Player} Total Home Runs` (25)
- `{Player} Singles` (123)
- `{Player} Total Walks` (110)
- `{Player} Stolen Bases` (14)
- `{Player} Total Hits, Runs & RBIs` (28)

### Player props — pitching (not yet mapped)

All type: total.

- `{Player} Total Pitching Strikeouts` (32)
- `{Player} Hits Allowed` (30)
- `{Player} Walks Allowed` (30)
- `{Player} Total Earned Runs Allowed` (19)
- `{Player} Total Outs Recorded` (15)
- `{Player} Total Runs Allowed` (11)

### Milestones variant (not mapped, lower priority)

- `{Player} Total Pitching Strikeouts Milestones` (6)

Same stat as the regular `Total Pitching Strikeouts` but with a
wider line range (2.5–8.5 vs 4.5–5.5).  Different PX market ID
and different line_ids.  Optic sometimes links to these instead of
the regular version — causes "stale" misdiagnosis in verification
(see below).

### Period markets (not mapped)

- `1st Inning Spread`
- `1st Inning Total Runs`
- `1st-5th Inning Moneyline`
- `1st-5th Inning Spread`
- `1st-5th Inning Total Runs`

### Team totals

- `{Team}: Team Total Runs` (16)

## Optic market_ids

Optic uses these `market_id` values for MLB:

- Game: `moneyline`, `run_line`, `total_runs`
- Team: `team_total`
- Batting: `player_hits`, `player_bases`, `player_rbis`,
  `player_runs`, `player_home_runs`, `player_singles`,
  `player_stolen_bases`, `player_hits_+_runs_+_rbis`
- Pitching: `player_strikeouts`, `player_hits_allowed`,
  `player_earned_runs`, `player_outs`, `player_walks`
- Note: Optic `player_walks` is pitcher walks allowed (verified:
  selections are pitcher names like Logan Webb, Max Fried).

## Milestones and Optic source_ids

When Optic links a `player_strikeouts` market to PX, it sometimes
references the Milestones variant's `selection_id` rather than the
regular market's.  Example:

    Optic: player_strikeouts:max_fried_over_5_5
      source_ids.Prophet X.selection_id = 28526af0...  (Milestones market 630005839)
    Our PX match:
      px_line_id = b764f099...  (regular market 440005839)

Both point to "Max Fried over 5.5 strikeouts" on PX, just in
different market objects.  Verification case 3a ("stale") fires
because the Milestones line_id isn't in `px_line_lookup` — we
don't map Milestones markets.  The diagnosis is wrong (the PX
market is active, not stale); the action (keep our mapping) is
correct.

### Fix design (implement when adding player props)

Verification case 3a currently only checks `px_line_lookup` (built
from mapped canonical rows).  Milestones line_ids aren't there
because we don't map them — correct, but the "stale" diagnosis is
wrong.

Split case 3a into two sub-cases using a broader set of all PX
line_ids seen during parsing:

1. Collect `all_px_line_ids: set[str]` from every PX market in the
   raw data, *before* the `is_known_market` filter.  This includes
   Milestones, period markets, etc.  Collection point: the filter
   loop in pipeline.py (~line 384).

2. Pass `all_px_line_ids` to `verify_source_ids`.

3. In case 3a, before declaring "stale", check `all_px_line_ids`:
   - Found → "unmapped PX variant" (benign, like sup_moneyline
     sibling).  Count as `px_unmapped_variant`.
   - Not found → genuinely stale (PX regenerated the market).
     Count as `px_stale` as today.

This parallels how sup_moneyline siblings work (case 3b) — those
are in `px_line_lookup` because we map them.  Milestones just need
the secondary lookup since we deliberately don't map them.

## No sup_moneyline in MLB

As of 2026-03-24, MLB PX data has zero `sup_moneyline` markets.
All player props are type: total.  (sup_moneyline is an NBA/NCAAB
phenomenon so far.)

## MarketType definitions

Kalshi `OUTS` / `RBI` / `SB` → `PLAYER_OUTS` / `PLAYER_RBIS` /
`PLAYER_STOLEN_BASES` are wired in `baseball_kalshi.py` /
`baseball_markets.py`.  Remaining types below are the full MLB
player-prop set in `market_types.py`:

    # Player-scoped — baseball batting
    PLAYER_HITS, PLAYER_BASES, PLAYER_RBIS, PLAYER_RUNS,
    PLAYER_HOME_RUNS, PLAYER_SINGLES, PLAYER_WALKS,
    PLAYER_STOLEN_BASES, PLAYER_HITS_RUNS_RBIS, PLAYER_OUTS

    # Player-scoped — baseball pitching
    PLAYER_STRIKEOUTS, PLAYER_HITS_ALLOWED, PLAYER_EARNED_RUNS,
    PLAYER_OUTS, PLAYER_RUNS_ALLOWED, PLAYER_WALKS_ALLOWED

All are (Scope.PLAYER, Shape.OVER_UNDER).
