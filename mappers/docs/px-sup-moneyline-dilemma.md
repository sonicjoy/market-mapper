# PX `sup_moneyline` market type

Discovered 2026-03-07.  Initially appeared only in 2026-03-06
fetches and seemed like a brief experiment, but Nick has confirmed
sup_moneyline has been around for a while.  We add `_YN` variants
reactively as new stat types appear in data rather than proactively
for all possible types — the mapping step is manual, and we only
want to support types we've actually seen.

## What it is

PX has started returning markets with `type: "sup_moneyline"` alongside
the established types (`moneyline`, `spread`, `total`).  These are
player prop markets — Made Threes, Total Points, Total Three Pointers
Made — that are semantically over/under but packaged in moneyline
structure.

## How we found it

Running `python -m mappers.run data/2026-03-06/23_54` raised:

    ValueError: Unrecognized PX market name: 'Alperen Sengün Made Threes '

Two issues stacked: (1) trailing whitespace in the name (fixed in
01284e9 with a Pydantic field_validator), and (2) the `sup_moneyline`
type failing the cross-check in `classify_market`, which expects
`"total"` for OVER_UNDER-shaped markets.

## Structural comparison

A regular `total` player prop:

    name: "Alperen Sengün Made Threes"
    type: "total"
    market_lines: [
      {line: 0.5, selections: [{outcome_id: 12, ...}, {outcome_id: 13, ...}]},
      {line: 1.5, selections: [...]},
      {line: 2.5, selections: [...]},
    ]

- Selections inside `market_lines` array, one entry per available line.
- Outcome IDs `{12, 13}` (over/under).
- Structured `line` field on each market_line.

A `sup_moneyline` version of the same market:

    name: "Alperen Sengün Made Threes"
    type: "sup_moneyline"
    line: 0
    selections: [
      {outcome_id: 1, line: 0, display_name: "Over 0.5"},
      {outcome_id: 2, line: 0, display_name: "Under 0.5"},
    ]

- Selections at top level (like `moneyline`), not inside `market_lines`.
- Outcome IDs `{1, 2}` (yes/no), same as PLAYER_DOUBLE_DOUBLE etc.
- Market `line` field is 0; selection `line` fields are 0.
- The actual threshold (0.5) is only in `display_name`.

## Key observations

**Coexistence (NBA)**: For the NBA event examined, the `sup_moneyline`
"Made Threes" coexists alongside a regular `total` "Made Threes" for
the same player.  The regular version has multiple lines (0.5, 1.5,
2.5); the `sup_moneyline` is a single line at 0.5.

**Sole version (NCAAB)**: For some NCAAB events, `sup_moneyline` is the
*only* version of the market — there is no regular `total` counterpart.
These are bettable markets we would miss entirely by skipping them.

**Multiple lines as separate records**: Some players have multiple
`sup_moneyline` records at different thresholds (e.g. Brenan Lorient
Total Points at 13.5 and 14.5, Rihards Vavers Total Three Pointers
Made at 2.5 and 3.5).  Each threshold is a separate market record,
unlike `total` where all thresholds are bundled in one market's
`market_lines` array.

**Timing**: Only appears in two 2026-03-06 fetches (19:11 and 23:54).
Not present in any earlier data (February), nor in the 2026-03-06
09:52 or 19:57 fetches, nor in 2026-03-07 08:05.  Across all data:

    2026-03-06/09:52   sup_moneyline=0   player_totals present
    2026-03-06/19:11   sup_moneyline=2   (1 NCAAB event)
    2026-03-06/19:57   sup_moneyline=0
    2026-03-06/23:54   sup_moneyline=13  (1 NBA + 6 NCAAB events)
    2026-03-07/08:05   sup_moneyline=0   player_totals=709

All NBA-only fetches (Feb 19 – Mar 3): zero sup_moneyline.
All NCAAB-only fetches (Feb 21 – Mar 3): zero sup_moneyline.

Initially this looked like a brief PX-side experiment, but as of
2026-03-09 Nick has confirmed sup_moneyline is has a history.  Both our
fetch script and Nick's call the same PX endpoint
(`/partner/mm/get_markets`) with no type filtering — the type is
from PX, not a script difference.

**Not empty**: Initial (wrong) assessment was that these had zero
market_lines and were placeholders.  They do have zero `market_lines`
but that's because their selections are at the top level.  They are
active, bettable markets.

## The dilemma

Our MarketType model accommodates these fine — "Made Threes Over 0.5"
is `PLAYER_THREES`, "Total Points Over 10.5" is `PLAYER_POINTS`.
The name-based classification works unchanged.

The friction is in three PX-specific places:

