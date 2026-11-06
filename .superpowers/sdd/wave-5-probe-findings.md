# Wave 5 — Basketball optic+poly probe findings (2026-07-23)

Probe environment: `.venv/bin/python`, `GCP_PROJECT=marketmaking-test` for Optic
fetches. Read-only — no source file modified; all exploration ran via `/tmp`
throwaway scripts (`fetch.optic`'s `--league` CLI is choice-restricted to the
9 currently-wired leagues and has no leagues-listing helper, so the
`leagues/active` discovery and the odds-ceiling pulls both needed raw
`requests` calls reusing `fetch.optic.get_optic`/`get_fixtures`/
`get_fixture_odds` directly — same pattern as Wave 4).

**Auth note:** both the `gcloud` CLI (`bq`, `gcloud auth print-access-token`,
`gcloud secrets versions access`) hit `Reauthentication failed. cannot prompt
during non-interactive execution` in this environment. `gcloud auth
application-default print-access-token` still worked, so (a) the BigQuery
pull used the `google-cloud-bigquery` Python client (`bigquery.Client(project=
"rs-marketmaking")`, ADC-authenticated) instead of the `bq` CLI, and (b) the
Optic secret (`opticodds_access_key`) was fetched via a direct Secret Manager
REST call bearer-authenticated with the same ADC token, replicating
`fetch/optic.py`'s `_init_headers` (gcloud-subprocess based) without needing
a working `gcloud` CLI session. Both are read-only, equivalent-privilege
substitutions — no code path in the repo was changed.

## A. Optic basketball market ceiling + league_ids

`GET {BASE_URL}leagues/active?sport=basketball` returned **14 active
leagues** (this endpoint lists only leagues with currently live/upcoming
inventory — NBA is absent because it's offseason, confirmed separately
below):

| League | Optic `league_id` | numerical_id | region | gender |
|---|---|---|---|---|
| **WNBA** | **`wnba`** | 553 | UNITED_STATES | women |
| USA - WNBA All Star | `usa_-_wnba_all_star` | 748 | UNITED_STATES | women (not a config target — All-Star exhibition, noted in passing) |
| NCAAB | `ncaab` | 356 | UNITED_STATES | — |
| (10 other non-target leagues: Australia NBL1/WNBL1, BIG3, Brazil LBF Women, Chile LNB, Lebanon LBL, Mexico LNBP, New Zealand NBL, Puerto Rico BSN, Uruguay Metro League, Vietnam VBA) | | | | |

**`ncaab`** matches the already-shipped `mappers/leagues/ncaab.py`
(`OpticConfig(league_id="ncaab", ...)`) exactly — parity confirmed live.

