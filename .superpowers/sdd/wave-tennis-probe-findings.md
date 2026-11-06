# Tennis rescue probe — Optic ceiling + poly templates + mapping matrix (2026-07-23)

Probe environment: `.venv/bin/python`, no poetry. BQ via the `google-cloud-bigquery` Python
client (`bigquery.Client(project="rs-marketmaking", location="us-east4")`) — the naive
`location="US"` 404s on this table, same gotcha every prior probe hit. Optic API access used
the ADC workaround: `gcloud auth application-default print-access-token` → bearer-authed `GET
secretmanager.googleapis.com/v1/projects/marketmaking-test/secrets/<secret>/versions/latest:access`
→ base64-decode the payload → use as `X-Api-Key` against `api.opticodds.com` directly with
`requests` (bypassing `fetch/optic.py`'s `gcloud secrets versions access` subprocess entirely).
**One correction to the task's stated setup**: `fetch/optic.py`'s own `LEAGUE_SECRET` map
sends ATP/WTA through a *separate* secret, `opticodds_parlay_tennis_access_key` (not the plain
`opticodds_access_key` every other league uses — see `TENNIS_SECRET` in `fetch/optic.py`).
Fetched both from Secret Manager and diffed them: **they are byte-identical today** (same
36-char key), so either works right now, but a future rotation could desync them — a tennis
fetch script should read the tennis-specific secret to stay correct-by-construction. Both
workarounds succeeded on the first attempt — a full, unblocked probe. Read-only throughout: no
source file was modified; all scratch scripts and JSON dumps live under `/tmp/tennis_probe`
(this session's isolated scratchpad), never in the repo tree.

Context: `mappers/leagues/atp.py` / `wta.py` wire only `OpticConfig(table_types={"moneyline":
MONEYLINE})` — the Wave-2 tennis matcher (`.superpowers/sdd/.../2026-07-22-wave2-tennis-matcher.md`,
already shipped) added `tennis_moneyline_rule` + the `"tennis_prefix"` question style +
strict-equality player matching, but scoped it to match-winner only, on the explicit premise
"Optic prices tennis moneyline only." This probe checks that premise against the live API and
finds it's **false** — Optic prices a rich tennis book — and pins the exact poly templates +
Optic structures needed to wire the rescue.

## A. Optic tennis ceiling

### League ids (`GET /leagues/active?sport=tennis`)

| id | name | numerical_id | gender |
|---|---|---|---|
| `atp` | ATP | 20 | men |
| `atp_challenger` | ATP Challenger | 21 | men |
| `atp_doubles` | ATP Doubles | 1360 | men |
| `itf_men` | ITF Men | 604 | men |
| `itf_women` | ITF Women | 605 | women |
| `utr_men` | UTR Men | 606 | men |
| `utr_women` | UTR Women | 607 | women |
| `wta` | WTA | 554 | women |
| `wta_doubles` | WTA Doubles | 1361 | women |

`itf_men`/`itf_women` are the two ids matching the task's "ITF" ask (Optic splits by gender, not
a single combined `itf`; there's no `itf_challenger` or similar). **None of these — including
`itf_men`/`itf_women` — are wired into mmmapper today**: `grep -rn itf mappers/ fetch/` returns
nothing; there is no `League.ITF_MEN`/`ITF_WOMEN`, no `OpticConfig`, no `LEAGUE_SECRET` entry.
Onboarding ITF is a full new-league task (League enum + Kalshi/Optic config + fetch wiring), not
something a market-rules-only tennis rescue touches — scoped out below, noted for later.

Each league's `sport.main_markets` field (a per-sport summary, not the full odds ceiling) lists
only 3: `moneyline`, `game_spread`, `total_games` — this undersells the real breadth by ~20x (see
next section); do not treat `main_markets` as the ceiling.

### Ranked market_id ceiling (live fixtures, 4 ATP + 4 WTA, ~7,700 combined odds rows)

Fetched via the 3-sportsbook-batch pattern from `fetch/optic.py` (`SPORTSBOOK_BATCHES`) against
4 live upcoming ATP fixtures (Kitzbuhel/Estoril, 2026-07-23/24) and 4 live WTA fixtures
(Prague/Hamburg/Palermo, same window) — no fixture was `is_live` yet (all `unplayed`, well
within the pre-match window OpticOdds already prices). **59 distinct market_ids** observed,
ranked by row count:

```
total_games                        1539   game_spread                        1210
1st_set_correct_score                630   1st_set_total_games                 498
player_games_won                     400   2nd_set_correct_score               392
correct_score                        240   set_handicap                        225
player_sets_won                      210   moneyline                           205
1st_set_moneyline                    196   player_to_win_a_set                 158
2nd_set_total_games                  156   2nd_set_moneyline                   145
total_sets                           127   player_double_faults                 98
player_aces                           96   1st_set_game_spread                  94
player_aces_+_double_faults           86   total_tie_breaks                     68
total_aces                            59   total_double_faults                  59
total_aces_+_double_faults            47   most_games_won_3-way                 39
2nd_set_game_spread                   38   1st_set_player_games_won             32
both_players_to_win_a_set             30   1st_set_game_2_correct_score         24
1st_set_game_1_correct_score          24   player_break_points_won              22
1st_set_will_there_be_a_tiebreak      20   any_set_won_to_love                  16
2nd_set_total_games_odd_even          16   1st_set_total_games_odd_even         16
most_break_points_won                 16   1st_set_player_aces                  12
will_there_be_a_tiebreak              10   total_breaks                         10
2nd_set_will_there_be_a_tiebreak       10   1st_set_player_aces_+_double_faults  10
most_break_points_won_3-way            9   most_aces_3-way                       9
most_double_faults_3-way               9   1st_set_player_double_faults          8
total_games_odd_even                   8   1st_set_game_3_correct_score           8
race_to_{10,15,20}_points          6 each   1st_set_total_double_faults           6
1st_set_game_{1,2}_moneyline       6 each   1st_set_game_2_total_points            6
2nd_set_total_aces                     5   1st_set_total_aces                     5
1st_set_game_1_total_points            4   1st_set_game_{2,3}_point_spread     4 each
1st_set_game_3_total_points            2
```

### Selection shapes for the task's target markets

- **`total_games`** (Match O/U — full-match games): `{"name":"Under 22.5","selection":"","selection_line":"under","points":22.5,"team_id":null}` —
  GAME-scoped, `selection`/`normalized_selection` always empty string, `team_id` always null.
  Standard TOTAL/OVER_UNDER shape.
- **`total_sets`**: `{"name":"Over 2.5","selection":"","selection_line":"over","points":2.5,"team_id":null}` — same GAME-scoped TOTAL shape; **line always 2.5** on every best-of-3 fixture sampled
  (never anything else — this is a fixed constant for tour-level tennis, not a variable ladder).
- **`game_spread`** (handicap in **games**, e.g. full-match): `{"name":"Luca Van Assche +0.5","selection":"Luca Van Assche","points":0.5,"team_id":"9F510576E2CD"}` —
  team-keyed SPREAD shape, **`selection` is the player's FULL name** here (this is the
  *Optic*-side field, unrelated to what poly asks — see below, poly has no counterpart to this
  market at all).
- **`set_handicap`** (handicap in **sets**): `{"name":"Pablo Carreno Busta +1.5","selection":"Pablo Carreno Busta","points":1.5,"team_id":"CD791F02C08B"}` —
  same SPREAD shape; **`points` is always exactly ±1.5** across every sample (225/225) — the only
  possible best-of-3 set-margins are 2-0/2-1, so ±1.5 is a fixed constant, not a ladder. This is
  the market poly's `Set Handicap:` question maps to — **not** `game_spread` (different market_id,
  different unit — games vs. sets — despite the similar English name).
