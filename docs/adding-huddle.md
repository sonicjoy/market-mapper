# Adding Huddle Support — feasibility assessment

Huddle is a **pricing supplier** that augments OpticOdds, *not* an exchange
we trade on like Kalshi or crypto.com.  So mapping it serves the same role
Optic does: its prices attach alongside Optic on the canonical row to enrich
fair-value inputs, rather than gating a trade.

This doc assesses building a **deterministic** Huddle→Optic mapper in this
repo's style (config-driven, `MatchKey`-based), as an alternative to the
existing AI-produced `huddle_canonical_mapping` table (built by Victor).
Specifically interested in **World Cup** markets.

## Scope of the assessment (probed 2026-06-07)

All three tables live in `marketmaking-test.huddle_us` (BigQuery).  Probed
ad hoc with `bq`; queries kept under 5 GB.

| Table | Rows | Size | Partition / cluster |
|---|---|---|---|
| `event_mapping` | 2,072 | 1.8 MB | none / cluster `eventId,competitionId,sportId` |
| `markets` | 30.0 M | 16.7 GB | DAY on `ingestionTimestamp` / cluster `eventId,marketId,sportId` |
| `huddle_canonical_mapping` | 5,928 | 2.6 MB | none (Victor's AI output) |

`sportName` is null throughout `event_mapping`; competitions are bare UUIDs.
`markets` is the live odds feed (many price snapshots per selection over
time — the large per-`marketCode` row counts are snapshots, not distinct
markets).  Constrain `markets` queries by `eventId` (clustering) plus a
recent `ingestionTimestamp` to stay cheap.

Huddle covers MLB, WNBA, NHL, Euroleague basketball, a large tennis /
table-tennis book, plus soccer.

## Headline

**Yes, practical — and *cleaner* than Kalshi on both axes that matter.**
Huddle slots into the "just another specialised exchange" model the
crypto.com work established: a BQ-fed input file → a
`mappers/exchanges/huddle.py` mapper → a per-league `HuddleConfig` → a
`huddle_*` stamp block on `CanonicalRow`.  The crypto.com integration
(`docs/adding-crypto.md`) is a precise template.  Two things make it
*easier* than the existing sources:

1. **Exact event join.**  Huddle and Optic share the Sportradar match id
   (Huddle's `betradar.event.extId` == Optic's `source_ids.sportradar_id`),
   verified 4/4 on the WC finals — so fixture matching is an integer join,
   not the name+date matching every other source relies on.
2. **Explicit numeric line.**  The handicap/total line is a field
   (`marketTypeParams.LINE`), so there is no ticker-suffix decoding or
   per-series `line_offset` to reverse-engineer.

The one real caveat is **WC-finals data thinness right now**, not any
structural blocker.

## The market/selection vocabulary is ideal for a config-driven map

This is the strongest point.  The `markets` feed exposes **clean enums**,
and the line is an explicit numeric field:

- `marketCode` — `RESULT`, `GOAL_HANDICAP`, `GOAL_OVER_UNDER`,
  `HALF_RESULT`, `BOTH_TEAMS_TO_SCORE`, `TEAM_GOAL_OVER_UNDER`,
  `CORNER_OVER_UNDER`, … (~40 distinct soccer codes seen on WC + friendly
  events).
- `selectionCode` — `HOME` / `AWAY` / `DRAW` / `OVER` / `UNDER` / `YES` /
  `NO`.
- **line** lives in `marketTypeParams.LINE` as a clean float
  (e.g. `{"LINE": -2.5, "SELECTIONS": 2.0}`; `SELECTIONS` is the
  2-way/3-way count).  `selectionTypeParams` is empty `{}` for game lines.
- `decimalValue` is the odds; `probability` is also carried.

That is the `HuddleConfig.table_types` shape in `mappers/exchanges/huddle.py`
— a flat `marketCode → MarketType` dict plus side dispatch on
`selectionCode`.  (Kalshi has since moved off its old `table_types`: its market
type now comes from the typed scope in `mappers/vocab/kalshi_scopes.py`.)  **Cleaner than Kalshi**: no ticker-suffix line decoding
and no per-series `line_offset` reverse-engineering (the `N−0.5` headache
from the WC spread/total work simply does not exist — the line is a field,
not encoded in an identifier).

A few mappable codes map straight onto types the WC config already carries
(`RESULT`→`MONEYLINE_3WAY`, `GOAL_OVER_UNDER`→`GAME_TOTAL`,
`GOAL_HANDICAP`→`POINT_SPREAD`); the long tail (`CORRECT_SCORE`, combos like
`RESULT_AND_GOAL_OVER_UNDER`, `NEXT_GOAL_TIME`, the `*_EXACT_EXHAUSTIVE`
family, player props) has no clean Optic target and stays unmapped: a code
that is not in `table_types` (or is in `HuddleConfig.ignored_codes`) maps
nothing. No tip `ignore` rows. `HuddleConfig` is still built from the
retiring tip today; that is migration debt (see `CLAUDE.md`).  The full
crosswalk and its gotchas are in **"Market crosswalk (open item 1)"** below.

> **JSON unwrap gotcha.**  `marketTypeParams` (and `selectionTypeParams`,
> and `mappingsPerFeed`) are **double-encoded** — a JSON-typed column whose
> value is a *string* of JSON.  `JSON_VALUE(marketTypeParams,"$.LINE")`
> returns NULL; you must unwrap the inner string first:
> `JSON_VALUE(PARSE_JSON(JSON_VALUE(marketTypeParams)),"$.LINE")`.  The
> fetcher's flatten step must do the same unwrap.

## Event matching: an EXACT Sportradar-ID join (verified 2026-06-07)

This is the decisive finding, and it is **better than Kalshi**.  Where the
other exchanges match Optic on `MatchKey(date, home_abbrev, away_abbrev)`
(`mappers/exchanges/optic.py` `load_fixtures`, with `source_ids` only an
after-the-fact cross-check), Huddle can join to Optic on a **shared
Sportradar id** — no name resolution, no date fuzz.

Two halves, both confirmed:

- **Optic exposes the Sportradar id** on `/v3/fixtures`, `/v3/teams`, and
  `/v3/players` when called with `include_sportradar_id=true`.  It lands in
  `source_ids.sportradar_id` as a prefixed string — `sr:fixture:66456904`
  for soccer fixtures, `sr:match:52864807` for NBA, `sr:team:3423`,
  `sr:player:1946814`.  The prefix varies by sport/entity; the **trailing
  integer** is the id.  (Note: the pipeline's current Optic fetch does not
  request this flag — `fetch/optic.py` would need
  `include_sportradar_id=true` added to the fixtures params.)
- **Huddle carries the same id.**  `event_mapping.mappingsPerFeed` is a
  (double-encoded) JSON blob of cross-feed event IDs —  `runningball`,
  `betgenius`, **`betradar` (= Sportradar)**, `lsports`, `statsperform`.
  Huddle's `betradar.event.extId` is the bare Sportradar match integer.

Cross-checked all 4 WC-finals fixtures Huddle carries against Optic's 72
`fifa_-_world_cup` fixtures — **4/4 exact match** on the numeric id:

| Huddle `eventName` | betradar `extId` | Optic fixture (`sr:fixture:<n>`) |
|---|---|---|
| Mexico v South Africa | `66456904` | Mexico v South Africa |
| Korea Republic v Czech Republic | `66456906` | Korea Republic v **Czechia** |
| Mexico v Korea Republic | `66456908` | Mexico v Korea Republic |
| Czech Republic v South Africa | `66456910` | **Czechia** v South Africa |

The "Czech Republic" (Huddle) vs "Czechia" (Optic) row is the case for the
id join in one line: a **name match would fail there, the id join does
not.**  This removes the country-alias table from the event-matching path
entirely — Huddle's FIFA-style names (`Korea Republic`, `Congo DR`,
`Virgin Islands, British`) never have to be reconciled to Optic spellings
to *find the fixture*.

