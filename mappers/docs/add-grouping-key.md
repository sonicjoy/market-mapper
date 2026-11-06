# Add grouping_key to CanonicalRow

## Problem

Optic odds carry a `grouping_key` field that pairs the two sides of a
bet.  For most markets it's redundant with the existing merge key
`(date, home, away, market_type, entity, line, side)` — e.g.
`"default:217.5"` just restates the line, `"dylan_larkin:0.5"` just
restates entity + line.

For head-to-head player props it carries genuinely new information.
H2H markets pit two named players against each other (e.g. "Scottie
Barnes vs Stephon Castle — who gets more assists?").  Both sides of
the bet have:

    market_type = "player_assists_h2h_moneyline"
    entity      = "stephon_castle"    (the player you're betting on)
    line        = None
    side        = "stephon_castle"

If Stephon Castle appears in two matchups (vs Barnes AND vs Quickley),
the only distinguishing field is `grouping_key`:
`"scottie_barnes_stephon_castle"` vs
`"immanuel_quickley_stephon_castle"`.  Without it the merge key
collides and the second matchup silently overwrites the first.

H2H markets exist in our NBA Optic data today but were being skipped.

## Design discussion

### Approaches considered

**A. None + collision guard (chosen).**  Set `grouping_key=None` on
CanonicalRow for all markets where `(entity, line, side)` is
sufficient.  For H2H, pass through the raw Optic value.  A collision
guard in `optic.build_rows` detects when two odds share the same
`(market_type, entity, line, side)` but have different raw
`grouping_key` values while the CanonicalRow's `grouping_key` is
None — and raises immediately.  No maintained list of "which markets
need grouping_key"; the data tells us.

PX/Kalshi leave `grouping_key=None` (they don't have H2H markets in
our current data).  Since None == None, the three-way merge is
unaffected for all existing markets.

**B. Derive from CanonicalRow fields.**  Compute `grouping_key` from
`(entity, line)` using a formula like `f"{entity}:{line}"`, same in
all three exchanges.  They agree by construction.  But this fails for
H2H: the matchup pairing (`"scottie_barnes_stephon_castle"`) can't be
derived from entity + line.  So H2H is still a special case, and the
derived value adds no discriminating power beyond what's already in the
merge key.

**C. Always use raw Optic grouping_key, compute matching values in
PX/Kalshi.**  The problem: Optic's team_total grouping_key uses full
team names (`"ottawa_senators:1.5"`) while our pipeline uses
abbreviations (`"OTT"`).  Computing matching strings in PX/Kalshi
requires full-name lookups or Optic normalization.  Fragile coupling
for zero benefit — the information is already in entity + line.

**Post-hoc confirmation (2026-03):**  The rekeying investigation
(`docs/rekeying-to-optic.md`, Check 3a) found that Optic mutates
`grouping_key` display names across fetches (e.g.
`giannis_antetokounmpo_+_keyonte_george:29.5` →
`g_antetokounmpo_+_keyonte_george:29.5`).  This means raw Optic
`grouping_key` values are unstable over time — a further reason
Approach C would have been problematic.

### Why A wins

All three approaches must special-case H2H (it carries genuinely new
information).  For non-H2H markets, approaches B and C compute a
grouping_key that's strictly redundant with fields already in the
merge key.  Approach A is the simplest correct approach: None for
redundant cases, raw value for H2H, collision guard as safety net.

### The merge-key constraint

Adding `grouping_key` to `row_key` means all three exchanges must
agree on its value for the same logical bet.  For non-H2H, all three
produce None.  For H2H, only Optic has these markets today so there's
no cross-exchange merge to worry about.  When PX/Kalshi add H2H
markets, their `build_rows` will compute a matching `grouping_key`
from their own market data — same pattern as every other field.

## What changed

- `Odd` model (`optic.py`): added `grouping_key: str = "default"`
- `CanonicalRow` (`shared.py`): added `grouping_key: str | None = None`
- `Shape.H2H` and `MarketType.PLAYER_ASSISTS_H2H` (`market_types.py`)
- H2H branch in `optic.build_rows`: sets entity, side, line, and
  `grouping_key=odd.grouping_key`
- Collision guard in `optic.build_rows`: raises if two odds collide
  on `(market_type, entity, line, side)` with different raw
  grouping_keys while the row's grouping_key is None
- `row_key` extracted to module level in `pipeline.py`, includes
  `grouping_key`
- JSON output: `grouping_key` in both `"key"` and `"optic_odds"` dicts
- `_PX_TYPE_FOR_SHAPE`: added `Shape.H2H: "moneyline"`
- NBA Optic `table_types`: added `player_assists_h2h_moneyline`

## Verification

Green/red/green:

1. **Green:** pipeline on NBA, NCAAB, NHL — collision guard silent,
   grouping_key=None everywhere, merge unchanged.
2. **Red:** H2H branch added WITHOUT setting grouping_key — collision
   guard fires for Immanuel Quickley (two matchups, same key fields,
   different raw grouping_keys).
3. **Green:** `grouping_key=odd.grouping_key` set in H2H branch —
   guard passes, 32 H2H assists rows produced on NBA 2026-02-25.

Regression: stripped grouping_key from new JSON output and compared
to old — 1553 rows identical.  6 new H2H rows added.  109 tests pass.

## Future work

This is the foundation for mapping PX and Kalshi markets to Optic H2H
markets.  No PX or Kalshi H2H markets have been seen in our data
snapshots yet.  When they appear, their `build_rows` functions need an
H2H branch that computes a matching `grouping_key` from their own
market data — at which point it will pay to revisit the design,
because H2H is stretching the Shape model (see the comment on
`Shape` in `market_types.py`).

- **Check PX and Kalshi for H2H markets.**  Our local data snapshots
  don't contain H2H markets for PX or Kalshi, but we haven't checked
  whether the exchanges actually offer them.
- Add to NCAAB too.