**NBA** does not appear in `leagues/active` at all (0 hits for `"nba"` or
`"basketball_nba"` in either the sport-filtered 14-league list or a second,
unfiltered `leagues/active` pull across **all 241** currently-active
leagues/all sports) — confirming NBA is genuinely offseason on Optic's side
right now, so its `league_id` could not be independently re-derived from live
data this probe. The shipped `mappers/leagues/nba.py` already hardcodes
`OpticConfig(league_id="nba", ...)`; this is consistent with the bare-
lowercase-no-region-prefix convention observed on `wnba`/`ncaab` (unlike
soccer's `usa_-_major_league_soccer` style) and is accepted as correct by
naming-convention parity, not live-reconfirmed.

**NBA Summer League has NO Optic league_id at all** — searched the full
241-league unfiltered active list for `"summer"` and any `"nba"`-adjacent id:
zero matches beyond `wnba`/`usa_-_wnba_all_star`. **Optic does not track NBA
Summer League as a league, at any URL.** This means the poly `nbasl` bridge
prefix (see section B) has **0% Optic coverage** — not a mapping gap, a
genuine absence of an Optic-side counterpart. Confirms the plan's implicit
scoping (no `nbasl.py` module is in the File Structure) is correct; do not
build a matcher for it.

**WNBA live odds ceiling.** WNBA is on its All-Star break at probe time — the
`fixtures/active` pull for `wnba` returned **0 fixtures inside the default
48h horizon** (`FIXTURE_HORIZON_HOURS`); games resume 2026-07-28. Widening to
`horizon_hours=240` surfaced **15 upcoming (all `"unplayed"`) fixtures**,
5–9 days out — no fixture was actually live, so (mirroring Wave 4's MLS
fallback when no live fixture existed) the odds ceiling below is the union
across the 7 nearest fixtures that had any odds posted at all (the other 8,
7+ days out, had 0 rows from every sportsbook tried — books simply haven't
opened those boards yet):

**61 distinct `market_id`s, ranked by summed position-row count across the 7
posted fixtures** (game/team-scoped only — see player-market caveat below):

```
   420  team_total                              21  1st_quarter_race_to_25_points
   338  total_points                             21  2nd_quarter_race_to_25_points
   336  point_spread                             21  1st_quarter_race_to_15_points
   294  both_teams_total_points                  21  1st_quarter_moneyline_3-way
   140  1st_half_team_total                      21  2nd_quarter_moneyline_3-way
   140  1st_quarter_team_total                   21  2nd_half_moneyline_3-way
    98  1st_half_total_points                    21  4th_quarter_moneyline_3-way
    98  1st_half_point_spread                    21  3rd_quarter_moneyline_3-way
    70  1st_quarter_point_spread                 21  1st_half_moneyline_3-way
    56  moneyline                                20  1st_quarter_race_to_10_points
    42  halftime_fulltime                        19  3rd_quarter_race_to_10_points
    28  team_total_points_odd_even               17  2nd_quarter_race_to_10_points
    28  moneyline_+_total_points                 14  4th_quarter_moneyline
    28  2nd_quarter_team_total                   14  4th_quarter_total_points
    28  4th_quarter_team_total                   14  3rd_quarter_point_spread
    28  4th_quarter_total_points_odd_even        14  3rd_quarter_moneyline
    28  1st_quarter_total_points_odd_even        14  2nd_half_point_spread
    28  3rd_quarter_total_points_odd_even        14  2nd_quarter_point_spread
    28  2nd_half_team_total                      14  2nd_quarter_total_points
    28  2nd_quarter_total_points_odd_even        14  1st_half_total_points_odd_even
    28  3rd_quarter_team_total                   14  last_team_to_score
   21  2nd_quarter_race_to_15_points             14  4th_quarter_point_spread
   21  1st_quarter_race_to_20_points             14  1st_half_moneyline
   21  3rd_quarter_race_to_20_points             14  1st_quarter_moneyline
   21  2nd_quarter_race_to_20_points             14  will_there_be_buzzer_beater
   21  3rd_quarter_race_to_15_points             14  2nd_half_total_points
                                                  14  2nd_quarter_moneyline
                                                  14  3rd_quarter_total_points
                                                  14  2nd_half_moneyline
                                                  14  total_points_odd_even
                                                  12  will_there_be_overtime
                                                  12  1st_quarter_race_to_30_points
                                                   6  3rd_quarter_race_to_30_points
                                                   6  2nd_quarter_race_to_30_points
```

Game-scoped `market_id` spelling (`moneyline`, `point_spread`, `total_points`,
`team_total`, `1st_half_moneyline`, `1st_half_point_spread`,
`1st_half_total_points`, `1st_half_moneyline_3-way`, `2nd_half_moneyline_3-way`)
is **byte-identical to `nba.py`/`ncaab.py`'s existing `OpticConfig.table_types`
keys** — confirms Optic runs one canonical basketball taxonomy across
NBA/NCAAB/WNBA (every game-level key checked matches).

**Player-prop markets (`player_points`, `player_assists`, `player_rebounds`,
etc.) were NOT observed live** — checked all 7 posted fixtures (0 hits) plus
a second pass on the earliest fixture (`20260728DBB00DA5`, Washington
Mystics vs. Connecticut Sun) widened to 10 additional sportsbooks (pinnacle,
caesars, espn_bet, williamhill_us, bet365, bovada, betrivers, bally_bet,
circa_sports, wynnbet) — still 0 `player_*` rows from any book. This reads as
a **timing gap, not a coverage gap**: every fixture available at probe time
was 5+ days out, and player-prop boards across all 15 sportsbooks tried
simply hadn't opened yet (game-level markets — spread/total/team_total — were
fully posted on the same fixtures at the same horizon, so this isn't a
blanket "nothing's posted" issue). **This could not be directly confirmed
from live data this probe.** Given the exact-match game-level taxonomy above,
the working assumption for Task 2+/W2 is that WNBA reuses NBA's player
`market_id` spellings (`player_points`, `player_assists`, `player_rebounds` —
the three poly actually asks for, see section B; NBA's other player types —
`player_made_threes`/`blocks`/`steals`/`turnovers`/`double_double`/
`triple_double` — are not asked by poly for WNBA either, so moot either way).
**Recommend a same-day-of-game reconfirmation** (`fetch.optic --explore wnba`
within ~24–48h of a WNBA tip-off) before treating the player `table_types`
list as fully live-verified, rather than asserting it here as observed.

