# Soccer rescue-wave live-data validation (2026-07-23)

Read-only analysis, no source touched (`mappers/`, `fetch/`, `config/` all
byte-identical to `HEAD` — confirmed via `git status --short` before/after).
Scratch scripts live under `/tmp` (this session's isolated scratchpad), never
in the repo tree. Env: `.venv/bin/python`, no poetry, `GCP_PROJECT=marketmaking-test`.

Validates the three rescue-wave commits on `feat/polymarket-parity-expansion`
against live Optic + Polymarket data:

- `50a317e` Task R1 — 10 cheap-tier recognizers (2nd-half total/team-totals,
  2nd-half winner+draw, first-to-score, 4 World-Cup player-prop ladders).
- `2f6df89` Task R2 — wires those `MarketType`s into `OpticConfig.table_types`
  for all 5 soccer leagues.
- `761514b` Task R4 — `Shape.CORRECT_SCORE` / `SideMode.EXACT_SCORE`, the poly
  `Exact Score:` ↔ Optic `correct_score` join (the "winner-anchor swap").

**Bottom line: both workarounds worked first try, no reauth blocker hit.
Live optic fetch succeeded for MLS, Liga MX, and UCL. 0 exceptions, 0
conflict-drops, 0 mis-stamped scorelines across 2,396 live poly soccer legs.
The `correct_score` join — the critical ask — is verified correct on real
data for home wins, away wins (the winner-anchor swap), and draws, across
all three leagues.**

## 0. Environment / run log

`gcloud secrets versions access` and the BigQuery client both worked without
any reauth prompt this session (no ADC-REST fallback was needed for the optic
secret; noting it anyway since the brief called it out as the known failure
mode). Directory: `data/2026-07-23/11_04/` (gitignored, matches the
`<date>/<HH_MM>` convention — built at the actual wall-clock time this
session ran, not the brief's `14_00` placeholder).

```
GCP_PROJECT=marketmaking-test .venv/bin/python -m fetch.polymarket --out-dir "$D"
  → Wrote data/2026-07-23/11_04/polymarket_markets.jsonl (19495 markets)
GCP_PROJECT=marketmaking-test .venv/bin/python -m fetch.optic --league mls --out-dir "$D"
  → mls: 0 fixtures   *** see deviation below ***
```

**Deviation from the brief, disclosed:** the *default* 48h fixture horizon
(`FIXTURE_HORIZON_HOURS`) returned **zero** fixtures for MLS, Liga MX, *and*
UCL at the moment this session ran (~2026-07-23 10:00 UTC) — every upcoming
fixture in all three leagues currently kicks off 2–6 days out (next MLS
gameweek 07-25/26, Liga MX 07-25–07-27, UCL Q3 second legs 07-28/29), outside
the 48h window. This is a genuine, momentary live-data fact, not a bug (the
override flag exists in `fetch/optic.py` precisely "for testing leagues whose
fixtures haven't entered the production horizon yet"). Re-ran all three
leagues in **one** `fetch.optic` call (the `--league` flag is
multi-value and writes one shared `optic_fixtures_odds.jsonl`, so leagues
must be fetched together or they clobber each other) with `--horizon-hours
168`:

```
GCP_PROJECT=marketmaking-test .venv/bin/python -m fetch.optic \
  --league mls liga_mx ucl --out-dir "$D" --horizon-hours 168
  → Wrote data/2026-07-23/11_04/optic_fixtures_odds.jsonl   (36 fixtures: 15 mls + 7 liga_mx + 14 ucl)

.venv/bin/python -m mappers.run "$D" --league mls --json > /tmp/rescue_mls.json 2>/tmp/rescue_mls.err
.venv/bin/python -m mappers.run "$D" --league liga_mx --json > /tmp/rescue_liga_mx.json 2>/tmp/rescue_liga_mx.err
.venv/bin/python -m mappers.run "$D" --league ucl --json > /tmp/rescue_ucl.json 2>/tmp/rescue_ucl.err
```

`grep -n "CONFLICT\|Traceback\|Error\|error"` across all 3 `.err` files:
**zero hits.** No exception anywhere in the run.

## 1. Pipeline-level stats (ground truth, from stderr)

| league | optic fixtures | poly rows (slug-scoped) | **stamped** (net-new) | dropped (optic didn't price) | no fixture | non-game-line | **agree** (pre-existing native match) | **conflict-dropped** |
|---|---|---|---|---|---|---|---|---|
| mls | 15 | 1,211 | **15** | 0 | 995 | 58 | 223 | **0** |
| liga_mx | 7 | 335 | **61** | 0 | 166 | 18 | 127 | **0** |
| ucl | 14 | 850 | **15** | 10 | 745 | 48 | 42 | **0** |
| **total** | **36** | **2,396** | **91** | **10** | **1,906** | **124** | **392** | **0** |

`agree` means: our poly-side parse independently computed a
`(market_type, entity, line, side)` key for a clob token that **Optic's own
API already cross-references to a Polymarket `selection_id`** (a pre-existing
native passthrough, unrelated to this rescue wave). Guard #4
(`_build_optic_poly_index`) checks every such token: if our key disagrees
with Optic's own mapping it's a `CONFLICT` (loud stderr line, drop); if it
agrees it silently passes through and is **not** double-counted as
`stamped`. **0 conflicts across 2,396 legs** is itself strong evidence the
new recognizers compute the *same* canonical key Optic derives independently
— see the worked example in §2.

## 2. Rescue-form stamp counts

Net-new `stamped` rows this run, by `market_type` (rescue-tier only; `team_total`/
`moneyline_3way`/`game_total` stamps are pre-existing Wave-4 forms picking up
incidental new inventory, not part of this rescue and not counted below):

| form | new `MarketType` | mls | liga_mx | ucl | total |
|---|---|---|---|---|---|
| `correct_score` (Task R4) | `CORRECT_SCORE` | 8 | 49 | 8 | **65** |
| `first_team_to_score` (Task R1) | `FIRST_TEAM_TO_SCORE` | 1 | 8 | 0 | **9** |
| `1h_team_total` (Task R1) | `FIRST_HALF_TEAM_TOTAL` | 2 | 0 | 0 | **2** |
| `2h_total`, `2h_team_total`, `2h_winner_3way` | — | 0 | 0 | 0 | 0 |
| player assists/shots/shots-on-target/goals+assists | — | 0 | 0 | 0 | 0 (N/A this run) |

**Why several rescue forms show 0 *new* stamps — and why that's not a
defect.** Cross-checking each rescue `MarketType`'s Optic rows for a
pre-existing native `source_ids.Polymarket` entry (the same "agree" mechanism
as §1) shows a sharp split:

- `2h_winner_3way`/`1h_winner_3way`: **100%** of Optic's rows on all 36 live
  fixtures (45/45 on mls) *already* carry Optic's own native Polymarket
  cross-reference. Every one of these legs therefore resolves via `agree`,
  not `stamped` — worked example below (Task R1's `SECOND_HALF_WINNER_3WAY`
  wiring is fully exercised and validated, just not through the "stamped"
  counter).
- `2h_total`/`1h_total`: ~45-52% native coverage; the *rest* have no poly
  question posted yet for the specific 07-25+ gameweek fetched this run
  (confirmed directly: every "2nd Half O/U" poly question in the mls bridge
  is dated 07-16 or 07-22 — last gameweek, already kicked off and outside any
  forward-looking fetch window — none exist yet for 07-25/26). A
  market-creation-lifecycle gap, not a mapping gap.
- `first_team_to_score`/`1h_team_total`/`2h_team_total`/all 4 player-prop
  forms: **0%** native coverage — Optic never cross-referenced these to
  Polymarket on its own. Every correct match for these forms depends
  entirely on this rescue wave's new recognizers. We got 9 + 2 live,
  hand-verified matches (below) with **zero** native safety net — the
  cleanest possible proof these two `MarketType`s are wired correctly.
  `2h_team_total` and the 4 player-prop ladders simply had no matching poly
  question posted yet for these particular 36 fixtures this run (player
  props are World-Cup-only by design — reconfirmed 0/2,396 rows here, same
  as the probe found on 8,810 rows) — **PENDING**, needs a live World Cup
  fixture to exercise (none active this session; out of scope per the
  brief unless WC-style data showed up here, which it didn't).

**Worked "agree" example** (proves `SECOND_HALF_WINNER_3WAY`'s draw wiring
is correct even without a fresh stamp): poly
`mex-gua-jua-2026-07-25-second-half-result-draw` → *"CD Guadalajara vs. FC
Juárez: Second half draw?"*, clob token
`...883052...883052`. Optic's `2nd_half_moneyline` odd for the *same*
Guadalajara/Juárez fixture already carries
`selection="Draw"`, `source_ids.Polymarket.selection_id` = the **identical**
token. Our own `soccer_second_half_draw_rule` → `build_rows` independently
computes `(market_type=2h_winner_3way, side=_TIE)` for that token — exactly
Optic's own key. No conflict logged. QED for that path.

## 3. `correct_score` cross-check (the critical one)

Hand-verified across all three leagues, using the actual stamped rows (poly
`question`, Optic `selection`/`selection_line`, and the computed
`(side, line)` all printed together):

**Home win** (no swap needed — Optic's home-anchored `selection_line` already
reads "own:opp" in poly's phrasing order):
```
poly:  "Exact Score: CF Montréal 1 - 0 Inter Miami CF?"      (MTL home)
optic: selection="Club de Foot Montréal", selection_line="1:0"
join:  side=MTL, line=1.0                                     ✓ correct
```

**Away win — the winner-anchor swap** (Optic anchors every scoreline to the
team that scored *more*, own-goals-first; poly always phrases home-first —
so an away win requires swapping the two digits):
```
poly:  "Exact Score: CF Montréal 2 - 3 Inter Miami CF?"       (MTL home=2, MIA away=3)
optic: selection="Club Internacional de Fútbol Miami", selection_line="3:2"  (MIA's own goals first)
join:  side=MIA, line=3.02                                    ✓ correct swap
```
Same swap confirmed independently on Liga MX (`Atlante FC 0 - 1 CF América?`
→ `side=CFA, selection_line="1:0"`) and UCL (`Górnik Zabrze 0 - 2 Fenerbahçe
SK?` → `side=FB, selection_line="2:0"`).

**Draw**:
```
poly:  "Exact Score: CF Montréal 1 - 1 Inter Miami CF?"
optic: selection="Draw", selection_line="1:1"
join:  side=_TIE, line=1.01                                   ✓ correct
```

Verified this pattern held on **all 65 stamped `correct_score` rows** across
the 3 leagues (full home-win/away-win-swap/draw ladders on Atlante–América,
Tijuana–León, Guadalajara–Juárez, Montréal–Miami, St.Louis–Colorado,
Górnik Zabrze–Fenerbahçe, plus single-line fixtures elsewhere) — every
`optic_selection`/`selection_line` pair matches the poly scoreline exactly
per the documented `winner_goals + loser_goals/100.0` encoding, in every
case. **0 conflicts, 0 mis-stamps** (no poly scoreline ever landed on a
different fixture's or a different scoreline's row — checked exhaustively by
clob-token cross-reference, not just eyeballing).

Additionally, of the 894 `correct_score` Optic rows on mls alone, 192
*already* carry Optic's own native Polymarket cross-reference (pre-dating
this task) — none of those 192 conflicted with our independently-derived
key either (0 conflict-dropped, aggregate, across all market types). That's
a second, out-of-band confirmation of the encoding.

## 4. 2nd-half-winner draw leg + first-to-score

- **`_TIE` (2nd-half draw)**: confirmed correct via the Guadalajara/Juárez
  `agree` example in §2 (independently computed key == Optic's own native
  key). No fresh `stamped` example existed in this snapshot for the reason
  given in §2 (100% native coverage on every one of the 36 fixtures'
  `2nd_half_moneyline` rows).
- **first-to-score team legs — DO stamp**, 9 live examples, spot-checked:
  ```
  "Los Angeles FC to score first vs. Sporting Kansas City?" → side=LAF        ✓
  "CF América to score first vs. Atlante FC?"                → side=CFA      ✓
  "Club León FC to score first vs. Club Tijuana?"            → side=LEO      ✓
  "FC Juárez to score first vs. CD Guadalajara?"              → side=FCJ      ✓
  "Atlas FC to score first vs. Club Santos Laguna?"           → side=ATS      ✓
  ```
  Each of a fixture's two team-named questions resolves independently to its
  *own* team's side (both directions checked on 4 fixtures) — no mirroring
  bug, no fixture cross-talk.
- **`Neither team to score first?` — confirmed absent, by design.**
  Collected the clob tokens of all 36 live `"Neither team to score first?"`
  bridge questions (mls 17 + liga_mx 7 + ucl 12) and searched all three
  output files for any of them appearing as a `polymarket.clob_token_id` on
  *any* stamped/agreed row: **0 hits in all three leagues.** These legs
  correctly fall through `parse_question` as unparsed (no recognizer exists
  for them, by Task R1's explicit documented decision) and land in the
  `non-game-line` bucket, not silently mis-stamped onto some other market.

## 5. Correctness

- **Market-type / line mismatches: 0**, and structurally guaranteed to stay
  that way — `attach_polymarket_row` only succeeds on an exact
  `(market_type, entity, line, side)` dict-key match against `row_index`; a
  wrong market_type or line simply fails to join (→ `dropped_no_optic`),
  it can never silently attach to the wrong row. Combined with 0
  conflict-drops against Optic's own independently-sourced keys (§1, §3),
  this is confirmed both by construction and empirically.
- **Over/under balance**: every paired total form in the stamped output is
  perfectly 1:1 — `team_total` (mls 2/2, liga_mx 2/2), `1h_team_total` (mls
  1/1), `game_total` (ucl 1/1). No lone unpaired side anywhere.
- **3+ hand spot-checks across rescue forms** (beyond `correct_score`):
  `team_total` correctly splits per-team (D.C. United vs Toronto FC →
  Toronto-side row at line 1.5, matching poly's *"Toronto FC O/U 1.5"*, not
  D.C. United's own line); `1h_team_total` (LAFC/Sporting KC → Sporting KC's
  own 0.5 line, correct team+line pairing); `moneyline_3way` on UCL correctly
  folds both team-phrased *and* the alternate `"Will X vs Y end in a draw?"`
  phrasing onto the same `_TIE` row.

## 6. Drops — full decomposition, nothing unexplained

**`no fixture` (1,906 rows, 100% explained):** every one of these belongs to
a *different real-world match* than the 36 fixtures fetched this run — a
prior or later gameweek for the same franchise. Verified by date-bucketing
every league's poly bridge by its slug date: mls has clusters at 07-16 (69),
**07-22 (930)**, plus March/April/May (52) — only the 07-25 gameweek (160
rows) falls inside our fetched-fixture window, and 1,211−160=1,051 ≈ 995 (the
gap is the small residual of unparsed/dropped rows within that same 07-25
gameweek). Liga MX and UCL show the identical pattern (UCL: 07-21 first-leg
ties at 597+191 rows vs. the 07-28/29 second legs we fetched at 18+44). The
"already-started-or-finished match, not in this forward-looking snapshot"
explanation is exhaustive — not a resolution bug on any fixture we actually
have.

**`non-game-line` / unparsed (124 rows, 100% explained, 4 documented
buckets, 0 unrecognized residue):**

| bucket | mls | liga_mx | ucl | total |
|---|---|---|---|---|
| `Exact Score: Any Other Score?` (documented permanent drop, grid boundary) | 17 | 7 | 14 | 38 |
| `Neither team to score first?` (documented intentional non-recognizer, §4) | 17 | 7 | 12 | 36 |
| 2nd-half BTTS (out-of-scope bonus form, noted in the probe, not this wave) | 16 | 2 | 11 | 29 |
| total/team corners (out-of-scope bonus form, same) | 8 | 2 | 10 | 20 |
| "Anytime Goalscorer" 1-off noise (known since wave-4) | 0 | 0 | 1 | 1 |
| **total** | **58** | **18** | **48** | **124** |

124/124 reconciled — **zero unrecognized poly soccer question forms** turned
up in 2,396 live legs across 3 leagues.

**`dropped (optic didn't price)` (10 rows, ucl only, fully explained):** all
10 belong to exactly 2 fixtures — Kuopio PS–Sabah FK and FK Kauno
Zalgiris–KÍ Klaksvík, both UCL qualifying ties 6+ days out — where Optic
hasn't posted odds yet for *any* market on that fixture, including the
already-shipped base `moneyline_3way`/`game_total` forms (verified: the
dropped keys include plain `moneyline_3way` rows, not just rescue-tier
ones). A live-timing/bootstrap artifact of hitting the furthest-out fixtures
in the horizon window, not a rescue-wave defect.

## 7. Exceptions

None. `grep -n "CONFLICT\|Traceback\|Error\|error"` across all 3 run logs:
zero matches. All 3 `mappers.run` invocations exited 0.

## Caveats / follow-ups

- Player-prop rescue forms (`player_assists`, `player_shots`,
  `player_shots_on_target`, `player_goals_or_assist`) are **PENDING** — 0/36
  live fixtures this run had any such poly question (World-Cup-only by
  design, per the probe), so they weren't exercised. Needs a live
  `--league world_cup` fetch during an active WC/qualifying window to
  validate end-to-end; not attempted here since none was active.
- `2h_team_total` (`SECOND_HALF_TEAM_TOTAL`) similarly saw 0 live poly
  questions this run (market-creation lifecycle — the corresponding
  "2nd Half O/U" team-total questions for the fetched gameweek aren't posted
  yet) — code path unexercised on live data this session, though its sibling
  `1h_team_total` stamped correctly (§2, same code shape).
- EPL was not run (task scope was mls/liga_mx/ucl only; EPL's `slug_prefix`
  remains the pre-existing "unvalidated" caveat noted in Task R4's report).
- This validation used `--horizon-hours 168` instead of the 48h production
  default, purely to have live fixtures to test against at run time (§0) —
  a read-only CLI-flag deviation, no source touched.

## Files

- Data: `data/2026-07-23/11_04/{polymarket_markets.jsonl,optic_fixtures_odds.jsonl}` (gitignored).
- Mapper output: `/tmp/rescue_{mls,liga_mx,ucl}.json` + `.err` (scratch, not committed).