- **`1st_set_total_games`/`2nd_set_total_games`** (per-set games total): `{"name":"Over 10.5","selection":"","selection_line":"over","points":10.5,"team_id":null}` —
  identical TOTAL shape to `total_games`, just scoped to one set.
- **`player_games_won`**: `{"name":"Pablo Carreno Busta Under 12.5","selection":"Pablo Carreno Busta","selection_line":"under","points":12.5,"team_id":"CD79...","player_id":"CD79..."}` —
  PLAYER-scoped OVER_UNDER (total games won by one player across the match). **Confirmed 0/9,346
  poly tennis questions ask this** (see section B) — Optic-only, no poly form to rescue.
- **`1st_set_correct_score`/`2nd_set_correct_score`/`correct_score`** (correct SET score, e.g. `6:4` within a
  set, or `2:0`/`2:1` at match level): `{"name":"Pablo Carreno Busta 2:0","selection":"Pablo Carreno Busta","selection_line":"2:0","team_id":"CD79..."}` —
  same team-anchored discrete-scoreline shape the soccer rescue's `correct_score` needed a new
  `Shape`/`SideMode` for (`.superpowers/sdd/wave-rescue-probe-findings.md` section B.1). **Confirmed
  0/9,346 poly tennis questions ask a correct-score form** (no "Exact Score:"/similar template
  anywhere in the atp/wta/itf bridge) — so tennis needs **none** of that machinery; flagged only
  because it's on Optic's ceiling, not poly's.