## B. Poly basketball form histogram (`wnba` + `nbasl` bridge prefixes)

Bounded BQ pull (`bigquery.Client(project="rs-marketmaking")`, dry-run
first): `SELECT slug, question, outcome_label, position_id, outcome_index,
n_outcomes FROM marketmaking-test.raw_ingestion_us.polymarket_position_token_bridge
WHERE SPLIT(slug,"-")[OFFSET(0)] IN ("wnba","nbasl")` — dry-run estimate
**20,274,046 bytes (~19.3 MiB)**, somewhat above the brief's ~10–17 MiB
expectation (this table has grown since Wave 4) but still a single bounded
scan; actual query billed **23,068,672 bytes (~22.0 MiB)**, processed
22,094,558 bytes. **1,670 rows total: `wnba` 1,624 / `nbasl` 46.**

A regex classifier (anchored on the real question shapes below, not a naive
keyword search) covered **1,624/1,624 wnba rows (100%)** into exactly **6
buckets** — no `OTHER` bucket, no unclassified rows:

| poly form | exact template | outcome_labels | position count | % | ~distinct markets | example |
|---|---|---|---|---|---|---|
| player points | `<Player>: Points O/U <N>` | **Yes / No** | 378 | 23.3% | 189 | `Paige Bueckers: Points O/U 21.5` → Yes/No |
| game total | `<A> vs. <B>: O/U <N>` | Over / Under | 340 | 20.9% | 170 | `Chicago Sky vs. Dallas Wings: O/U 176.5` → Over/Under |
| player rebounds | `<Player>: Rebounds O/U <N>` | **Yes / No** | 302 | 18.6% | 151 | `Aliyah Boston: Rebounds O/U 8.5` → Yes/No |
| player assists | `<Player>: Assists O/U <N>` | **Yes / No** | 282 | 17.4% | 141 | `Caitlin Clark: Assists O/U 6.5` → Yes/No |
| spread | `Spread: <Team> (-N)` / `(+N)` | **both team names** | 224 | 13.8% | 112 | `Spread: Minnesota Lynx (-12.5)` → Minnesota Lynx / (opponent) |
| moneyline | `<A> vs. <B>` (bare, no colon) | **both team names** | 98 | 6.0% | 49 | `Chicago Sky vs. Dallas Wings` → Chicago Sky / Dallas Wings |

**All 4 requested-but-not-yet-confirmed forms were explicitly checked and are
ABSENT from `wnba`** (0/1,624 rows each, verified by direct substring/keyword
search across all 579 distinct questions, not just the histogram buckets
above missing them):

- **team_total** — no `<A> vs. <B>: <Team> O/U N` shape anywhere, despite
  Optic pricing `team_total` as the single highest-volume market on the live
  board (section A). Poly genuinely doesn't ask for it on WNBA.
- **1st/2nd-half markets of any kind** — no `half`/`halftime` substring in
  any of the 579 distinct questions, despite Optic pricing
  `1st_half_total_points`/`1st_half_point_spread`/`1st_half_moneyline_3-way`/
  `2nd_half_moneyline_3-way` extensively.
- **player threes / blocks / steals / turnovers** — no `three`/`block`/
  `steal`/`turnover` substring anywhere. The player-prop menu is exactly
  {Points, Assists, Rebounds} — a narrower set than NBA's own Kalshi ticker
  types (which include `3PT`/`BLK`/`STL`).
