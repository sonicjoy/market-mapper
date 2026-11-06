# Soccer league extension — census + onboarding report

**Branch:** `feat/polymarket-parity-expansion`
**Goal:** onboard every soccer league that (a) OpticOdds prices AND (b) has a Polymarket bridge, as a poly-only clone of the existing `mls.py`/`ucl.py`/`liga_mx.py` template.

**Headline result:** the exhaustive live census found only **2 new onboardable leagues** — Argentina Primera División and Brazil Serie A. Every other candidate soccer bridge prefix (~28 more) corresponds to a league Optic's live fixtures/odds feed does **not** actually return data for right now, despite most of them appearing in Optic's `/leagues/active?sport=soccer` metadata catalogue (167 entries) — that catalogue is not itself proof of live pricing. This matches this codebase's prior finding that Optic prices a small, apparently curated set of leagues overall (previously estimated at ~9): with this task's two additions, the confirmed-live soccer set is now EPL, Spain La Liga, France Ligue 1, Italy Serie A, USA MLS, Mexico Liga MX, UEFA Champions League, Argentina Primera División, Brazil Serie A — exactly 9.

## Step 1 — Census

One bounded BQ query against `marketmaking-test.raw_ingestion_us.polymarket_position_token_bridge` (115,762 rows), grouped by `SPLIT(slug, "-")[OFFSET(0)]`, returned 81 distinct prefixes. After excluding already-wired soccer (`mls`, `mex`, `ucl`, `fifwc`) and non-soccer (`atp`/`wta`/`itf` tennis, `mlb` baseball, `wnba`/`nbasl` basketball, `ufc` MMA, `cs2`/`val`/`lol`/`dota2`/`hok`/`r6siege`/`mlbb`/`codmw`/`sc2`/`ow` esports, `cric*` cricket — ~15 distinct cricket-competition prefixes), the candidate soccer prefixes were:

`col` (4,123 markets — largest new candidate), `bra2` (1,789), `kor` (1,398), `nwsl` (1,364), `bol1` (1,341), `atc` (1,267), `chi` (1,246), `nor` (1,155), `uel` (1,082), `swe` (1,017), `bra` (815), `auc` (810), `per1` (733), `rou1` (688), `arg` (493), `sud` (479), `uwcl` (434), `gtm` (311), `rus` (271), `cze1` (258), `col1` (214), `chi1` (202), `svk1` (190), `den` (76), `usl1` (52), `hun` (41), `j2100` (12), `trsk` (12), `scop` (10), `efl` (5), `isp` (5), `brco` (3), `lib` (1), `ukr1` (1).

## Step 2 — Resolution against Optic

`GET /leagues/active?sport=soccer` returned 167 entries; the full (non-active-filtered) `/leagues?sport=soccer` catalogue has 775. Every hypothesized league_id for the candidate prefixes above (`uefa_-_europa_conference_league`, `brazil_-_serie_b`, `korea_-_k1_league`/`k2_league`, `usa_-_nwsl`, `bolivia_-_division_professional`, `austria_-_bundesliga`, `china_-_super_league`/`league_one`, `norway_-_eliteserien`/`1_divisjon`, `uefa_-_europa_league`, `sweden_-_allsvenskan`/`superettan`, `australia_-_cup`, `peru_-_primera_division`, `romania_-_liga_i`, `conmebol_-_copa_sudamericana`/`copa_libertadores`, `uefa_-_champions_league_women`, `guatemala_-_liga_nacional`, `russia_-_premier_league`, `czech_republic_-_first_league`, `colombia_-_primera_a`, `chile_-_primera_division`/`primera_b`, `slovakia_-_superliga`/`2_liga`, `denmark_-_superliga`, `usa_-_usl_league_one`, `hungary_-_nb_i`, `japan_-_j1_league`/`j2_league`, `turkey_-_super_lig`, `scotland_-_premiership`, `england_-_league_2`/`national_league`, `india_-_super_league`, `brazil_-_copa_do_brasil`, `ukraine_-_premier_league`/`persha_liha`) was probed directly against `GET /fixtures` and `GET /fixtures/active` with `start_date_after`/`start_date_before` windows out to 90 days.

