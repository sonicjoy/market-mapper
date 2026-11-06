# Task 8: live-data validation of the Polymarket soccer matcher (MLS/Liga MX/UCL)

Read-only analysis (no pipeline/matcher source touched). Env: `GCP_PROJECT=marketmaking-test`,
`.venv/bin/python`, no poetry. Run 2026-07-22, ~21:56–22:10 UTC.

## Environment gaps found (worked around, not fixed in source)

1. **`fetch/optic.py`'s `SUPPORTED_LEAGUES` map / `--league` argparse choices was never
   updated** for mls/liga_mx/ucl — only `mappers/run.py`'s `LEAGUES` registry + the three
   league modules were wired (Tasks 6/7a/7b). `python -m fetch.optic --league mls` errors
   at argparse (`invalid choice`). Worked around with a throwaway script
   (`/tmp/wave4_fetch_optic_soccer.py`) that reuses `fetch.optic`'s own
   `_init_headers`/`get_fixtures`/`get_fixture_odds`/`process_fixture` helpers verbatim
   against `mappers.leagues.{mls,liga_mx,ucl}.OPTIC`, writing the identical
   `optic_fixtures_odds.jsonl` contract `mappers/pipeline.py` expects. No repo file
   touched; script lives in `/tmp` only. Recommend wiring `fetch/optic.py` for real before
   these leagues go into any scheduled fetch.
2. **`config/<league>/team_aliases.toml` did not exist for mls/liga_mx/ucl.**
   `mappers/pipeline.py::run()` hard-raises (`ValueError: Optic abbreviations not in
   team_aliases.toml`) if any Optic-fixture team abbreviation has no canonical entry —
   this gate is unconditional (runs regardless of KALSHI/PX being `None`) and blocks the
   pipeline before any Polymarket stamping logic runs at all. Created
   `config/mls/team_aliases.toml` with the 30 bare "Identity (no exchange keys)" stanzas
   the error itself printed (MLS is poly-only, so no `px`/`kalshi`/`crypto` alias keys are
   needed or populated). **Not git-committed** — flagged as scratch infra for this
   validation session only; a real one should be generated properly if MLS ever gets
   Kalshi/PX/crypto coverage. Liga MX/UCL never needed one this session (0 optic fixtures
   in-horizon → empty abbreviation set → gate is a no-op).

## MLS — full end-to-end run (15 live fixtures, 2026-07-22/23 kickoffs)

`optic_fixtures_odds.jsonl`: 15 fixtures (48h horizon). `polymarket_markets.jsonl`: 16,752
markets total bridge-wide, 1,134 with `mls-` slug prefix.

```
polymarket [mls]: 36 stamped, 0 dropped (optic didn't price), 135 no fixture,
                  594 non-game-line, 684 agree, 0 conflict-dropped
```
stderr otherwise clean — **no exceptions, no warnings**, for any of the 3 league runs.

### 1. Stamps by form

Per the task's own definition (row where the `polymarket` block is populated in
`--json` output): **36 stamps, all `team_total`** (18 over / 18 under — perfectly
balanced). Zero stamps in any other form.