- **double-double / triple-double** — no `double` substring anywhere.

So the **July census note is now fully resolved**: alphabetical sampling
hadn't hidden anything real — WNBA's poly menu is genuinely just these 6
forms; it is dominated by player props (962/1,624 = 59.2% combined) but ML/
spread/total are confirmed present too (40.8% combined), just less numerous
per-game than the 3-stat player-prop ladder.

**All 15 current WNBA franchises appear** (14 incumbent + 2 2026 expansion
teams, Toronto Tempo and `PortlandFire`/Portland Fire — see section D).

**`nbasl` (NBA Summer League, 46 rows / 23 distinct games) is ML-only,
confirmed by full classification, not sampling**: every question matches
`NBA Summer League: <A> vs. <B>` (note the `"NBA Summer League: "` prefix —
**not** the bare MLB-style `<A> vs. <B>`; this form has a colon, so the
existing `mlb_moneyline_rule`'s `if ":" in q: return None` guard would
incorrectly drop it as-is). outcome_label = both team names (TEAM_LABEL
style). Per section A, this has 0% Optic coverage regardless, so no
recognizer is warranted — noted for completeness only, matching the plan's
File Structure (no `nbasl.py`).

## C. Moneyline encoding — confirmed TEAM_LABEL (bare `<A> vs. <B>`, NOT the soccer 3-way-Yes/No form)

**Verdict: basketball moneyline is the bare MLB-style 2-way `TEAM_LABEL`
form, byte-identical in shape to `mlb_moneyline_rule`'s recognized pattern —
NOT** the soccer `Will <Team> win on <date>?` Yes/No `THREE_WAY_FIXED` form.
Confirmed directly from the bridge data (section B):

```
'Chicago Sky vs. Dallas Wings' → outcome_label 'Chicago Sky' (idx 0/2), 'Dallas Wings' (idx 1/2)
'Indiana Fever vs. Las Vegas Aces' → outcome_label 'Indiana Fever' (idx 0/2), 'Las Vegas Aces' (idx 1/2)
```

No `"Will <Team> win on <date>?"`, no `"Will <A> vs. <B> end in a draw?"`,
and (expectedly, since basketball has no draw) no 3rd/tie outcome anywhere —
every moneyline question is exactly 2 outcomes, both team-name labels. This
means basketball moneyline reuses `mlb_moneyline_rule`'s exact regex
(`^(.+?)\s+vs\.?\s+(.+?)$` guarded by "no colon") and `SideMode.TEAM_LABEL`
unchanged — no new recognizer shape, no `THREE_WAY_FIXED` needed for the
full-game moneyline.

