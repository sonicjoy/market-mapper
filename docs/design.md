# Design

Agent instructions.  Read and understand the file, as for any clarifications if things
are unclear.  Then read each TODO, propose how to action it to the user, and wait for a response.

## Principles and questions

We should aim to match the Optic output.  Not all the properties (there are many) but where
we need to output something similar, match the **structure and property names exactly**

## Input

## Prophet X (PX)

### Events

We get a separate prophetx_events.jsonl file.  The fields we care about:

```
scheduled, timestamp in UTC
sport_name
tournament_name
event_id
name
competitors array
  name
  abbreviation
  side
```

### Markets

We get a PX markets file, prophetx_markets.jsonl.  The fields we care about:

#### Moneyline shape

```
type
sport_event_id
line
selections
  name
  line
  outcome_id
```

#### Spread shape

```
name
sport_event_id
market_lines
  type
  name
  selections
    name
    line
    outcome_id
```

## Output structure

### Optic input structure fields we care about

```
start_date, in UTC
home_competitors array
  name
  abbreviation
away_competitors array
  name
  abbreviation
sport dict
  id
league
  id
odds
  normalized_selection
  market_id
  points
  selection_line
  source_ids dict
    "Prophet X" dict
      event_id
      selection_id
    "Kalshi" dict
      market_id, ticker (distinct from the event ticker)
```

I looked at just an NBA player_points market to decide that the following
"selection classification" fields for odds were definitive:

`normalized_selection, market_id, points, selection_line`

But we should do a fuller assessment across **all market types and sports** to ensure 
that these fields capture ALL the key information we need to output.  I suppose I am asking:
are these fields enough to uniquely classify a "betting market" in the most general sense:
something you can bet for or against.

In a way it doesn't matter because we will always be outputting the PX or KX source
ids, and THEY point directly at a selection (PX) or market (KX) and KX markets are very granular, down
to the selection level, where need be.  But we are **deriving** the selection classification fields
based only on the PX and KX data, so in a way we are duplicating.  But we need to put something
readable in the output, and try and match it to Optic conventions.

TODO: Assess and catalog the way Optic creates "selection classification" fields above, based on our
sample data.  Report on this, we need to decide how hard it is for us to match it exactly.

### Our output structure

Out output structure will exactly match the subset of the Optic input structure 
documented above.

We MUST match Optic fields names and SHOULD try and match in value, e.g. UTC, snake case 
formatting, standard word (noun, verb) ordering, etc.

TODO: Systematically assess the content of each optic property documented above from the
sample data in data/ and report.

## Selection classification field assessment

Assessment of `normalized_selection, market_id, points, selection_line` across all
market types in the Optic sample data (`data/nba/2026-02-21/optic_fixtures_odds.jsonl`).

**Conclusion: yes, these four fields uniquely identify a selection within a fixture.**

Every one of the 93 distinct `market_id` values in the sample data uses a consistent
pattern of these four fields, and no two selections within a fixture share the same
four-tuple.

### Patterns by market type

| Market type | `market_id` | `normalized_selection` | `selection_line` | `points` |
|---|---|---|---|---|
| Moneyline | `moneyline` | team slug (`houston_rockets`) | `null` | `null` |
| 3-way moneyline | `moneyline_3-way` | team slug or `draw` | `null` | `null` |
| Spread | `point_spread` | team slug | `null` | signed (`-2.5`) |
| Game total | `total_points` | `""` (empty) | `over` / `under` | `217.5` |
| Team total | `team_total` | team slug | `over` / `under` | `103.5` |
| Player prop | `player_points` etc. | player slug (`paolo_banchero`) | `over` / `under` | `25.5` |
| Player DD/TD | `player_double_double` | player slug | `over` / `under` | `0.5` |
| Odd/even | `total_points_odd_even` | `odd` / `even` | `null` | `null` |
| Team odd/even | `team_total_odd_even` | team slug | `odd` / `even` | `null` |
| Race to N | `race_to_5_points` etc. | team slug | `null` | `null` |
| First basket | `first_basket` | player slug | `null` | `null` |
| H2H moneyline | `player_points_h2h_moneyline` | selected player slug | `null` | `null` |
| H2H spread | `player_points_h2h_spread` | selected player slug | `null` | signed |
| Combo | `player_points_combo_` | joined slugs (`a_+_b`) | `over` / `under` | threshold |
| Each/Either | `player_points_each_` | joined slugs | `over` / `under` | threshold |

Half and quarter variants (e.g. `1st_half_point_spread`, `1st_quarter_moneyline`) follow
the same patterns as their full-game equivalents — the period prefix is baked into the
`market_id`.

### How `normalized_selection` is formed

- Team-scoped: lowercase underscore-joined team name (`phoenix_suns`)
- Player-scoped: lowercase underscore-joined player name; trailing underscore for
  suffixes like Jr. (`wendell_carter_jr_`)
- Multi-player: slugs joined with `_+_` (`desmond_bane_+_dillon_brooks`)
- Game totals / both-teams totals: empty string `""`
- Odd/even (game-level): `odd` / `even`

### How `selection_line` is used

- `null` — moneyline, spreads, race-to, first basket, H2H moneyline, most-X-player
- `over` / `under` — all totals, all player props, DD/TD
- `odd` / `even` — odd/even markets only

### How `points` is used

- `null` — moneyline, race-to, first basket, odd/even, most-X-player
- Signed decimal — spreads (`-2.5` for favorite, `+2.5` for underdog)
- Unsigned decimal — totals and player props (`217.5`, `25.5`)
- `0.5` — double-double and triple-double (achievement threshold)

### Other Optic fields of interest

`grouping_key` pairs the two sides of a line (e.g. `default:217.5` groups Over/Under
217.5) but is fully derivable from the four classification fields.  `id` is a composite
key (`{fixture}:{market_id}:{slug}`), also derivable.

### Implications for our pipeline

Our current `category` values need renaming to match Optic `market_id`:

| Ours | Optic |
|---|---|
| `spread` | `point_spread` |
| `game_total` | `total_points` |
| `player_threes` | `player_made_threes` |
| `1h_spread` | `1st_half_point_spread` |
| `1h_total` | `1st_half_total_points` |
| `1h_moneyline` | `1st_half_moneyline` |

Categories that already match: `moneyline`, `team_total`, `player_points`,
`player_assists`, `player_rebounds`, `player_blocks`, `player_steals`,
`player_double_double`, `player_triple_double`.

We currently embed over/under in `sides[].team` rather than in a separate
`selection_line` field — this will need extracting.  `line` maps directly to `points`
(rename only, values already match).

## Game key limitations

Our `GameKey` is `(date, away, home)` — a date string and two team abbreviations.
This is sufficient for NBA but too narrow for multi-sport use.  Comparing against
the Optic fixture-level fields (`start_date`, `home_competitors`, `away_competitors`,
`sport`, `league`), three things are missing:

1. **Sport** — different sports could have teams with colliding abbreviations on the
   same date.
2. **League** — even within a sport (e.g. basketball: NBA vs EuroLeague, or soccer
   with dozens of leagues).  Optic carries both `sport.id` and `league.id`.
3. **Time** — our date is day-granularity.  Optic uses a full UTC timestamp
   (`"2026-02-21T22:00:00Z"`).  This matters for sports with doubleheaders (MLB) or
   tournaments where the same two teams could meet twice in a day.

No action needed now — the current key is fine for NBA-only operation.