This undercounts real coverage, though — see next section. `attach_polymarket_row`
only fires for a clob token Optic's own bridge does **not already carry a native
`Polymarket` source_id for** (guard #4 in `pipeline.run`); tokens Optic already maps
natively short-circuit into a separate "agree/conflict" bucket and never reach
`attach_polymarket_row`, so they show `polymarket: null` in the row despite being a
fully-validated match. Cross-referencing `optic_odds.source_ids.Polymarket` against
`--json` output gives the true picture (row-level, i.e. counting every optic row our
matcher could have attached a poly token to, whether Optic beat us to it or not):

| market_type | native (Optic beat us to it, "agree") | new (`stamped` by us) | total poly-matched rows |
|---|---|---|---|
| moneyline_3way | 45 | 0 | 45 |
| point_spread | 120 | 0 | 120 |
| game_total | 180 | 0 | 180 |
| team_total | 144 | 36 | 180 |
| btts | 30 | 0 | 30 |
| first_half_winner_3way | 45 | 0 | 45 |
| first_half_total | 90 | 0 | 90 |
| first_half_btts | 30 | 0 | 30 |
| **total** | **684** | **36** | **720** |

0 of the 684 "agree" rows also got a fresh stamp (no double-stamping) and **0
conflicts** — every token our matcher independently resolved to a row_key, Optic's
own native Polymarket mapping (an unrelated integration on Optic's side) agreed with
byte-for-byte. That 0-conflict result across 720 poly-matched rows is itself strong
correctness evidence for the whole matcher, not just the 36 that needed a fresh stamp.

### 2. Task-4.5 fix validation — PASS

Inspected `_resolve_poly_markets`'s resolved set directly (pre guard-#4 bucketing) for
the two `THREE_WAY_FIXED` forms:

```
moneyline_3way:        30 TEAM-win selections + 15 TIE (draw) selections  (45 total = 15 fixtures × 3)
first_half_winner_3way: 30 TEAM-win selections + 15 TIE (draw) selections  (45 total)
```

Single-team `"Will <Team> win on <date>?"` legs **do** resolve (67% of moneyline_3way
resolutions are team-win, not just draws) — the Phase-B `(frozenset{slug teams}, date)`
deferred-resolution mechanism works as designed. Zero of these 90 resolutions produced
a guard-#4 conflict against Optic's own independently-sourced native Polymarket
mapping, i.e. every team-win/draw fixture+side attribution the fix produces is
verified correct against ground truth, not just "didn't crash."

Spot check: `mls-hou-dcu-2026-07-22-hou` (`Will Houston Dynamo win on 2026-07-22?`)
resolved to fixture Houston Dynamo FC vs DC United — correct fixture, correct
`fixed_side_team="houston dynamo"`, `team_b=None` as designed.

### 3. Alias validation (MLS's 5 franchises) — PASS

All 5 aliased franchises had a live fixture in this 15-fixture window and **all 5
resolved with zero drops**, across every market form each fixture offered (not just
one form each):

| franchise (poly name) | optic name | fixture | forms resolved |
|---|---|---|---|
| D.C. United SC | DC United | Houston Dynamo vs DC United | team_total(×6), moneyline_3way(team-win+draw), 1h_winner_3way, spread, total, 1h_total |
| CF Montréal | Club de Foot Montréal | Nashville SC vs CF Montréal | team_total(×6), + same full set |
| Los Angeles Galaxy | LA Galaxy | LA Galaxy vs St. Louis City SC | team_total(×6), + same full set |
| New York City FC | New York City Football Club | Columbus Crew vs NYCFC | btts, spread, team_total, total, 1h_total, halftime, moneyline (team-win + draw) — all resolved |
| Inter Miami CF | Club Internacional de Fútbol Miami | Inter Miami vs Chicago Fire FC | btts, spread, team_total, total, 1h_total, halftime, moneyline (team-win + draw), 1h_btts — all resolved |

NYCFC and Inter Miami show 0 in the "new stamp" count only because Optic's own native
Polymarket mapping already covered every one of their poly-matched rows (6/6 team_total
rows = "agree", not "neither") — confirmed via the raw `_resolve_poly_markets` trace
(not just the row-level bucket), which shows every poly market for both fixtures
(clb-nyc-*, mia-chi-*) resolving to the correct fixture. **No franchise silently
dropped.**

### 4. Correctness checks — all pass

- **Market-type mismatches: 0/36.** Every stamp's poly question matches the
  `team_total` shape (`<A> vs. <B>: <Team> O/U <N>`) it was stamped onto.
- **Line mismatches: 0/36.** `key.line == optic_odds.points` for every stamp.
- **Over/under balance:** 18 over / 18 under — exact 50/50.
- **3 hand-verified spot checks** (poly question → optic selection):
  - `Houston Dynamo vs. D.C. United SC: D.C. United SC O/U 0.5` → optic selection
    `DC United`, side `over`, line `0.5`, `key.away="DC"` — correct (alias-resolved,
    correct home/away orientation from slug `-team-total-away-0pt5`).
  - `Houston Dynamo vs. D.C. United SC: Houston Dynamo O/U 0.5` → optic selection
    `Houston Dynamo FC`, `key.home="HOU"` — correct.
  - `Los Angeles Galaxy vs. St. Louis City SC: Los Angeles Galaxy O/U 0.5` → optic
    selection `LA Galaxy`, `key.home="LA"` — correct (alias-resolved).

### 5. Drop analysis

Of 1,134 `mls-` bridge markets: **594 (52.4%) unparsed** (no recognizer shape matched),
540 (47.6%) parsed — matches the ~48%-mappable expectation almost exactly. Unparsed
samples confirm the expected/designed drop set only:
`Exact Score: <A> N - N <B>?` / `Exact Score: Any Other Score?` (biggest single chunk),
`<Team> 1st/2nd Half O/U <N>` (team-half total), bare `2nd Half O/U <N>` (game 2nd-half
total), `... Both Teams to Score in Second Half`, `<Team> to score first vs. <Team>?`,
`Neither team to score first?`, `<Team> to win the second half?`, `Second half draw?`.
No unexpected drop patterns seen — every sampled unparsed question is one of the
already-documented out-of-scope forms (exact_score/2nd-half/to-score-first/team-half).

Of the 540 parsed, 405 (75%) additionally resolved to one of our 15 in-horizon
fixtures; the other 135 (25%) are `no_fixture` — expected, since the poly bridge
carries markets for MLS games well beyond this run's 48h optic-fetch window (the
mismatch is window size, not a matcher defect).

## Liga MX — 0 live fixtures in horizon, noted and skipped

`optic_fixtures_odds.jsonl` (48h horizon, fetched 2026-07-22 22:05 UTC): **0
fixtures.** Extended-horizon probe (240h, `/tmp` scratch, not part of the validated
run) confirms Liga MX's next matchday starts `2026-07-25T03:00:00Z` — genuinely
outside the default window, not a bug. Ran poly-bridge fetch + mapper anyway to
confirm no crash on the 0-fixture case:
```
polymarket [liga_mx]: 0 stamped, 0 dropped, 125 no fixture, 84 non-game-line, 0 agree, 0 conflict-dropped
```
Clean exit, no exceptions. 84/209 (40%) of `mex-` bridge markets unparsed (60%
recognized) — roughly consistent with MLS's ~48% mappable rate, though with 0 optic
fixtures this run proves nothing about actual stamping correctness, only that
parsing + the 0-fixture path don't crash.

## UCL — 0 live fixtures in horizon, noted and skipped

`optic_fixtures_odds.jsonl` (48h horizon, fetched 2026-07-22 22:10 UTC): **0
fixtures.** The wave-4 probe's single live qualifier (`202607228B140941`, kicked off
`2026-07-22T19:00:00Z`) had already concluded by this run's later time-of-day.
Extended-horizon probe (240h, scratch) shows the next UCL qualifying fixtures start
`2026-07-28T15:00:00Z`. Ran poly-bridge fetch + mapper anyway:
```
polymarket [ucl]: 0 stamped, 0 dropped, 369 no fixture, 461 non-game-line, 0 agree, 0 conflict-dropped
```
Clean exit, no exceptions. 369/830 (44.5%) recognized.

## Overall verdict

MLS (the only league with live in-horizon fixtures this run) validates cleanly
end-to-end: **Task-4.5's single-team moneyline/1st-half-winner fix works** (team-win
legs resolve, 30/45 non-tie, 0 conflicts against Optic's own ground truth), **the MLS
alias overlay works** (all 5 aliased franchises resolved on every form, 0 silent
drops), and **all sampled correctness checks pass** (0 market-type mismatches, 0 line
mismatches, perfect O/U balance, 3/3 hand spot-checks correct). Drop rate (52.4%
unparsed) matches the ~48%-mappable design expectation, and every sampled drop is an
already-documented out-of-scope form. Liga MX and UCL had no live fixtures in the
default 48h fetch horizon at run time (both confirmed via extended probe to be
genuinely off-season/off-window, next kickoffs 2026-07-25 and 2026-07-28
respectively) — pipeline ran clean with 0 exceptions on the 0-fixture path for both,
but neither produced a stamp to validate against real fixture data this session.