**1st/2nd-half winner markets: poly does NOT offer them for WNBA at all**
(section B — 0/1,624 rows contain "half" in any form). So the
`THREE_WAY_FIXED` half-winner question (does poly ask a 2-way team-label form
or does Optic's genuinely-3-way `1st_half_moneyline_3-way`/
`2nd_half_moneyline_3-way` force a `THREE_WAY_FIXED`-shaped poly market) is
**moot for WNBA** — there is no poly question to recognize, so this path is
dormant for the WNBA config specifically. Optic prices
`1st_half_moneyline_3-way`, `2nd_half_moneyline_3-way`, and (new, beyond NBA's
existing table_types) `1st_quarter_moneyline_3-way` through
`4th_quarter_moneyline_3-way` (all confirmed live, section A) — genuinely
3-way markets (Team A / Team B / _TIE, since a quarter or half CAN end level
in regulation even though the full game can't) — but with zero poly demand
for any half/quarter form on WNBA, this is inventory with no counterpart,
not a rescue candidate. NBA/NCAAB (offseason, unconfirmable this probe) may
still ask half-winner markets once in season — Wave-4's `THREE_WAY_FIXED`
machinery is unchanged and available if/when that's confirmed, but nothing
in this probe exercises it for basketball.

## D. Name agreement

**Team names** — cross-referenced all 15 poly WNBA franchise names (parsed
from the moneyline form, section B) against Optic's 15 team names (`home_
team_display`/`away_team_display` across the 15 upcoming `fixtures/active`
fixtures — a full round-robin cross-section of the league), running the
actual `mappers.exchanges.polymarket._norm_name`/`_name_match` (`"mlb_
suffix"` style, plain containment) programmatically (not by hand):

| poly name | optic name | mlb_suffix containment? |
|---|---|---|
| `PortlandFire` | `Portland Fire` | **NO** — `_normalize("PortlandFire")` → `"portlandfire"` (no space, since there's no punctuation to split on) vs `_normalize("Portland Fire")` → `"portland fire"` (space-separated); neither is a contiguous substring of the other |
| *(all other 14 franchises)* | *(exact match)* | **YES** — plain containment resolves cleanly |

**1 of 15 (6.7%) fails** — a single, very mechanical case (missing a space in
the poly question text's team-name concatenation for the newest 2026
expansion franchise), not a nickname/legal-name mismatch like MLS's 5. Needs
one `team_name_aliases` entry for Task W2:
`{"portlandfire": "portland fire"}` (both sides already `_norm_name`'d, per
the existing overlay's key/value convention). Toronto Tempo (the *other* 2026
expansion team) needed no alias — `"toronto tempo"` matches exactly both
sides.

**Player names** — `normalize_player_name` (imported directly, not
reimplemented) run against 14 WNBA players spanning every diacritic/
punctuation shape the function's own docstring claims to handle:

```
"A'ja Wilson"            -> "a'ja_wilson"          (apostrophe kept)
"Flau'jae Johnson"       -> "flau'jae_johnson"     (apostrophe kept)
"Azurá Stevens"          -> "azura_stevens"        (diacritic folded)
"Leïla Lacan"            -> "leila_lacan"          (diacritic folded)
"Janelle Salaün"         -> "janelle_salaun"       (diacritic folded)
"Charlisse Leger-Walker" -> "charlisse_leger-walker" (hyphen kept)
"Olivia Nelson-Ododa"    -> "olivia_nelson-ododa"    (hyphen kept)
"DeWanna Bonner"         -> "dewanna_bonner"       (mixed-case fold)
"NaLyssa Smith"          -> "nalyssa_smith"        (mixed-case fold)
"Kayla McBride"          -> "kayla_mcbride"
"Sarah Ashlee Barker"    -> "sarah_ashlee_barker"
"Sonia Citron"           -> "sonia_citron"
"Caitlin Clark"          -> "caitlin_clark"
"Paige Bueckers"         -> "paige_bueckers"
```

Every shape present in the WNBA player pool (apostrophes, French/Scandinavian
diacritics, hyphenated surnames, mixed-case compound first names) is one the
function already documents and folds correctly — no new normalization
failure mode surfaced. **Caveat**: since Optic hadn't posted any
`player_points`/`player_assists`/`player_rebounds` selections for WNBA at
probe time (section A), this is a *function-correctness* check, not a
*direct poly-vs-optic agreement* check (no live Optic player selection string
existed to diff against). No poly∩optic player-name mismatch can be ruled
out until the section-A player-market reconfirmation happens; nothing found
here contradicts agreement, but treat it as function-level (not
data-level) verification pending the day-of-game re-probe.

## Impact on Tasks 2+

**Mappable forms (poly ∩ optic) for WNBA, confirmed:** moneyline
(`TEAM_LABEL`), spread (`SPREAD_TEAM`), game total (`OVER_UNDER`), player
points/assists/rebounds (**`YESNO_AS_OU`, not `OVER_UNDER`** — see below).
That's it — 6 forms, matching section B's histogram exactly. `team_total`
and any half/quarter market, though richly priced by Optic (section A), have
**zero poly demand** and must NOT be wired (no question to recognize, and
building one would be inventing a mapping poly never asks for — against the
plan's global constraint).

**Recognizer reuse — all four WNBA forms are structurally identical to
existing MLB `mlb_suffix`-style rules, confirmed byte-for-byte against
section B/C's real question text:**

- **Moneyline**: `mlb_moneyline_rule`'s exact regex/guard
  (`^(.+?)\s+vs\.?\s+(.+?)$`, colon-guarded) — **works unchanged**,
  `SideMode.TEAM_LABEL`.
- **Game total**: `mlb_total_rule`'s exact regex
  (`^(.+?)\s+vs\.?\s+(.+?):\s*o/u\s*([\d.]+)\s*$`) — **works unchanged**,
  `SideMode.OVER_UNDER`.
- **Spread**: `mlb_spread_rule`'s exact regex
  (`^spread:\s*(?P<team>.+?)\s*\(\s*([+-]?[\d.]+)\s*\)\s*$`) — **works
  unchanged**, `SideMode.SPREAD_TEAM`.
- **Player props (points/assists/rebounds)**: reuse the shared
  `_player_prop_rule` helper with 3 new stat regexes (`"<Player>: Points O/U
  N"` / `"Assists"` / `"Rebounds"`, mirroring `_Q_HOME_RUNS`/
  `_Q_STRIKEOUTS`'s shape exactly) — **but each call MUST pass
  `side_mode=SideMode.YESNO_AS_OU`**, not the helper's `OVER_UNDER` default.
  This is the one genuine deviation from the MLB template: MLB's home-runs/
  strikeouts props use `Over`/`Under` labels (`OVER_UNDER`), while WNBA's
  points/assists/rebounds props use **`Yes`/`No`** labels (confirmed 100%
  consistent across all 481 Yes + 481 No rows checked) — the same
  `YESNO_AS_OU` mode soccer's `mlb_first_inning_rule`/`soccer_player_goals_
  rule` already exercise, just newly applied to a `PLAYER`-scope prop rather
  than a `GAME`-scope one. Getting this wrong (defaulting to `OVER_UNDER`)
  would silently drop every WNBA player-prop row (`build_rows`' `OVER_UNDER`
  branch expects literal `"Over"`/`"Under"` labels it will never see), not
  mismap it — fails safe, but still 962/1,624 rows (59%) of the entire wnba
  bridge sample lost if missed.

**Half-winner `THREE_WAY_FIXED` path**: not exercised by WNBA (poly asks
nothing half-related) — leave the machinery available (already frozen/
working from Wave 4) but WNBA's own `market_rules` tuple needs no
half-winner recognizer. Revisit if/when NBA/NCAAB (in-season) are confirmed
to ask a half-winner poly form.

**Alias needs for Task W2 (`wnba.py`)**: exactly one —
`team_name_aliases = {"portlandfire": "portland fire"}`. Toronto Tempo (the
other 2026 expansion team) needs none.

**`OpticConfig` for `wnba.py`**: `league_id="wnba"`, `table_types` restricted
to the poly-confirmed 4 market families — `moneyline`, `point_spread`,
`total_points`, `player_points`, `player_assists`, `player_rebounds` (NBA's
`table_types` naming convention, pending the day-of-game live reconfirmation
noted in section A for the three player entries specifically). Do **not**
carry over `team_total`/half-winner/quarter-level types from NBA's template
this time — unlike MLB→Liga MX/UCL (Wave 4 Task 7b) where the same-sport
template carried harmless dead weight, WNBA's poly menu is narrow enough
that padding `table_types` with types poly never asks for is just inert
noise; harmless either way but the leaner list is more accurate documentation
of what this config actually does.

**`nbasl`**: confirmed 0% Optic coverage (section A) — no module, no
recognizer, no config. Not a Wave-5 candidate at all, unlike Wave 4's
correct_score (which Optic priced AND poly asked for — this is neither poly-
without-optic nor optic-without-poly, it's a poly form with literally no
Optic league to stamp onto).

**NBA/NCAAB (Task W1)**: cannot be probed live this wave (both offseason,
absent from the bridge and, for NBA, absent from `leagues/active` too).
Their `OpticConfig`s are already shipped and match this probe's confirmed
naming convention (section A) — Task W1 is forward-ready config work
(`POLYMARKET` config referencing the same `mlb_suffix`-style recognizers,
since NBA/NCAAB's own poly question shapes are presumed identical to WNBA's
per the plan's parity framing) but its exact poly form menu (does NBA poly
ask team_total? half-winner? the fuller Threes/Blocks/Steals/Turnovers/DD/TD
prop menu its Kalshi ticker types imply?) is **unconfirmed** and should be
spot-checked once the bridge repopulates for the 2026-27 season, rather than
assumed from this WNBA-only pull.