**Result: every one of them returned zero fixtures**, at every window width tried (default, 16-day, 30-day, 90-day). This was cross-checked against a calibration set to rule out "just off-season lag": `england_-_premier_league`, `spain_-_la_liga`, `france_-_ligue_1`, and `italy_-_serie_a` all correctly returned real, far-forward August-2026 season-opener fixtures (`has_odds=true`) in the identical 90-day-window query — proving Optic *does* pre-populate fixtures well ahead of kickoff for the leagues it actually carries, so leagues returning nothing are genuinely absent from Optic's live feed, not merely "not close enough to game day yet." Two of the highest-value dead ends: `uefa_-_europa_league` and `uefa_-_europa_conference_league` return zero fixtures even though their qualifying rounds run concurrently, this week, with the already-onboarded UEFA Champions League (which itself returned 14 live fixtures in the same query) — Optic simply doesn't carry these two competitions, at least not through this key.

Only **`argentina_-_primera_division`** (45 fixtures / 30 clubs — a full round) and **`brazil_-_serie_a`** (24 fixtures / 20 clubs — a full round) returned live data. A `fixtures/odds` pull on one fixture from each confirmed odds under every soccer_market_rules `market_id` this task's modules wire (moneyline, asian_handicap, total_goals, team_total, 1st_half_moneyline, 1st_half_total_goals, both_teams_to_score, 1st_half_both_teams_to_score, player_goals, 2nd_half_moneyline, first_team_to_score, 2nd_half_total_goals, 1st_half_team_total, 2nd_half_team_total, player_assists, player_shots, player_shots_on_target, player_goals_+_assists, correct_score) — all 19 fired on Brazil's probed fixture, 18/19 on Argentina's (missing only `player_goals_+_assists`, which is kept anyway per the over-include-is-fail-safe convention and did fire on Brazil's same-day fixture).

## Step 3 — Onboarded

| slug_prefix | optic_league_id | File | Aliases |
|---|---|---|---|
| `arg` | `argentina_-_primera_division` | `mappers/leagues/argentina_primera.py` | 3 |
| `bra` | `brazil_-_serie_a` | `mappers/leagues/brazil_serie_a.py` | 4 |

Both clone `mls.py`'s poly-only template verbatim: `KALSHI=None, PX=None, CRYPTO=None, RUNSHOP=None`, `SOCCER_MARKET_TYPES` + `soccer_market_rules`, `question_style="mlb_suffix"`, the same 19-key `OPTIC.table_types` set and `OUTPUT_ORDER` as `mls.py`/`ucl.py`.

**Argentina Primera aliases** (poly name → optic name), resolved by cross-referencing all 482 distinct "arg" bridge questions (30 team names recovered) against the live 30-club fixture list with `mlb_suffix` `_norm_name`/`_name_match` containment:
- `CA Vélez Sarsfield` → `Club Atlético Vélez Sarsfield`
- `CSyD Defensa y Justicia` → `CSD Defensa y Justicia`
- `Gimnasia y Esgrima de La Plata` → `Gimnasia y Esgrima La Plata`

A fourth apparent mismatch, poly's `AA Estudiantes`, was investigated and found to be a **correct** plain-containment match to `AA Estudiantes de Río Cuarto` (a distinct, smaller club) — not a collision with the separately-labeled `Estudiantes de La Plata` fixture. Confirmed by cross-referencing each poly market's slug date against Optic's schedule: poly's "AA Estudiantes vs. CA Tigre" (slug date 2026-07-25) matches Optic's "AA Estudiantes de Río Cuarto vs CA Tigre" (2026-07-25T17:45Z) exactly, while poly's separate "Estudiantes de La Plata … CA Independiente" market (slug date 2026-07-26) matches Optic's "Club Estudiantes de La Plata vs CA Independiente" (2026-07-26T20:15Z) — the two clubs never share a poly label, so no alias was needed for either. This disambiguation has its own regression test (`test_argentina_primera_estudiantes_disambiguation_no_collision`).