1. **`classify_market` cross-check** (px.py ~line 315): Maps
   Shape → expected PX type.  OVER_UNDER expects `"total"`, rejects
   `"sup_moneyline"`.  Needs to either accept multiple PX types per
   shape or be removed.

2. **`extract_market_lines` dispatch** (px.py ~line 261): Routes
   `"moneyline"` to top-level selections, everything else to
   `market_lines`.  `sup_moneyline` needs the moneyline path but
   isn't `"moneyline"`.  Simple to fix: check for top-level
   selections or match on a set of types.

3. **Side labels and line extraction**: This is the hard part.

   - Outcome IDs `{1, 2}` map to "yes"/"no" in `_FIXED_SIDE_LABELS`.
     For genuine yes/no markets (double-double) that's correct.
     For sup_moneyline over/under markets, we'd want "over"/"under".
     But `{1, 2}` is semantically correct here too — "Over 0.5 threes"
     is really "Yes, at least 1 three."  Whether we label the sides
     "yes/no" or "over/under" depends on whether we want consistency
     with the regular `total` version of the same market (which uses
     "over"/"under") or consistency with the PX outcome IDs.

   - The line value (0.5, 10.5, etc.) is only in `display_name`.
     The structured `line` fields are all 0.  Extracting the threshold
     requires parsing "Over 10.5" → 10.5, which is fragile compared
     to the clean numeric `market_lines[].line` we use for `total`.

## Resolution: YES_NO_LINE shape with _YN MarketType variants

The decisive constraint: two PX markets can't map to the same
canonical key.  For NBA, the regular `total` "Made Threes" already
occupies `(player, PLAYER_THREES, 0.5, over)`.  The sup_moneyline
version can't also map there.

Treating these as yes/no is semantically correct: "Over 0.5 threes"
= "Will he make at least 1 three?" = yes/no.  The outcome IDs
`{1, 2}` (yes/no) agree.

**New shape**: `YES_NO_LINE` — like YES_NO but with a line value in
the canonical key, needed because multiple sup_moneyline records can
exist at different thresholds for the same player.

**New MarketTypes** (added reactively as seen in data):
- `PLAYER_THREES_YN` — "Made Threes" / "Total Three Pointers Made"
- `PLAYER_POINTS_YN` — "Total Points"
- `PLAYER_STEALS_YN` — "Total Steals" (added 2026-03-09)

**Classification**: Name-based suffix matching produces the regular
type (PLAYER_THREES), then `_SUP_MONEYLINE_REMAP` redirects to the
_YN variant when `px_type == "sup_moneyline"`.

**Extraction**: Line value parsed from display_name ("Over 10.5" →
10.5) since the structured line fields are all 0.  Fragile but the
only option PX gives us.

**Side labels**: outcome_id 1→"yes", 2→"no" via existing
`_FIXED_SIDE_LABELS`.  No override needed.

## Post-resolution fix: cross-exchange merge for sole-version case

The `_YN` remap prevents PX-internal collisions but breaks the
cross-exchange merge with Optic.  Optic maps these markets as regular
`player_points` (over/under), not `player_points_yn` (yes/no), so the
`row_key` never matches.

In NBA, this didn't matter: Optic's `source_ids` always referenced
the regular `total` version, not the `sup_moneyline`.  The `_YN` rows
were PX-only orphans.

In NCAAB, where `sup_moneyline` was the sole version, Optic had no
choice but to reference it, producing "has PX source_id but we have
no PX match" reconciliation warnings.

Fix: `build_rows` now downgrades `_YN` rows to their regular
counterparts (`player_points`, over/under) when no regular `total`
version exists at the same `(entity, line)`.  When both coexist, the
`_YN` row stays to avoid collision.

## Maintenance

Nick confirmed sup_moneyline has been around a while (on 2026-03-09).  New stat
types will appear over time — when `classify_market` raises for an
unseen stat, add the `_YN` variant to `MarketType`, add the entry
to `_SUP_MONEYLINE_REMAP`, and update the list above.  We add
variants reactively (as seen in data) rather than proactively,
because the mapping step is manual and we only support defined types.

**YES_NO exception (2026-07-28):** PX may relabel genuine yes/no
markets (player double/triple-double) from wire type `moneyline` to
`sup_moneyline` without changing payload shape (`YES`/`NO`
display_names, outcome_ids `{1,2}`).  These are already
`Shape.YES_NO` — `classify_market` skips `_SUP_MONEYLINE_REMAP`, and
`_parse_sup_moneyline_line` accepts the YES/NO flavor with
`line=None`.  Do not add `*_YN` variants for them.  If PX ever ships
both a moneyline and a sup_moneyline DD for the same player,
`validate_markets` rejects the duplicate-player collision.