Consequences for the build:

- The Huddle mapper can resolve fixture → Optic by stripping
  `sr:(fixture|match):` off Optic's `source_ids.sportradar_id` and matching
  the integer to Huddle's `betradar.event.extId`.  This is the cleanest
  event join of any source in the repo.
- An alias table is still wanted for **side resolution** (which physical
  team is `HOME`/`AWAY`), and Optic's `/v3/teams?include_sportradar_id`
  gives a Sportradar **team** id (`sr:team:<n>`) that Huddle's
  `mappingsPerFeed` likely also carries — so even sides can be id-resolved
  rather than name-resolved.  To confirm: check whether Huddle's blob has a
  per-competitor betradar id (the probed events only had the event-level
  one extracted).
- **Player props** get the same gift: Optic `/v3/players?include_sportradar_id`
  returns `sr:player:<n>`, and Huddle props carry `PLAYER_ID` plus
  (probably) a betradar player id — a deterministic player join later,
  without the fuzzy name-normalisation the crypto player-prop plan needs.
- Huddle rows are still **novel** in the pipeline's sense (Optic's
  `source_ids` has no `huddle` key — the Sportradar id is a *third-party*
  join, not Optic vouching for Huddle), but the join itself is exact.

To read the Huddle blob in SQL it is double-encoded — parse the inner
string:

```sql
JSON_EXTRACT_SCALAR(PARSE_JSON(JSON_VALUE(mappingsPerFeed)),
                    "$.betradar.event.extId")
```

## Market crosswalk (open item 1)

Open item 1 is building and validating the
`Huddle marketCode → MarketType → Optic market id` crosswalk for soccer,
plus the explicit ignore set.  Both universes are enumerated (2026-06-07):