- **`total_games_odd_even`/`1st_set_total_games_odd_even`**: `{"name":"Odd","selection":"Odd","selection_line":null,"team_id":null,"normalized_selection":"odd"}` —
  a genuinely new binary shape (Odd/Even, not Over/Under, not Yes/No) — no poly counterpart found.
- **`will_there_be_a_tiebreak`/`1st_set_will_there_be_a_tiebreak`**, **`any_set_won_to_love`**,
  **`both_players_to_win_a_set`**: plain literal Yes/No, `team_id` null (GAME-scoped YES_NO,
  same shape soccer's BTTS already uses) — no poly counterpart found.
- **`player_to_win_a_set`**: `{"name":"Pablo Carreno Busta Yes","selection":"Pablo Carreno Busta","selection_line":"yes","team_id":"CD79...","player_id":"CD79..."}` — PLAYER-scoped YES_NO — no poly counterpart.
- **`1st_set_moneyline`/`2nd_set_moneyline`** (per-set winner): `{"name":"Luca Van Assche","selection":"Luca Van Assche","team_id":"9F51...","selection_line":null}` —
  **strictly 2-way**, no Draw option ever observed (unlike soccer's half-winner, which is 3-way) —
  standard team-keyed MONEYLINE shape. This is what poly's `Set K Winner:` form maps to.
- **`most_games_won_3-way`/`most_break_points_won_3-way`/`most_aces_3-way`/`most_double_faults_3-way`**:
  3-way (Team/Team/**Draw**) — genuinely can tie on these stats even though a set itself can't tie.
  No poly counterpart found.

## B. Poly tennis form histogram + templates

Query: `SELECT slug, question, outcome_label, outcome_index, n_outcomes FROM
marketmaking-test.raw_ingestion_us.polymarket_position_token_bridge WHERE
SPLIT(slug,"-")[OFFSET(0)] IN ("atp","wta","itf")` — dry-run **13,461,695 bytes (~12.8 MiB)**,
one query, well within the ~17 MB ceiling every prior probe used. **18,718 rows / 9,346 distinct
questions** (atp 10,382 rows / wta 5,562 / itf 2,774).

Classified every distinct question with a doubles-safe global check (`"/"` anywhere in the
question after stripping the literal `"O/U"` substring — **`"O/U"` itself contains a slash**,
so a naive `"/" in question` check misclassifies every totals question as doubles; strip the
`o/u` literal first, exactly the bug a first-pass classifier would hit).

### Row-level (position) histogram

| form | rows | % of 18,718 | atp | wta | itf |
|---|---|---|---|---|---|
| doubles (drop — slash-joined team names) | 4,922 | 26.3% | 3,424 | 1,498 | 0 |
| **match_total_games** | 3,848 | 20.6% | 2,378 | 1,250 | 220 |
| moneyline (**already wired**) | 3,338 | 17.8% | 1,362 | 850 | 1,126 |
| **set_handicap** | 3,108 | 16.6% | 1,678 | 1,000 | 430 |
| **total_sets** | 1,704 | 9.1% | 902 | 588 | 214 |
| **set_games** (1st/2nd/3rd/4th) | 692 | 3.7% | 194 | 146 | 352 |
| completed match (drop — settled, Yes/No) | 620 | 3.3% | 372 | 178 | 70 |
| **set_winner** (1st/2nd/3rd/4th) | 486 | 2.6% | 72 | 52 | 362 |

Zero rows fell through unclassified (9,346/9,346 distinct questions accounted for). **New
rescuable volume (excluding the already-wired moneyline and the permanently-dropped
doubles/completed buckets) = 9,838 rows / 52.6% of the whole tennis bridge — bigger than the
volume moneyline itself currently recovers.**

`itf` has **zero** doubles rows in the bridge (poly doesn't appear to list ITF doubles at all;
`atp`/`wta` doubles are ~33%/27% of their respective totals).

### B.1 moneyline (already wired) — verbatim

Template: `"<Tournament>: <Player A> vs <Player B>"` — **FULL names** on both sides.

```
Bloomfield Hills: Yunchaokete Bu vs Borna Gojo
Hamburg European Open: Elena Pridankina vs Panna Udvardy
ITF Bali: Taisei Ichikawa vs Jumpei Yamasaki
```
`outcome_label`: the player's full name (e.g. `"Elena Pridankina"`).

### B.2 match_total_games — verbatim (new)

Template: **`"<A> vs. <B>: Match O/U <N>"`** — **NO tournament prefix at all** (unlike
moneyline). **`<A>`/`<B>` are SURNAME-ONLY** (single whitespace-delimited token — confirmed by
word-count histogram: 1,921/1,921 distinct questions have exactly 1 word on each side).

```
Galarneau vs. Ruiz: Match O/U 21.5
Sinner vs. Zverev: Set 1 Games O/U 10.5     <- (set_games, same surname convention, see B.4)
Assche vs. Busta: Match O/U 22.5
```
`outcome_label`: bare `"Over"` / `"Under"` (no line baked in).

**Critical name-form quirk**: `"Assche"` here is the LAST WHITESPACE TOKEN of the full name
`"Luca Van Assche"` — a naive last-word truncation, **not** the true tennis surname (which a
human would call "Van Assche"). Same for `"Busta"` from `"Pablo Carreno Busta"` and `"Fokina"`
from `"Alejandro Davidovich Fokina"` — all confirmed via direct grep of the same tournament's
moneyline questions naming the full player. `normalize_player_name(full_name).split("_")[-1]`
reproduces this convention exactly (hyphenated names like `"Auger-Aliassime"` stay one token
since `normalize_player_name` never splits on hyphens — no live bridge sample containing a
hyphenated surname in this bucket to confirm end-to-end, flagged as a residual unknown, but the
mechanism should hold).

### B.3 total_sets — verbatim (new)

Template: **`"<A> vs. <B>: Total Sets O/U <N>"`** — **FULL names** (unlike match_total_games —
confirmed: 851/851 distinct questions have ≥2 words on both sides, same convention as moneyline).
**Line is always exactly 2.5** across every sample (matches Optic's own constant, section A).

```
Yunchaokete Bu vs. Borna Gojo: Total Sets O/U 2.5
Marta Kostyuk vs. Linda Noskova: Total Sets O/U 2.5
Max Alcala Gurri vs. Lorenzo Angelini: Total Sets O/U 2.5
```
`outcome_label`: **`"Over 2.5"` / `"Under 2.5"`** — the line is baked into the label (unlike
match_total_games' bare `"Over"`/`"Under"`) — see the build_rows implication in section C.

### B.4 set_games — verbatim (new)

Template: **`"<A> vs. <B>: Set <K> Games O/U <N>"`**, K ∈ {1,2,3,4} observed (1: 386 rows, 2:
262, 3: 22, 4: 22 — 3/4 are best-of-5 Grand Slam artifacts, see section C quirks).
**SURNAME-only** (same convention as match_total_games, 346/346 distinct questions 1-word both
sides).

```
Balaji/Goransson vs. Frantzen/Haase: Set 1 Games O/U 8.5   <- doubles variant, dropped globally
Muchova vs. Noskova: Set 1 Games O/U 10.5
Malmkjaer vs. Bartashevich: Set 1 Games O/U 10.5
```
`outcome_label`: bare `"Over"` / `"Under"`.

### B.5 set_handicap — verbatim (new)

Template: **`"Set Handicap: <A> (-N) vs <B> (+N)"`** — a **fixed literal prefix** (not a
tournament name), **SURNAME-only** names (1,546/1,546 distinct questions 1-word both sides),
**N is always exactly 1.5** (matches Optic's `set_handicap` constant, section A).

```
Set Handicap: Gojo (-1.5) vs Bu (+1.5)
Set Handicap: Lajovic (-1.5) vs Assche (+1.5)
Set Handicap: Fokina (-1.5) vs Molcan (+1.5)
```
`outcome_label`: the surname of the outcome side (e.g. `"Gojo"`, `"Bu"`) — same convention as the
team_a/team_b captures, so internally self-consistent.

### B.6 set_winner — verbatim (new)

Template: **`"Set <K> Winner: <A> vs <B>"`**, K ∈ {1,2,3,4} observed (1: 348, 2: 118, 3: 10, 4:
10 — same best-of-5 tail as set_games). **SURNAME-only** (242/242 distinct questions 1-word).

```
Set 1 Winner: Ichikawa vs Yamasaki
Set 1 Winner: Sinner vs Zverev
Set 2 Winner: Muchova vs Noskova
```
`outcome_label`: the winning player's surname (e.g. `"Zverev"`).

The 3rd/4th-set rows are all Grand Slam men's matches (`Sinner`, `Zverev`, `Djokovic`, `Fritz`,
`Cobolli`, `Fery` — recognizable top-20 ATP names from a recent major), confirming best-of-5
context; no current ATP/WTA tour event is best-of-5 outside majors, so these are low-volume,
intermittent, not a steady-state pattern for the two currently-wired leagues (5+5
distinct-question in the 4-set forms combined, vs. 570+ each for Set 1/2).

### Confirmed absent from poly (Optic-only, no rescue possible)

Systematically absent across all 9,346 distinct questions (0 matches for any of): correct/exact
score (match or set level), player games/sets/aces/double-faults/break-points props, odd/even
totals, tiebreak yes/no, "to win a set" yes/no, "most X 3-way" props, game-level handicap
(`game_spread` — poly only ever asks the SET-level `set_handicap`), race-to-points, individual-game
correct-score/moneyline/spread (the `1st_set_game_N_*` family). These make up the bulk of Optic's
59-market_id ceiling but have zero poly-side demand.

## C. Mapping matrix + SideMode/MarketType assessment

Read `mappers/exchanges/polymarket.py` (`SideMode` enum, `build_rows` dispatch, lines 1391–1535)
and `mappers/exchanges/optic.py` (`Shape`-keyed dispatch, lines ~306–390). As with the soccer
rescue, every `Shape`/`SideMode` pair dispatches generically on `(scope, shape)`/`side_mode`
alone — no per-market-id logic — so in principle a new form is "cheap": new `MarketType`
members + new `market_rules` recognizers + config, zero dispatch changes. **Tennis breaks that
pattern in two ways** neither soccer rescue hit: an outcome-label shape mismatch (total_sets)
and a systemic name-granularity mismatch (four of the five new forms).

| Poly form | Optic market_id | Optic shape | SideMode fit | New MarketType | Name granularity | Extra machinery? |
|---|---|---|---|---|---|---|
| moneyline (shipped) | `moneyline` | 2-way team | `TEAM_LABEL` (existing) | `MONEYLINE` (existing) | FULL | none — already shipped |
| total_sets | `total_sets` | over/under + points | `OVER_UNDER` (existing) | **new**: `TOTAL_SETS` (Scope.GAME, Shape.TOTAL) | FULL (agrees with moneyline) | **yes — see C.1** (outcome_label bakes in the line) |
| match_total_games | `total_games` | over/under + points | `OVER_UNDER` (existing) | **new**: `MATCH_TOTAL_GAMES` (Scope.GAME, Shape.TOTAL) | **SURNAME-only** | **yes — see C.2** (name-matching) |
| set_games (1st/2nd) | `1st_set_total_games`/`2nd_set_total_games` | over/under + points | `OVER_UNDER` (existing) | **new**: `FIRST_SET_TOTAL_GAMES`/`SECOND_SET_TOTAL_GAMES` | **SURNAME-only** | **yes — see C.2** |
| set_handicap | `set_handicap` (not `game_spread`!) | team + signed points | `SPREAD_TEAM` (existing) | **new**: `SET_HANDICAP` (Scope.GAME, Shape.SPREAD) | **SURNAME-only** | **yes — see C.2** |
| set_winner (1st/2nd) | `1st_set_moneyline`/`2nd_set_moneyline` | 2-way team, no Draw | `TEAM_LABEL` (existing) | **new**: `FIRST_SET_WINNER`/`SECOND_SET_WINNER` (Scope.GAME, Shape.MONEYLINE) | **SURNAME-only** | **yes — see C.2** |

Unlike soccer's rescue, tennis needs **zero** new `Shape`/`SideMode`/`build_rows` branches for
arity/structure — every form here is a plain 2-outcome TOTAL/SPREAD/MONEYLINE optic's own
`build_rows` (`mappers/exchanges/optic.py`) already handles generically (just add
`table_types` entries). The two real wrinkles are both about **matching**, not shape:

### C.1 total_sets: the outcome_label/line collision in `build_rows`'s OVER_UNDER branch

`build_rows`'s `OVER_UNDER` branch (`mappers/exchanges/polymarket.py` ~line 1497) does:
```python
lab = _normalize(o.outcome_label)
...
if lab == over_lab:      # over_lab = "over"
```
Every existing OVER_UNDER form (MLB/soccer totals, tennis's own `match_total_games`/`set_games`)
has a **bare** `"Over"`/`"Under"` `outcome_label`, so `_normalize("Over")` → `"over"` matches
exactly. `total_sets` is the first form whose label bakes the line in
(`"Over 2.5"`) — `_normalize("Over 2.5")` → `"over 2 5"` (the `.` becomes a space, digits are
kept), which **does not** equal `"over"`, so the exact-match branch would silently drop every
`total_sets` market (return `[]`, the market never wires up — the failure mode is "quietly never
maps" not a crash, so it could ship invisible). Fix is small and backward-compatible: change the
comparison to `lab.startswith(over_lab)` / `startswith(under_lab)` — `"over".startswith("over")`
stays `True` for every existing bare-label form, so this is additive, not a behavior change for
anything already shipped. This is the one line in `build_rows` the whole rescue actually needs
to touch — every other new form is pure config + recognizer.

### C.2 The surname-vs-full-name mismatch — needs new name-matching machinery

The Wave-2 tennis matcher's whole design premise is **strict, exact** player-name equality
(`normalize_player_name(label) == normalize_player_name(fixture_name)`, deliberately not
containment, specifically to stop `"Rune"` wrongly matching `"Holger Rune"`). That premise holds
for `moneyline` and `total_sets` (both use FULL names — confirmed byte-exact against live
Optic competitor names for 24/25 sampled fixtures, section D) but **breaks** for
`match_total_games`/`set_games`/`set_handicap`/`set_winner`, whose poly labels are the **last
whitespace token** of the full name (`"Luca Van Assche"` → `"Assche"`, `"Pablo Carreno Busta"` →
`"Busta"`) — under strict equality, `normalize_player_name("Assche")` (`"assche"`) will never
equal `normalize_player_name("Luca Van Assche")` (`"luca_van_assche"`).

This can't be solved by cloning the existing recognizers with a new `question_style` literal the
way the soccer rescue did, because **the granularity varies per-question-form within the same
league**, not per-league — ATP/WTA need FULL-name exact matching for 2 of 6 forms and
LAST-TOKEN matching for the other 4, all in the same `PolymarketConfig`. `_name_match`/
`_norm_name`'s current signature is keyed off a single `cfg.question_style` for the whole
league, so it can't discriminate by form. Making this work needs one of:

1. A `name_granularity` (or similar) field threaded onto `ParsedMarket` itself (not just
   `PolymarketConfig`), read by `build_rows`/`_match_poly_fixture` instead of `cfg.question_style`
   alone — `full` compares the label as-is; `surname` compares the label against
   `_norm_name(fixture_name, style).rsplit("_", 1)[-1]`. Requires editing `ParsedMarket`'s
   dataclass, `build_rows`'s `TEAM_LABEL`/`SPREAD_TEAM`/`OVER_UNDER`-entity-resolution branches,
   and `_match_poly_fixture`'s signature — a real, if mechanical, cross-cutting change (touches
   the shared dispatch code, not just new recognizers), same tier as soccer's `correct_score`
   design work even though the *shape* machinery here is trivial by comparison.
2. Alternative: a standalone surname index built once per pipeline run per league (surname →
   optic competitor id, raising on a same-tournament collision) that these 4 rules' recognizers
   consult directly, bypassing `_name_match` for team/entity resolution entirely. Avoids
   touching the shared dispatch but duplicates matching logic outside it and needs its own
   collision-handling story — probably the worse trade.

Either way: **this is not a "cheap, config-only" rescue tier** like soccer's 9-form batch — the
4 surname-only forms need one shared new mechanism before any of their `market_rules` can be
written; `moneyline` and `total_sets` remain zero-risk clones of the existing pattern.

**Collision risk from the surname-only design (empirical)**: checked today's live rosters for
duplicate last-token surnames. **ATP (10 matches, 20 players) and WTA (15 matches, 30 players):
zero collisions today.** **ITF (69 men's + 90 women's matches, ~318 players): 8 real collisions**
(`itf_men`: 2 pairs — `Nidunjianzan`, `Breazu`; `itf_women`: 6 pairs — `Wong`, `Akli`, `Koning`,
`Silva`, `Allegre`, `Gomez`). ITF isn't wired into mmmapper at all today (section A), so this
doesn't block the ATP/WTA rescue, but it's a real landmine for whenever ITF gets onboarded — the
surname-only forms would need either a same-day collision guard (drop both candidates rather
than guess) or a smarter resolver, not just the last-token heuristic as-is.

### best-of-3 vs best-of-5 quirk

Every numeric constant on the poly side (`total_sets` line always 2.5, `set_handicap` line
always ±1.5) is a best-of-3 assumption — correct for every ATP/WTA tour event outside the four
majors. The `Set 3/4 Winner` / `Set 3/4 Games O/U` tail (5+5 / 22+22 rows respectively, all
identifiable Grand Slam matches from player names) shows poly **does** ask a best-of-5-shaped
question when the underlying event calls for it, but Optic's odds ceiling for those market_ids
(`3rd_set_total_games`, `3rd_set_moneyline`, etc.) wasn't directly probed live this session (no
Slam is in season — Wimbledon concluded, US Open is next) — flagged as unconfirmed, low-volume,
and safe to defer/exclude from a first rescue pass (Set 1/2 alone cover >98% of both new forms'
volume).

## D. Name agreement

Cross-referenced all 25 live ATP+WTA fixtures fetched in section A against the poly bridge's
`moneyline`/`total_sets` (FULL-name) questions: **24/25 matched byte-exact** (both the home and
away full name appear verbatim in a poly question); the one miss (`Tomas Martin Etcheverry vs
Ignacio Buse`) is a timing gap — that match simply hasn't had a poly market created yet, not a
naming mismatch. Explicit `normalize_player_name` equality check, 5 players including two
non-ASCII-origin transliterations (Ukrainian/Cyrillic — the class of name most likely to drift
between two data vendors):

| Optic name | Poly name | `normalize_player_name` | Equal? |
|---|---|---|---|
| Mariano Navone | Mariano Navone | `mariano_navone` | yes |
| Luca Van Assche | Luca Van Assche | `luca_van_assche` | yes |
| Oleksandra Oliynykova | Oleksandra Oliynykova | `oleksandra_oliynykova` | yes |
| Paula Badosa | Paula Badosa | `paula_badosa` | yes |
| Anhelina Kalinina | Anhelina Kalinina | `anhelina_kalinina` | yes |

**Zero alias need found** for the FULL-name forms — poly and Optic agree on tennis player-name
spelling essentially perfectly in this sample (unlike MLS/Liga MX team names, which needed a
whole alias overlay — `team_name_aliases`, wave-4 section D). The only real name-agreement risk
in tennis is the surname-only forms' last-token derivation (section C.2), which is a structural
matching-granularity problem, not a spelling/alias problem.

## Tennis rescue scope

**Tier 1 — clone-only (zero new machinery beyond the one `build_rows` tweak in C.1)**: `total_sets`.
1,704 rows / 851 markets. Full-name matching (byte-identical to the already-shipped moneyline
pattern), `OVER_UNDER` shape, existing `Shape.TOTAL` on the Optic side (`total_sets` market_id,
add one `table_types` entry) — needs only a new `MarketType.TOTAL_SETS`, one new recognizer
(`tennis_total_sets_rule`, near-identical to `mlb_total_rule`/`soccer_total_rule`), and the
`build_rows` `startswith` fix from C.1 (which, being backward-compatible, could ship
independently of the tennis wave if preferred).

**Tier 2 — needs the surname-matching mechanism (C.2) first, then cheap clones after**:
`match_total_games` (3,848 rows / 1,921 markets), `set_handicap` (3,108 / 1,546),
`set_games` 1st+2nd only (670 / 340, excluding the 22+22-row 3rd/4th-set tail), `set_winner`
1st+2nd only (466 / 236, excluding the 10+10-row tail). Combined: **8,092 rows / 4,043 markets**
once the name-matching machinery exists — each individual recognizer is then a simple clone
(`_Q_TENNIS_SET_HANDICAP`/`_Q_TENNIS_SET_WINNER`/etc., same anchoring style as the existing
`_Q_SPREAD`/`_Q_MONEYLINE`), needing 4 new `MarketType`s (`MATCH_TOTAL_GAMES`,
`FIRST_SET_TOTAL_GAMES`, `SECOND_SET_TOTAL_GAMES`, `SET_HANDICAP`, `FIRST_SET_WINNER`,
`SECOND_SET_WINNER` — 6 total) all reusing existing `Shape`s (`TOTAL`/`SPREAD`/`MONEYLINE`) and
existing `SideMode`s (`OVER_UNDER`/`SPREAD_TEAM`/`TEAM_LABEL`).

**Deferred / out of scope**: best-of-5 3rd/4th-set forms (44 rows total, Grand-Slam-only,
Optic ceiling unconfirmed live this session); ITF onboarding (a full new-league task, separate
from a market-rules rescue, and the surname-collision risk in C.2 is sharpest there); everything
on Optic's 59-market_id ceiling with zero poly-side demand (player props, correct-score,
odd/even, tiebreak yes/no, game-level handicap, individual-game markets — section B "Confirmed
absent from poly").

**Combined new-rescue total once both tiers ship: 9,796 rows / 4,894 markets (Tier 1 + Tier 2's
1st/2nd-set scope)** — 52.4% of the whole atp/wta/itf tennis bridge, more than doubling the
volume the currently-shipped moneyline-only matcher recovers (3,338 rows / 1,669 markets), with
ITF (2,774 bridge rows, ~15% of the total) still entirely out of reach until it's onboarded as
its own league.