**Brazil Serie A aliases**, resolved the same way over 781 distinct "bra" bridge questions (20 team names) against the live 20-club fixture list:
- `Associação Chapecoense de Futebol` → `Chapecoense AF`
- `CA Mineiro` → `Clube Atlético Mineiro`
- `CA Paranaense` → `Club Athletico Paranaense`
- `Grêmio FBPA` → `Grêmio FB Porto Alegrense`

## Skipped candidates (never invented)

Every other candidate prefix from Step 1 was skipped for the same reason: **its hypothesized optic league_id returns zero live fixtures/odds**, confirmed not an off-season/lag artifact (see the EPL/La Liga/Ligue 1/Serie A calibration above).

| Prefix | Hypothesized league_id(s) tried | Result |
|---|---|---|
| `col` | `uefa_-_europa_conference_league` | 0 fixtures (largest skip, 4,123 markets) |
| `uel` | `uefa_-_europa_league` | 0 fixtures |
| `bra2` | `brazil_-_serie_b` | 0 fixtures |
| `kor` | `korea_-_k1_league`, `korea_-_k2_league` | 0 fixtures both |
| `nwsl` | `usa_-_nwsl` | 0 fixtures |
| `bol1` | `bolivia_-_division_professional` | 0 fixtures |
| `atc` | (no plausible optic league_id — team names are Austrian amateur/regional clubs not in Optic's catalogue) | no league_id found |
| `chi` | `china_-_super_league`, `china_-_league_one` | 0 fixtures both |
| `nor` | `norway_-_eliteserien`, `norway_-_1_divisjon` | 0 fixtures both |
| `swe` | `sweden_-_allsvenskan`, `sweden_-_superettan` | 0 fixtures both |
| `auc` | `australia_-_cup` | 0 fixtures |
| `per1` | `peru_-_primera_division` | 0 fixtures |
| `rou1` | `romania_-_liga_i` | 0 fixtures |
| `sud` | `conmebol_-_copa_sudamericana` | 0 fixtures |
| `uwcl` | `uefa_-_champions_league_women` | not even in `/leagues/active`; 0 fixtures |
| `gtm` | `guatemala_-_liga_nacional` | 0 fixtures |
| `rus` | `russia_-_premier_league` | 0 fixtures |
| `cze1` | `czech_republic_-_first_league` | 0 fixtures |
| `col1` | `colombia_-_primera_a` | 0 fixtures |
| `chi1` | `chile_-_primera_division`, `chile_-_primera_b` | 0 fixtures both |
| `svk1` | `slovakia_-_superliga`, `slovakia_-_2_liga` | 0 fixtures both |
| `den` | `denmark_-_superliga` | 0 fixtures |
| `usl1` | `usa_-_usl_league_one` | 0 fixtures |
| `hun` | `hungary_-_nb_i` | 0 fixtures |
| `j2100` | `japan_-_j2_league`, `japan_-_j1_league` | not in `/leagues/active`; 0 fixtures |
| `trsk` | `turkey_-_super_lig` | 0 fixtures |
| `scop` | `scotland_-_premiership` | 0 fixtures |
| `efl` | `england_-_league_2`, `england_-_national_league` | 0 fixtures both |
| `isp` | `india_-_super_league` | not in `/leagues/active`; 0 fixtures |
| `brco` | `brazil_-_copa_do_brasil` | 0 fixtures |
| `lib` | `conmebol_-_copa_libertadores` | 0 fixtures |
| `ukr1` | `ukraine_-_premier_league`, `ukraine_-_persha_liha` | 0 fixtures both |

No mapping was invented for any of these; per the task mandate, a league Optic doesn't price is skipped, not guessed.

## Files changed

- `mappers/leagues/argentina_primera.py` (new)
- `mappers/leagues/brazil_serie_a.py` (new)
- `mappers/leagues/__init__.py` — `League.ARGENTINA_PRIMERA` / `League.BRAZIL_SERIE_A` enum members + `_LEAGUE_SPORT` entries (both `Sport.SOCCER`)
- `mappers/run.py` — both registered in `LEAGUES`
- `fetch/optic.py` — both registered in `LEAGUE_SECRET` (`"opticodds_access_key"`)
- `tests/mappers/test_soccer_league_extension.py` (new) — 31 tests: registry wiring, poly-only invariants, `SOCCER_MARKET_TYPES`/`soccer_market_rules` identity, 19-key `OPTIC.table_types` coverage, `LEAGUE_SECRET`/`SUPPORTED_LEAGUES` invariants, and alias-resolution tests for all 7 aliases (including the Estudiantes disambiguation regression test)

**2 new `League` enum members added.**

## Validation (Step 5)

Both onboarded leagues are in-season right now, so both were live-validated (not just forward-ready):

```
GCP_PROJECT=marketmaking-test .venv/bin/python -m fetch.optic --league argentina_primera brazil_serie_a --out-dir data/2026-07-23/12_00
GCP_PROJECT=marketmaking-test .venv/bin/python -m fetch.polymarket --out-dir data/2026-07-23/12_00
.venv/bin/python -m mappers.run data/2026-07-23/12_00 --league argentina_primera --json
.venv/bin/python -m mappers.run data/2026-07-23/12_00 --league brazil_serie_a --json
```

Results:
- **argentina_primera:** 8 fixtures fetched; 145 poly rows stamped, 0 dropped (optic didn't price), 295 agree, **0 conflict-dropped**. 138 "no fixture" / 27 "non-game-line" are poly rows outside the small fetched fixture window / futures markets, expected given only 8 of the league's ~15 rounds-in-flight fixtures were fetched.
- **brazil_serie_a:** 2 fixtures fetched; 109 poly rows stamped, 0 dropped (optic didn't price), 73 agree, **0 conflict-dropped**.

Spot-checked stamped rows by eye (moneyline_3way, game_total, correct_score, first_team_to_score, 1st/2nd-half team totals) against the poly question text — all team-code/side/line assignments correct, including rows that exercised the aliases live (`CSyD Defensa y Justicia`, `CA Gimnasia y Esgrima de Mendoza`, `Gimnasia y Esgrima de La Plata` via `Racing Club to score first vs. Gimnasia y Esgrima de La Plata?`, and `CA Vélez Sarsfield` via `Will CA Vélez Sarsfield win on 2026-07-24?`). Zero mismatches found.

## Test suite / lint

- Baseline (pre-change): `651 passed, 13 skipped` (confirmed via `git stash`).
- After change, `tests/mappers/` (task's canonical gate): `684 passed, 17 skipped` — the delta is +31 from the new `test_soccer_league_extension.py` file plus the pre-existing generic per-league parametrized tests in `test_table_completeness.py` picking up the 2 new leagues automatically (+2 passed / +4 skipped from those, netting to the +33 minus 2 double-counted... concretely: `test_table_completeness.py` alone went from 651/13 → 653/17 with just the registry wiring in place, before the new test file was added; adding the 31-test file brought it to 684/17).
- Full `tests/` (all suites, `GCP_PROJECT=marketmaking-test`): `763 passed, 17 skipped`.
- **No golden files touched** — the new leagues are additive-only (new `League` enum members + new modules), so existing golden output is byte-identical (confirmed no regressions in the full suite run).
- `ruff check` on all changed files: clean on every line this task added or touched. 5 pre-existing lint findings remain in `fetch/optic.py` (E402 late import, B011 `assert False`, UP017 `datetime.UTC` alias) and `mappers/run.py` (E501 long docstring line) — confirmed via `git stash` to be present on the pre-existing baseline, untouched by this task's edits, and left alone (out of scope; not on a line this task changed).

## Bottom line

Of ~30 soccer bridge prefixes with a live Polymarket market, **2** are backed by an Optic league Optic is actually pricing live: Argentina Primera División and Brazil Serie A. Both are now onboarded, tested, and live-validated. The other ~28 — including two very large ones (Europa League, Europa Conference League) — are confirmed *not* priced by Optic right now and were correctly left unmapped rather than guessed. This is consistent with, and further corroborates, this codebase's standing finding that Optic's live-odds coverage is a small curated set of leagues (now 9 confirmed soccer leagues total across this codebase's Kalshi+poly and poly-only configs), not the ~167-endpoint metadata catalogue's apparent breadth.
