# Tennis rescue live-data validation (2026-07-23)

Read-only analysis, no source touched. `git status --short` was clean before
and after this session — the one side effect (`mappers.tennis_bootstrap`
auto-rewrites `config/{atp,wta}/team_aliases.toml` on every `mappers.run`, per
its own docstring) was reverted with `git checkout --` once analysis was
done, so the tree is byte-identical to `HEAD`. Scratch scripts and JSON dumps
live under `/tmp` (this session's scratchpad), never in the repo tree. Env:
`.venv/bin/python`, no poetry, `GCP_PROJECT=marketmaking-test`.

Validates the three tennis-rescue commits on `feat/polymarket-parity-expansion`
against live Optic + Polymarket data:

- `0227ffc` Tier 1 — `total_sets` rescue + the `build_rows` OVER_UNDER
  baked-line fix (poly's `"Over 2.5"`/`"Under 2.5"` labels).
- `c840ed4` Task TN2 — the `name_granularity="surname"` mechanism +
  `_fixture_surname_collision` flip-safety guard.
- `c17f2af` Task TN3 — 4 surname-only forms: `match_total_games`,
  `set_games` (1st/2nd), `set_handicap`, `set_winner` (1st/2nd).

**Bottom line: both ADC workarounds were unnecessary — the plain
`fetch/optic.py`/BigQuery path worked first try for both ATP and WTA, no
reauth blocker hit. 0 exceptions, 0 conflict-drops, 0 mis-stamps, 0 collision
drops across 9 ATP + 14 WTA live fixtures. `total_sets`, `match_total_games`,
`set_handicap` all cross-validate exactly against Optic's own independent
Polymarket mapping (146 agreeing legs total, byte-identical clob tokens, zero
conflicts). `set_games`/`set_winner` (the two remaining surname forms) had
**zero live poly inventory** for either league at this snapshot — Polymarket
currently lists only doubles Set-1/2 markets, no ATP/WTA singles ones — so
they were instead verified as a direct code-level check (real fixture,
synthetic-but-format-exact poly questions): both parse and bind the surname
to the correct competitor code in either name order. The flip-safety
collision guard was also verified directly (synthetic same-surname fixture →
0 rows, both `TEAM_LABEL` and `SPREAD_TEAM` paths); no real ATP/WTA fixture
in this window has two same-surname competitors.**

## 0. Environment / run log

Neither `gcloud`/`bq` reauth issue mentioned in the brief materialized —
`fetch/optic.py`'s subprocess-based secret fetch and `bq_client()` both
worked unmodified, so the ADC-REST fallback was never needed.

```
D=data/2026-07-23/16_30
GCP_PROJECT=marketmaking-test .venv/bin/python -m fetch.optic --league atp --out-dir "$D"
  → atp: 9 fixtures
GCP_PROJECT=marketmaking-test .venv/bin/python -m fetch.polymarket --out-dir "$D"
  → Wrote data/2026-07-23/16_30/polymarket_markets.jsonl (19520 markets)
.venv/bin/python -m mappers.run "$D" --league atp --json > /tmp/tennis_atp.json 2>/tmp/tennis_atp.err
  → exit 0, 887 rows

GCP_PROJECT=marketmaking-test .venv/bin/python -m fetch.optic --league wta --out-dir "$D"
  → wta: 14 fixtures  (overwrites optic_fixtures_odds.jsonl; polymarket_markets.jsonl is
                        league-agnostic, shared, not re-fetched)
.venv/bin/python -m mappers.run "$D" --league wta --json > /tmp/tennis_wta.json 2>/tmp/tennis_wta.err
  → exit 0, 1243 rows
```

Default horizon was sufficient for both leagues — 9 ATP + 14 WTA fixtures
came back on the first (non-`--horizon-hours`) call; the "empty default
horizon" deviation flagged in the brief did not occur this run. Both leagues
had 1–2 fixtures already `is_live` (1 ATP: Hanfmann/Baez; 2 WTA:
Bartunkova/Tararudee, Oliynykova/Gormaz) — the pipeline's pre-existing
is-live skip (`mappers/pipeline.py`, "we don't emit rows for in-progress
games") correctly drops **all** markets for those fixtures from the JSON
output; this fully explains every "optic didn't price" drop below (§1), it
is not a mapping defect.

`grep -ni "traceback\|exception"` on both `.err` files (excluding the
informational `reconcile:` lines, which are pre-existing Kalshi/PX
cross-checks unrelated to this task — no Kalshi/PX data was fetched this
session): **zero hits.**

## 1. Pipeline-level stats (ground truth, from stderr)

```
atp: polymarket [atp]: 0 stamped, 12 dropped (optic didn't price), 675 no fixture,
     89 non-game-line, 62 agree, 0 conflict-dropped
wta: polymarket [wta]: 0 stamped, 18 dropped (optic didn't price), 205 no fixture,
     35 non-game-line, 84 agree, 0 conflict-dropped
```

**Important nuance for reading "stamped" here** (same mechanism as the prior
soccer-rescue validation, `wave-rescue-validation.md` §1): `stamped` counts
only *net-new* attachments where Optic's own row had no pre-existing native
`source_ids.Polymarket` cross-reference. `agree` counts poly markets whose
independently-computed `(market_type, entity, line, side)` key lands on a
row Optic **already** natively cross-references to the identical Polymarket
clob token (a pre-existing Optic↔Polymarket passthrough, unrelated to this
rescue) — 0 conflicts means every single one of those pre-existing native
links was independently *reproduced byte-for-byte* by the new tennis
recognizers. In this snapshot, **every** poly-resolvable, pre-game tennis
market for both leagues happened to already carry Optic's native mapping, so
`stamped` reads 0 — that is a property of this narrow 23-fixture sample
(Optic's tennis feed evidently back-fills its own Polymarket links for
everything it also prices on Polymarket), not evidence the rescue adds no
value in general.

## 2. Per-form breakdown (replicated directly from the pipeline's own
`_resolve_poly_markets` + `build_rows`, cross-checked against the real
`row_index` — not re-derived by hand)

| form | league | poly markets resolved to a fixture | → rows: agree | → rows: dropped (all = the 1–2 live fixtures) | conflict |
|---|---|---|---|---|---|
| `moneyline` (baseline) | atp | 8 | 14 | 2 | 0 |
| `moneyline` (baseline) | wta | 14 | 24 | 4 | 0 |
| `total_sets` (Tier 1) | atp | 6 | 10 | 2 | 0 |
| `total_sets` (Tier 1) | wta | 10 | 16 | 4 | 0 |
| `match_total_games` (TN3) | atp | 16 | 26 | 6 | 0 |
| `match_total_games` (TN3) | wta | 15 | 24 | 6 | 0 |
| `set_handicap` (TN3) | atp | 7 | 12 | 2 | 0 |
| `set_handicap` (TN3) | wta | 12 | 20 | 4 | 0 |
| `1st_set_total_games`/`2nd_set_total_games` (TN3) | both | **0** | — | — | — |
| `1st_set_winner`/`2nd_set_winner` (TN3) | both | **0** | — | — | — |

`62 = 14+10+26+12` (atp) and `84 = 24+16+24+20` (wta), `12 = 2+2+6+2` and
`18 = 4+4+6+4` — reconciles exactly with §1's aggregate stderr line, and
every single "dropped" row traces to one of the 3 live fixtures (verified by
listing the dropped rows' slugs: 100% `atp-hanfman-baez-2026-07-24-*` for
ATP, 100% `wta-bartunk-tararud-2026-07-22-*` / `wta-oliynyk-gormaz-2026-07-23-*`
for WTA).

**Why `set_games`/`set_winner` show 0 resolved markets — confirmed as a live
market-catalog gap, not a matcher bug.** Searched the *entire* atp (801
markets) and wta (291 markets) Polymarket bridge dumps for any question
containing "Set 1"/"Set 2"/"1st Set"/"2nd Set": ATP has 58 such questions,
WTA has 9 — **100% of them are doubles** (`atp-doubles-...`, slash-joined
player names). Filtering to singles-only questions in either bridge: **0
results in both leagues.** Polymarket simply isn't listing 1st/2nd-set
games/winner markets for ATP or WTA singles right now (doubles only) — there
is nothing live for these two forms to bind to, in either league, this
snapshot.

## 3. Surname resolution — hand-verified (THE novel bit)

**`set_handicap` — signed line bound to the correct named side** (real
stamp, ATP, Assche/Busta, `game_id=24114-37798-2026-29`):

```
poly slug:  atp-assche-busta-2026-07-22-set-handicap-away-1pt5
poly question: "Set Handicap: Busta (-1.5) vs Assche (+1.5)"
our matcher → row(home=ASS, away=BUS2, line=-1.5, side=BUS2, clob=...284139617)
            → row(home=ASS, away=BUS2, line=+1.5, side=ASS,  clob=...928287)
Optic's OWN independent source_ids.Polymarket for those exact 2 grid cells:
  (side=BUS2, line=-1.5) → selection_id 56369596...284139617   ✓ identical
  (side=ASS,  line=+1.5) → selection_id 34886301...928287      ✓ identical
```
Surname "Busta" → `Pablo Carreno Busta` (away code `BUS2`), "Assche" →
`Luca Van Assche` (home code `ASS`) — both bound to the **correct** player
and the **correct** signed side (favorite `Busta -1.5` = away, underdog
`Assche +1.5` = home), matching Optic's own clob tokens exactly. (Optic's
row_index also carries the mirror-image grid cells `ASS@-1.5`/`BUS2@+1.5`
from its own dense ladder — those have no Polymarket source at all, since no
such market exists; our matcher correctly never touches them.)

**`total_sets` — baked O/U label bound correctly** (real stamp, ATP,
Assche/Busta):
```
poly outcomes: "Over 2.5" (clob ...978127803), "Under 2.5" (clob ...307586068)
our matcher → side=over, line=2.5, clob=...978127803   ✓ matches Optic's native "Polymarket" source_ids exactly
            → side=under, line=2.5, clob=...307586068  ✓ matches
```

**`match_total_games` — O/U across multiple lines per match** (real stamp,
ATP, Rublev/Skatov, line 21.5):
```
our matcher → side=over,  line=21.5, clob=12037692...639619   ✓ matches Optic native
            → side=under, line=21.5, clob=57919469...071914   ✓ matches
```

**`set_games`/`set_winner` — no live poly inventory this snapshot (§2), so
verified as a direct code-level check** instead: called
`polymarket.parse_question` + `build_rows` on the real Assche/Busta ATP
fixture (`ASS`/`BUS2`) with synthetic-but-format-exact questions (matching
the regexes byte-for-byte, `_Q_TENNIS_SET_GAMES` / `_Q_TENNIS_SET_WINNER`):

| question | parsed `MarketType` | resolved rows |
|---|---|---|
| `"Assche vs. Busta: Set 1 Games O/U 9.5"` | `FIRST_SET_TOTAL_GAMES` | `side=over/under, line=9.5, home=ASS, away=BUS2` ✓ |
| `"Assche vs. Busta: Set 2 Games O/U 10.5"` | `SECOND_SET_TOTAL_GAMES` | `side=over/under, line=10.5, home=ASS, away=BUS2` ✓ |
| `"Set 1 Winner: Assche vs Busta"` | `FIRST_SET_WINNER` | `side=ASS` (clob for "Assche" outcome), `side=BUS2` (clob for "Busta" outcome) ✓ |
| `"Set 2 Winner: Busta vs Assche"` (names **deliberately reversed**) | `SECOND_SET_WINNER` | `side=BUS2` (clob for "Busta"), `side=ASS` (clob for "Assche") ✓ — order-independent, no mirroring bug |

All 4 bind the surname to the correct competitor code regardless of the
order the names appear in the question.

## 4. Collision guard — verified directly, 0 real drops this run

**Real fixtures**: scanned all 9 ATP + 14 WTA fixtures' `(home_name,
away_name)` last-token surnames for a match — **0 collisions found** in
either league this snapshot (confirms the probe's expectation).

**Synthetic collision check** (since no real one existed to observe): built
a fake fixture `home_name="Pedro Martinez"` / `away_name="Roberto Martinez"`
(shared surname "martinez") and ran both surname-sensitive branches:

```
"Set 1 Winner: Martinez vs Martinez"                    → build_rows → 0 rows  ✓ dropped
"Set Handicap: Martinez (-1.5) vs Martinez (+1.5)"      → build_rows → 0 rows  ✓ dropped
"Assche vs Busta" (non-colliding sanity check)          → build_rows → 2 rows ✓ still works
```
Confirms `_fixture_surname_collision` correctly gates both `TEAM_LABEL`
(`set_winner`) and `SPREAD_TEAM` (`set_handicap`) — the two branches where a
surname actually resolves to a specific competitor in the output row.
`OVER_UNDER` forms (`match_total_games`/`set_games`) are correctly **not**
gated: their output side is `over`/`under`, never a player identity, so a
same-surname ambiguity in the *input* team-name match poses no output-level
mis-stamp risk — confirmed this is intentional by reading the two call sites
in `build_rows` (only under `SideMode.TEAM_LABEL` and `SideMode.SPREAD_TEAM`).

## 5. Correctness

- **Market-type / line mismatches: 0.** `attach_polymarket_row` only
  succeeds on an exact `(market_type, entity, line, side)` key match against
  `row_index`; combined with 0 conflict-drops against Optic's own
  independently-sourced keys (§1–§3), this is confirmed both structurally
  and empirically across 146 agreeing legs (62 atp + 84 wta).
- **Mis-stamps (surname landing on the wrong player): 0.** Every hand-checked
  `set_handicap`/`total_sets`/`match_total_games` stamp's clob token matches
  Optic's own independently-sourced mapping exactly (§3) — a mis-bind would
  either conflict (loud stderr, none occurred) or simply fail to join
  (dropped, and the actual drops all trace to live-fixture skip, not a
  binding failure).
- **Over/under balance**: perfectly 1:1 in every case checked — `total_sets`
  (atp 5/5, wta 8/8 pairs), `match_total_games` (atp 13/13, wta 12/12 pairs)
  — no lone unpaired side anywhere.
- **3+ hand spot-checks**: `set_handicap` (Assche/Busta, §3), `total_sets`
  (Assche/Busta, §3), `match_total_games` (Rublev/Skatov, §3), plus the 4
  synthetic `set_games`/`set_winner` code-level checks (§3) — 7 total.

## 6. Drops — full decomposition

**`no fixture` (675 atp / 205 wta, 100% expected):** Polymarket's bridge
covers a much broader date window (2-day BQ lookback across many
tournaments) than the 9/14 fixtures Optic's narrow default-horizon fetch
returned for "now" — these are markets for *other* real matches genuinely
outside this run's schedule, not resolution failures on any fixture we
actually have. (Sample cross-check: `atp-` bridge slug-date histogram spans
07-20 through 07-24+ across dozens of tournaments; only the 9 matches this
run's Optic fetch covers ever appear in the `resolved` list.)

**`non-game-line` / unparsed (89 atp / 35 wta) — both fully explained,
matches the brief's expected drop categories exactly:**

| bucket | atp | note |
|---|---|---|
| doubles (`A/B vs C/D`, slash-joined names) | 63 | expected — tennis rescue is singles-only by design |
| `"<Tournament>: Completed Match: A vs B"` (yes/no) | 26 | expected — no recognizer, no Optic equivalent to bind to |

(WTA breaks down the same way at smaller scale — not re-tabulated, same two
buckets account for all 35.) **Best-of-5 Set 3/4 forms**: not observed in
either bridge this snapshot (best-of-5 is Grand-Slam-only and none is in
season) — the rules correctly return `None` for `set_num` ∉ {1,2} by
construction (`tennis_set_games_rule`/`tennis_set_winner_rule`), verified by
code inspection since no live example existed to exercise it.

**`dropped (optic didn't price)` (12 atp / 18 wta) — 100% attributable to
the 1–2 `is_live` fixtures each league had this run** (§0, §2) — a pipeline-
level pre-game-only policy, not a tennis-matcher defect.

## 7. Exceptions

None. `grep -ni "traceback|exception"` on both `.err` logs (excluding the
pre-existing, tennis-unrelated `reconcile:` Kalshi/PX informational lines):
zero matches. Both `mappers.run` invocations exited 0.

## Caveats / follow-ups

- `set_games` (1st/2nd) and `set_winner` (1st/2nd) have **zero live
  Polymarket singles inventory** for ATP or WTA as of this snapshot (only
  doubles markets exist for these question shapes right now) — validated at
  the code level (§3) instead of via a live stamp. Re-run this same fetch
  once Polymarket lists a singles 1st/2nd-set market (or once a Slam is in
  season, if that's a market-availability driver) to get a live end-to-end
  example.
- The collision guard likewise has no real same-surname ATP/WTA fixture to
  observe in this window (§4) — validated synthetically. Worth a periodic
  re-check as the tour calendar rotates through players who could collide
  (e.g. two Martinezes, two Garcias).
- `config/atp/team_aliases.toml` and `config/wta/team_aliases.toml` are
  auto-rewritten by `mappers.tennis_bootstrap` on every `mappers.run` call
  (by design, per its docstring) — both were reverted via `git checkout --`
  after this session's analysis so the tree stays clean; any future
  automated validation run should do the same if it must stay strictly
  read-only.

## Files

- Data: `data/2026-07-23/16_30/{polymarket_markets.jsonl,optic_fixtures_odds.jsonl}` (gitignored; wta overwrote atp's optic file in-place, both already analyzed before the overwrite).
- Mapper output: `/tmp/tennis_{atp,wta}.json` + `.err` (scratch, not committed).