- **Huddle** — ~95 distinct soccer `marketCode`s (over the finals +
  friendlies competitions; query below), each with its `selectionCode`s and
  (once unwrapped) `marketTypeParams.LINE` / `SELECTIONS`.
- **Optic** — `/v3/markets?league=fifa_-_world_cup` returns **185** market
  ids (**106** full-match, the rest `1st_half_*` / `2nd_half_*` / `1st_10_*`).
  The `id` field (e.g. `total_goals`, `asian_handicap`, `both_teams_to_score`)
  is exactly what `OpticConfig.table_types` keys on.

The WC `OpticConfig.table_types` today maps only four: `moneyline`,
`asian_handicap`, `total_goals`, `player_goals` (`mappers/leagues/world_cup.py`).

### Proposed core crosswalk

| Huddle `marketCode` | Optic market id | `MarketType` | Notes |
|---|---|---|---|
| `RESULT` (H/D/A) | `moneyline` | `MONEYLINE_3WAY` | already mapped; Optic soccer `moneyline` carries Draw (confirmed in `adding-world-cup-2026.md`) |
| `GOAL_OVER_UNDER` | `total_goals` | `GAME_TOTAL` | already mapped |
| `GOAL_HANDICAP` (`SELECTIONS`=2) | `asian_handicap` | `POINT_SPREAD` | already mapped — **split, see gotcha 1** |
| `BOTH_TEAMS_TO_SCORE` | `both_teams_to_score` | BTTS (new `YES_NO`) | new type (WC P2) |
| `HALF_RESULT` | `1st_half_moneyline_3-way` | `FIRST_HALF_WINNER_3WAY` | type exists |
| `HALF_GOAL_OVER_UNDER` | `1st_half_total_goals` | `FIRST_HALF_TOTAL` | type exists |
| `HALF_GOAL_HANDICAP` (`SELECTIONS`=2) | `1st_half_asian_handicap` | `FIRST_HALF_POINT_SPREAD` | type exists; same split |
| `TEAM_GOAL_OVER_UNDER` | `team_total_goals` | `TEAM_TOTAL` | type exists |
| `DOUBLE_CHANCE` / `DRAW_NO_BET` / `HALF_TIME_FULL_TIME` / `CORNER_OVER_UNDER` / `CARD_OVER_UNDER` | `double_chance` / `draw_no_bet` / `halftime_fulltime` / `total_corners` / `total_cards` | — | new MarketTypes; optional later widening |

### Gotchas the data forces (the real content of "confirm against Optic")

1. **3-way vs 2-way handicap split.**  `GOAL_HANDICAP`, `HALF_GOAL_HANDICAP`
   and `GOAL_MARGIN` carry a `DRAW` selection in *some* rows — those are
   *European* 3-way handicaps (`marketTypeParams.SELECTIONS = 3`), which map
   to Optic `goal_spread_3-way` (**not** in the config).  Only `SELECTIONS = 2`
   rows are the Asian handicap → `asian_handicap` → `POINT_SPREAD`.  The
   mapper must split on `SELECTIONS` or it will mis-merge the 3-way rows.
2. **Catalogue ≠ per-fixture.**  `/v3/markets` is league-wide *capability*,
   not what's quoted on a given game.  Confirm each chosen market is actually
   quoted on a WC fixture (pull `/v3/fixtures/{id}/odds` or
   `/v3/odds`), and that Optic's **line-sign convention** (home-negative)
   matches Huddle's `LINE`.  This is the one piece of open item 1 not yet
   done — see the cold-agent runbook.
3. **Large benign ignore set.**  Combos (`RESULT_AND_*`,
   `DOUBLE_CHANCE_AND_OVER_UNDER`, `*_+_*`), `CORRECT_SCORE_*`, `GOAL_BANDS`,
   `GOAL_MARGIN`, `*_EXACT_EXHAUSTIVE`, `NEXT_*`, and the in-play
   `*_FROM_NOW` codes have no clean Optic target.  Enumerate them explicitly
   so a *new* Huddle code surfaces loudly rather than being silently dropped.
4. **`*_SUPER_SUB` player variants.**  Many `PLAYER_*` codes appear twice,
   once with a `_SUPER_SUB` suffix (substitute-player variant).  Decide
   whether they collapse to the same `MarketType` or are ignored.
5. **Player props are a separate phase.**  Huddle's prop set is rich but
   threshold-style Yes/No (`PLAYER_*_MILESTONE`, `PLAYER_ANYTIME_GOALSCORER`)
   — the same shape the crypto soccer-props finding flagged (the threshold
   is baked into the `marketCode`, not in a line field).  Optic has the
   `player_*` / `anytime_goal_scorer` counterparts.  Defer, like the crypto
   player-prop plan.

## WC-finals coverage is currently thin (the real caveat)

`event_mapping` spans 2026-06-03 → 2026-06-21.  Within soccer:

- The actual **WC 2026 finals = competition `315ad098-9257-47c8-9cfc-cfbf3ac4791f`**
  (Mexico v South Africa 2026-06-11 19:00 — matches the probe fixture in
  `adding-world-cup-2026.md`).  It has only **4 fixtures** and **no markets
  loaded yet** (the finals are only just entering Huddle's horizon).
- The 72-event competition `27433282-3a1a-45df-a528-e2af27d1624c` is the
  **June friendlies / qualifiers** (Morocco v Norway, France v Ivory Coast,
  Iraq v Venezuela, Gibraltar v British Virgin Islands) — and it *does*
  carry full market depth.
- Victor's AI table lumps **30 events under `"fifa - world cup"`** drawn
  from at least three different competition UUIDs (finals `315ad098` = 4
  fixtures, `f2b659ec` "Argentina v Algeria", plus friendlies).  That
  conflation is itself an argument for a deterministic, **`competitionId`-
  keyed** build — map the finals competition exactly and don't silently
  absorb friendlies.

Practical consequence: build and test against the **friendlies competition**
(full market depth) now, exactly as the crypto WC work built against the
pre-restart dump, and let the finals fixtures flow once Optic + Huddle
markets populate.

### Scope decision: friendlies are a SEPARATE standalone league (2026-06-07)

Decided to map the friendlies competition too, not just the finals — and to
do it as its **own ordinary league module**, not as a second `league_id`
bolted onto the World Cup config.  The earlier worry was that Huddle's
single "friendlies" bucket (Haiti v New Zealand, Maldives v Pakistan,
Lesotho v Kenya, …) would fan out across many Optic confederation leagues
and break the pipeline's one-league-per-module model.  **It does not** —
Optic dumps essentially the whole June international window into one league,
`international_-_friendlies`.  Measured via the Sportradar-id join: **70 of
72** Huddle friendlies match `international_-_friendlies` fixtures (Jun
1–12, 99 fixtures) exactly; the 2 strays (Maldives v Bangladesh, Kuwait v
Oman) are likely in an AFC-qualifier sub-league or carry no Optic sr id —
handle as a documented extend/ignore, not a blocker.

**Friendlies differ from the finals on all three platforms by a clean
identifier, so they ARE a distinct league — clone the WC module and swap:**

| | World Cup | Friendlies |
|---|---|---|
| Kalshi prefix | `KXWC` | `KXINTLFRIENDLY` |
| Optic `league_id` | `fifa_-_world_cup` | `international_-_friendlies` |
| Huddle `competitionId` | finals `315ad098…` | June window `27433282…` |

Confirmed 2026-06-07 that Kalshi carries friendlies under their own prefix
(`KXINTLFRIENDLYGAME` / `SPREAD` / `TOTAL` — 117 / 60 / 60 open markets) and
that `KXINTLFRIENDLYGAME` is **structurally identical** to `KXWCGAME`: a
3-way with an explicit `-TIE` leg, home-first ticker (`26JUN10BOLDZA` =
Bolivia home, Algeria away), and the same `N−0.5` spread/total suffix
convention.  (Historical: the mapper no longer reads ticker legs or suffixes;
Kalshi sides come from `custom_strike` via `strike_side` and lines from
`strike_type` + `floor_strike` via `_typed_line`, both in
`mappers/exchanges/kalshi.py`.)  So the friendlies module is `world_cup.py` with the three
identifiers swapped and the market types pruned to what friendlies quote
(GAME/SPREAD/TOTAL certain; check 1H/BTTS/GOAL before adding).

This **dissolves** the "World Cup needs two Optic leagues" problem
entirely.  There is **no `OpticConfig.league_id` tuple change, no
shared-crosswalk extraction, and no making `KALSHI` optional** — friendlies
have full Kalshi coverage.  It is the same clone relationship `world_cup.py`
already has to `epl.py`, so the only duplication is the normal,
already-accepted league-clone duplication.  It also matches the doc's own
anti-conflation point below (don't lump finals and friendlies under one
`league` label, the way Victor's AI table does): a separate module gives
friendlies their own `league` value.

Friendlies are a *rolling* window: each international break lands in
whatever Optic league is current, so "friendlies coverage" long-term means
tracking that `league_id`, not a fixed one.  For this project the June
window is `international_-_friendlies`.

### What Victor's AI table currently produces (for reference)

`huddle_canonical_mapping` breakdown (snapshots 2026-06-05 → 06-07):

| sport | league | rows | events | optic_games | avg conf |
|---|---|---:|---:|---:|---:|
| baseball | mlb | 3,861 | 45 | 45 | 99.7 |
| soccer | fifa - world cup | 874 | 30 | 30 | 98.3 |
| soccer | international - friendlies | 642 | 39 | 39 | 98.3 |
| basketball | nba | 433 | 2 | 2 | 99.3 |
| tennis | wta | 50 | 25 | 25 | 100 |
| hockey | nhl | 44 | 2 | 2 | 100 |
| tennis | atp | 24 | 12 | 12 | 100 |

The output rows carry confidence tiers and `selection_rule` strings
(`ml_home`, `spread_away+derived_side`, …) and `event_orientation` —
i.e. a fuzzy name/market matcher, not the exact deterministic join this
repo's pipeline produces.

## Verdict

Architecturally clean and well-precedented (crypto.com is the template),
and easier than the precedent on both the event side (exact Sportradar-id
join, verified 4/4 on WC finals) and the market side (explicit numeric
line).  Rows are still **novel** in the pipeline's sense — Optic's
`source_ids` has no `huddle` key — but the third-party Sportradar id makes
the join exact rather than fuzzy.  Business intent differs from Kalshi:
Huddle is a pricing supplier that *augments* Optic, so its prices attach
alongside Optic on the canonical row rather than gating a trade.

A from-scratch deterministic build would add, mirroring crypto.com:

1. a BQ fetcher (`fetch/huddle.py`, `ro_query` — Huddle is BQ-fed like
   crypto, not an HTTP API), pulling `event_mapping` (incl. the
   `betradar.event.extId`) + `markets`;
2. `include_sportradar_id=true` on the Optic fixtures fetch
   (`fetch/optic.py`), so Optic fixtures carry `source_ids.sportradar_id`;
3. a mapper (`mappers/exchanges/huddle.py`) joining fixture → Optic on the
   Sportradar integer and turning `markets` rows into `CanonicalRow`s,
   gated to the mappable `marketCode` subset;
4. a `HuddleConfig` per league module (`marketCode → MarketType`, the
   `competitionId`(s) to include, the `selectionCode` side dispatch);
5. a `huddle_*` stamp block on `CanonicalRow` + serialisation, novel-row
   handling.

### What's resolved vs still to settle

Resolved 2026-06-07:

- **The exact event join works** — Optic's `include_sportradar_id=true`
  gives `source_ids.sportradar_id` and its trailing integer equals Huddle's
  `betradar.event.extId` (4/4 WC finals, including the Czech Republic ↔
  Czechia name divergence the id join sails through).
- **Both market universes enumerated and a core crosswalk drafted** — see
  "Market crosswalk (open item 1)".  The 2-way/3-way handicap split and the
  ignore-set boundary are identified.
- **Scope = finals + friendlies, as two separate league modules** —
  friendlies are a clean standalone clone (`KXINTLFRIENDLY` /
  `international_-_friendlies` / friendlies competition, 70/72 covered), not
  a second `league_id` on the WC config; Kalshi covers them too, so no
  `OpticConfig`/`KALSHI` changes.  See "Scope decision: friendlies are a
  SEPARATE standalone league".
- **Side resolution is positional and safe** — Huddle and Optic agree on
  home/away on **70/70** matched friendlies (and 4/4 finals): both inherit
  Sportradar's designation via the shared fixture id.  So once a Huddle
  selection is joined to its Optic fixture by sr id, its `HOME`/`AWAY`
  maps directly to that fixture's home/away — no flip handling, no team
  alias table.  (This is structurally safe, not just empirically: we build
  the row from the *joined* fixture's home/away, so position is relative to
  the fixture we matched, not a guess.)
- **MarketTypes confirmed to exist** — `MONEYLINE_3WAY`, `POINT_SPREAD`,
  `GAME_TOTAL`, `FIRST_HALF_WINNER_3WAY`, `FIRST_HALF_TOTAL`,
  `FIRST_HALF_POINT_SPREAD`, `TEAM_TOTAL` are all in
  `mappers/market_types.py`.  BTTS is the only new `MarketType` the
  crosswalk needs (game-scoped `YES_NO`), per WC P2.
- **Source-id stamp = a single `selectionId`** (verified 2026-06-07
  against the friendlies `markets` feed) — **one** functional key, *not*
  the crypto.com two-key shape.  This was the open "what id ties a mapped
  row back to the price feed" question, and it lands the opposite way from
  crypto.  crypto needs *two* keys (`security_id` **+** `symbol`) only
  because its catalogue (`SecurityList`, carrying `eventCode`) is a
  different message from its price stream (`SecurityStatus`/`MarketData`,
  carrying `SecurityID`+`Symbol`) — the mapping must stamp the id that
  survives into the *price* messages.  Huddle has **no such split**: the
  price snapshots live in the same `markets` rows that carry `selectionId`,
  so the price feed is addressed by exactly the id the mapping stamps.
  Measured on one friendlies event (3,028 selections, ~5 snapshots each
  over 7h): `selectionId` is **immutable** — across all its snapshots a
  given `selectionId` never changed `marketCode`, `selectionCode`, `LINE`,
  or `inPlay` (0 of 3,028 drifted on any axis), and `selectionId` alone was
  as unique as `(eventId, marketId, selectionId)` within the event.  So the
  functional Huddle key is `selectionId`; everything else
  (`marketCode`/`selectionCode`/`LINE`/label/`marketId`) is **provenance**,
  carried for the same novelty reason crypto carries `selection_name`/
  `symbol` (no Optic row to lean on), not as a second join key.  Two
  residuals, neither a blocker: (a) cross-*event* uniqueness is only proven
  *within* one event — 5 of 6 probed friendlies had no markets loaded yet
  (the documented thinness) — so key on **`(eventId, selectionId)`** as
  free insurance (`eventId` already comes from the Sportradar join);
  (b) pre-match and in-play get distinct `selectionId`s (0 selections
  spanned both), which aligns with the `inPlay = false` dedup — stamp the
  pre-match id and the in-play ids drop out for free.

Still to settle before building:

1. **Optic line-sign / per-fixture confirmation** (the only unfinished
   probe) — confirm the drafted crosswalk markets are actually quoted on a
   live fixture and that Optic's line sign matches Huddle's `LINE`.  Do it
   on a **friendlies** fixture (built first; the finals competition's
   markets are still thin).  This is step 1 of the runbook below; cheap,
   needs live odds.  Only gates the spread/total chunk — moneyline has no
   line, so the moneyline skeleton can land before this is closed.

## Build progress (2026-06-07, branch `mm-810-add-world-cup-2026-mappings`)

The friendlies-first moneyline skeleton is underway, small commits,
pipeline green at each step (`mappers/CLAUDE.md`).  Done so far:

- **Step 1 — Optic Sportradar id surfaced** (`8aee88e`).  `Fixture`
  gained `sportradar_id` (bare integer, `sr:(fixture|match):` stripped).
  **Correction to the plan below:** `include_sportradar_id=true` only
  populates `source_ids` on **`/fixtures/active`**, NOT on
  `/fixtures/odds` — and the record we persist
  (`optic_fixtures_odds.jsonl`) is built from the *odds* endpoint, which
  carries no fixture-level `source_ids` even with the flag set (deep-
  scanned 2026-06-07).  So the flag alone does nothing; `fetch/optic.py`
  `main()` carries the id over from the active-list fixture onto the
  persisted record.  Verified end to end: MEX v RSA →
  `sportradar_id="66456904"` (matches the 4/4 finals finding).  Existing
  league output byte-identical (`--json` checksum over a
  world_cup/nba/ncaab subset).
- **Step 2 — `fetch/huddle.py` market-set fetcher** (`504ce17`).  Pulls
  the soccer selection universe from `event_mapping` ⋈ `markets`, scoped
  by the finals + friendlies `competitionId`s, one deduped pre-match
  record per selection.  Key decisions made building it:
  - **Tables: `event_mapping` + `markets` only.**  `huddle_canonical_
    mapping` is Victor's AI output and is the thing this build is an
    *alternative* to — it is a cross-check for our output, never an
    input.
  - **Mappings, not prices.**  `markets` is a price stream, but the
    mapping-relevant identity of a `selectionId` is immutable across its
    snapshots, so we keep ONE snapshot per selection and carry **no
    odds** (the trading system prices by `selectionId` separately).
  - **SQL does the work** (join + latest-per-selection dedup + the
    double-encoded `marketTypeParams`/`mappingsPerFeed` unwrap) because
    the source is tabular — the structural/interpretive split of
    `docs/adding-crypto.md` holds, just with more in SQL and the
    interpretation still in the mapper.
  - **Window = 12h** (cron), configurable.  Sizing is purely "don't drop
    a published fixture between hourly runs", driven by the re-snapshot
    gap, not price freshness: measured p50 20min / p95 ~3.3h / p99 ~7.5h
    / max ~30h, so 12h sits above p99 with margin; the ~30h tail is left
    to the next run (re-capture is idempotent).  Huddle's own publish
    lead is typically 24–47h before kickoff (the upstream limit on how
    early we can map).  12h scans ~70MB.
  - Verified on a 6h dev window: 7058 selections / 8 events, 0 dedup
    collisions, RESULT trio (HOME/DRAW/AWAY, `SELECTIONS=3`),
    `GOAL_HANDICAP` carrying both `SELECTIONS` 2.0 and 3.0 (the split,
    gotcha 1), clean `GOAL_OVER_UNDER` 0.5–6.5 ladder.
- **Step 3a — `huddle_*` stamp fields on `CanonicalRow`** (`dca3481`).
  Six fields mirroring the `crypto_*` block: `huddle_selection_id` (the
  functional source-id stamp) plus `event_id` / `market_id` /
  `market_code` / `selection_code` / `betradar_extid` provenance.
  Additive; output byte-identical.

**Next:** step 3b — `mappers/exchanges/huddle.py`: `HuddleConfig`
dataclass + `Selection` model + `parse_selection` + `build_rows`
(moneyline: `RESULT` → `MONEYLINE_3WAY`, `HOME`/`AWAY`/`DRAW` side
dispatch, no line) + unit tests.  Then step 4 (clone `world_cup.py` →
`international_friendlies.py`, `HUDDLE` field on `LeagueConfig`, register
the league) and step 5 (pipeline wiring: the `{sr_int: Fixture}` index,
sr-id match, merge by `row_key`, serialise, novel-row handling).  The
Optic line-sign probe (open item 1) still gates only the
spread/total chunk, not the moneyline skeleton.

## Next steps for a cold agent

You are picking this up with no prior context.  Read this doc top-to-bottom
first, then `docs/adding-crypto.md` (the structural template) and
`mappers/leagues/world_cup.py` (the WC `OpticConfig`/`KalshiConfig` you are
mirroring).  See "Build progress" above for what already exists (steps 1,
2 and 3a are done — `fetch/optic.py` sr-id, `fetch/huddle.py`, and the
`huddle_*` stamp fields); the steps below are the original from-scratch
plan, of which 3b onward remain.

**Environment / access (verified working 2026-06-07):**

- BQ: `huddle_us` lives in project `marketmaking-test`.  Use `bq query
  --project_id=marketmaking-test --use_legacy_sql=false`.  Keep queries
  under 5 GB; constrain `markets` by `eventId` + a recent `ingestionTimestamp`.
- Optic key: `gcloud secrets versions access latest
  --secret=opticodds_access_key --project=marketmaking-test`; base URL
  `https://api.opticodds.com/api/v3/`; WC league id `fifa_-_world_cup`.
  Add `&include_sportradar_id=true` to get `source_ids.sportradar_id`.

**Finish open item 1 (the one unfinished probe):**

1. Pull live odds for one friendlies fixture (built first; finals are thin)
   and list the `market`/`market_id` values actually quoted
   (`/v3/fixtures/active` for an id, then the odds endpoint).  Confirm each
   crosswalk row's Optic market id appears.
2. For `asian_handicap` / `total_goals`, compare Optic's line + sign to
   Huddle's `marketTypeParams.LINE` on the **same** Sportradar-joined
   fixture — confirm home-negative agreement, no `line_offset` needed.
3. Re-query the Huddle universe to lock the crosswalk + ignore set:
   ```sql
   WITH ev AS (SELECT eventId FROM huddle_us.event_mapping
               WHERE competitionId IN ("315ad098-9257-47c8-9cfc-cfbf3ac4791f",
                                       "27433282-3a1a-45df-a528-e2af27d1624c"))
   SELECT m.marketCode,
          STRING_AGG(DISTINCT m.selectionCode ORDER BY m.selectionCode) sels,
          STRING_AGG(DISTINCT JSON_VALUE(PARSE_JSON(JSON_VALUE(m.marketTypeParams)),
                              "$.SELECTIONS")) selections_param,
          COUNT(*) n
   FROM huddle_us.markets m JOIN ev USING(eventId)
   WHERE m.ingestionTimestamp >= "2026-06-05"
   GROUP BY 1 ORDER BY 1
   ```

**How the sr-id join becomes a mergeable row (the key architectural point).**
The repo merges sources onto Optic by `row_key` (built from
`MatchKey(date, home_abbrev, away_abbrev)` + `MarketType` + line + side).
The Sportradar join does **not** bypass this — it *feeds* it: a Huddle
selection → its `betradar.event.extId` → the Optic fixture carrying that
`sr id` → **adopt that fixture's `MatchKey` and canonical home/away
abbreviations** → build the `CanonicalRow` with those → it collides with
Optic's row by `row_key`.  So the sr id replaces the *fixture-finding*
step (name+date) only; everything downstream is the normal row build.
Build an index `{sr_int: Optic Fixture}` at load time (alongside the
existing `{MatchKey: Fixture}`) and look Huddle up in it.

**Phasing (friendlies first, moneyline-first within it).**  Build order is
two chunks on the friendlies league, then a clone onto the World Cup:

1. **Friendlies moneyline** — the walking skeleton.  `RESULT` →
   `MONEYLINE_3WAY` only: 3-way side dispatch, no line, no handicap split.
   This is most of the work, because it builds and proves all the
   scaffolding end to end — fetcher → sr-id join → merge by `row_key` →
   `huddle_*` stamp → serialise, plus novel-row handling.
2. **Friendlies spread + total** — once the skeleton merges, these are just
   crosswalk-dict entries on proven machinery: `GOAL_OVER_UNDER` →
   `GAME_TOTAL` and `GOAL_HANDICAP`(2-way) → `POINT_SPREAD`.  They add only
   `LINE` handling (shared between them) plus, for spread, the 2-way/3-way
   `SELECTIONS` split (gotcha 1) and the Optic line-sign confirm.  If the
   line-sign probe is still open here, lead with total (over/under sign is
   unambiguous) and do spread alongside.  **Do NOT split spread from total
   into separate chunks** — once moneyline proves the pipe they are an hour
   of crosswalk entries, not a milestone each.
3. **World Cup** — drop the same `HuddleConfig` shape onto `world_cup.py`
   once the finals competition has markets loaded (it is thin now).

Everything beyond these three codes — half-markets, team totals, BTTS (new
type), and the optional `double_chance` / `halftime_fulltime` / corners /
cards — is later widening; everything else → ignore set.

**Markets feed is snapshots — dedup and filter.**  `markets` is a price
stream (many rows per selection over time, both pre-match and in-play).
The mapper input must be **one row per selection**: dedup to the latest
`ingestionTimestamp` per `(eventId, marketId, selectionId)` — though
`selectionId` alone is a stable, immutable, globally-sufficient key
(verified 2026-06-07; see the source-id stamp finding above), so
`(eventId, selectionId)` suffices and is kept only as cross-event
insurance — and take **pre-match only** (`inPlay = false`) — which also
drops the in-play `*_FROM_NOW` / `NEXT_*` codes for free (pre-match and
in-play carry distinct `selectionId`s, so this is a clean cut).

**Then build, mirroring crypto.com, small commits, pipeline green at each step**
(follow `docs/adding-crypto.md` and `mappers/CLAUDE.md`):

1. `fetch/optic.py`: add `include_sportradar_id=true` to the fixtures fetch
   params; surface `source_ids.sportradar_id` on the parsed Optic fixture
   (`mappers/exchanges/optic.py` `Fixture` currently drops it — add a field).
   **No `OpticConfig` change** — friendlies are their own league module with
   `league_id = "international_-_friendlies"` (see the scope decision), so
   `league_id` stays a single `str`.  Note `international_-_friendlies` past
   fixtures need `start_date_after` / `start_date_before` params (the
   endpoint defaults to upcoming only).
2. `fetch/huddle.py`: BQ fetcher (`ro_query`), joining `event_mapping`
   (carry `betradar.event.extId`, the unwrapped `mappingsPerFeed`) to
   `markets`, writing `huddle_markets.jsonl` (one deduped pre-match record
   per selection — see "Markets feed is snapshots" above).  Mirror the
   crypto fetcher's "dumb SQL, smart Python" split and empty-window
   handling.  Filter to soccer competitions; `markets` is day-partitioned,
   so bound `ingestionTimestamp` to keep scan cost down.
3. `mappers/exchanges/huddle.py`: `HuddleConfig` dataclass +
   `parse_selection` + `build_rows`.  Event match = Sportradar integer join
   (strip `sr:(fixture|match):`).  Side dispatch on `selectionCode`; line
   from `marketTypeParams.LINE`; handicap split on `SELECTIONS` (gotcha 1).
4. League modules — **friendlies first**.  Add a new
   `LeagueConfig` field `HUDDLE: HuddleConfig | None` (mirroring the
   existing optional `PX`).  Then clone `world_cup.py` →
   `mappers/leagues/international_friendlies.py`: swap the Kalshi prefix to
   `KXINTLFRIENDLY`, the Optic `league_id` to `international_-_friendlies`,
   and add the `HuddleConfig` with the friendlies `competitionId`; register
   the league in `mappers/leagues/__init__.py` (`League` enum +
   `_LEAGUE_SPORT`).  The World-Cup `HuddleConfig` lands on `world_cup.py`
   later, once finals markets load.  Each `HuddleConfig` = the `marketCode →
   MarketType` crosswalk + the `competitionId`(s) + the explicit ignore set.
   Note it is *simpler* than `CryptoConfig`: there is **no period-gate
   constant** — half-markets are distinct `marketCode`s (`HALF_*`), so the
   period is already encoded in the code, not a separate field to gate on.
5. `huddle_*` stamp block on `CanonicalRow` + conditional `huddle`
   serialisation sub-object (mirror the `crypto`/`kalshi` blocks in
   `pipeline.py`); wire the load+merge in `build_pipeline`, gated on
   `league.HUDDLE is not None`.  The **functional key is a single
   `selectionId`** (plus `eventId` as insurance) — *not* crypto's two-key
   `security_id`+`symbol` shape; the readable
   `marketCode`/`selectionCode`/`LINE`/label are **provenance** carried for
   the novelty reason, not join keys (see the source-id stamp finding
   above).  Huddle rows are **novel** — confirm an unmatched Huddle row is
   carried, not dropped.

**Validate** (same method as the crypto WC verification): run against the
**friendlies competition** (full market depth — the finals competition has
no markets loaded yet).  Confirm Huddle rows **merge onto Optic rows by
`row_key`** (agreed), not novel.  With the Sportradar-id event join, an
unexpectedly novel row means a *market/line/side* crosswalk error, not a
fixture miss — so novelty is now a precise crosswalk signal.  Eyeball
orphans for ladder-extension vs genuine mismatch.  Run the `--json`
checksum over a small subset per `mappers/CLAUDE.md` so existing leagues
stay byte-identical.
