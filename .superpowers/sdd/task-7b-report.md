### Task 7b report: wire Liga MX + UCL (poly-only, KALSHI=None), cloned from MLS's Task 7a pattern

**Status:** complete, not blocked.

**Name-agreement check — methodology:**

Bounded BQ pull (`bq --project_id=rs-marketmaking query`, dry-run first):
`SELECT slug, question, outcome_label FROM
marketmaking-test.raw_ingestion_us.polymarket_position_token_bridge WHERE
SPLIT(slug,"-")[OFFSET(0)] IN ("mex","ucl")` — dry-run estimate **10,915,750
bytes (~10.9 MiB)**, matching the brief's ~10-17 MB expectation; actual query
returned **5,430 rows** (mex 1,530 / ucl 3,900). Team names were extracted
from the recognized soccer question forms (the module's own compiled regexes
— `_Q_SOCCER_TOTAL`, `_Q_SOCCER_TEAM_TOTAL`, `_Q_SOCCER_ML_TEAM_WIN`,
`_Q_SOCCER_ML_DRAW`, `_Q_SOCCER_FIRST_HALF_LEADER`, etc. — not a naive regex),
giving 18 distinct Liga MX poly names and 41 distinct UCL poly names.

Optic side: a throwaway `/tmp` script (`fetch.optic._init_headers` +
`fetch.optic.get_fixtures`, `GCP_PROJECT=marketmaking-test`) pulled
`fixtures/active` for `mexico_-_liga_mx` (18 fixtures → 18 distinct clubs, a
full Apertura round matching Liga MX's whole 18-club roster) and
`uefa_-_champions_league` (14 fixtures → 28 distinct clubs — the Q2-second-
leg/Q3 window visible at probe time; UCL's qualifying rounds cycle far more
clubs than are visible in one active-fixture snapshot, since eliminated ties
drop off the endpoint).

Applied mmmapper's exact `_norm_name(..., "mlb_suffix")` / containment check
(`a == b or a in b or b in a`) pairwise. For Liga MX every poly name had an
unambiguous 1:1 optic counterpart (18 clubs both sides) so a plain
name×name cross-check was sufficient. For UCL, clubs recur under similar-
looking short names (e.g. "KÍ" vs "KF Víkingur" are two DIFFERENT clubs), so a
naive cross-check produces false positives on short abbreviations via
substring collision (a 2-letter poly token like "ki" is a substring of
several unrelated Optic names). Verified each UCL alias candidate against the
SAME actual fixture (matching opponent name + same/adjacent date, using the
poly bridge's own `<A> vs. <B>` question text against the live Optic
fixture's home/away pair) rather than trusting cross-product name similarity
alone. One draft candidate ("FC Thun" → "FC Thun Berner Oberland") was caught
by its own regression test as ALREADY resolving via plain containment
(poly's name is a prefix-substring of Optic's) and was dropped before
landing — a real example of the "over-eager alias" failure mode this
verification step exists to catch.

**Name-check results per league:**

*Liga MX (`liga_mx.py`) — 4 mismatches found, all aliased, high confidence
(18/18 clubs cross-referenced, no ambiguity):*
| poly name | optic name |
|---|---|
| Atlético San Luis | Atlético de San Luis |
| CF América | Club de Fútbol América |
| Pumas de la UNAM | Pumas de la Universidad Nacional Autonoma de Mexico |
| Tigres de la UANL | Club Tigres de la Universidad Autónoma de Nuevo León |

*UEFA Champions League (`ucl.py`) — 12 mismatches found and aliased (all
confirmed via same-fixture cross-check, not name-similarity guesswork):*
| poly name | optic name |
|---|---|
| Aarhus GF | Aarhus Gymnastikforening |
| Ararat-Armenia FA | Ararat-Armenia FC |
| Qairat FK | Kairat Almaty |
| AS Omónoia Leukosías | AC Omonia Nicosia |
| KF Egnatia Rrogozhinë | KS Egnatia Rrogozhinë |
| SK Puntigamer Sturm Graz | SK Sturm Graz |
| Fenerbahçe SK | Fenerbahçe Spor Kulübü |
| Universitatea Craiova CS | Universitatea Craiova 1948 Club Sportiv |
| MH Hapoel Be'er Sheva | Hapoel Be'er Sheva FC |
| KF Víkingur | Víkingur Reykjavík |
| SK Iberia 1999 | FC Iberia 1999 |
| Kuopion PS | Kuopion Palloseura |

13 UCL poly clubs were **not** aliased — no live Optic fixture data was
available at probe time to confirm their exact Optic name (their qualifying
ties had already concluded and dropped off the `fixtures/active` feed): ETO
FC, FC Atert Bissen, FC Drita, FC Flora, FC Petrocub Hînceşti, FK Borac Banja
Luka, FK ML Viciebsk, FK Sutjeska Nikšić, FK Vardar Skopje, Floriana FC,
Inter Club d'Escaldes, The New Saints FC, Tre Fiori FC. These fail SAFE
(market drops, never mismaps) — documented as an open coverage gap in
`ucl.py`'s docstring, not treated as "resolved." 4 more UCL clubs already
reconcile via plain containment and were deliberately left OUT of
`TEAM_NAME_ALIASES` (confirmed, not just assumed): "KÍ"→"KÍ Klaksvík", "FK
Crvena zvezda"→"FK Crvena zvezda Beograd", "Górnik Zabrze"→"KS Górnik
Zabrze", "FK Kauno Žalgiris"→"FK Kauno Zalgiris" (diacritic-only), "FC
Thun"→"FC Thun Berner Oberland" (the caught-and-dropped draft above).

**Files changed:**
- `mappers/leagues/liga_mx.py` — new (cloned from `mls.py`): `OPTIC`
  (`league_id="mexico_-_liga_mx"`, same 9-key soccer `table_types`),
  `TEAM_NAME_ALIASES` (4 entries), `POLYMARKET` (`slug_prefix="mex"`,
  `SOCCER_MARKET_TYPES`, `question_style="mlb_suffix"`,
  `soccer_market_rules`), `LEAGUE` (`KALSHI=None, PX=None`).
- `mappers/leagues/ucl.py` — new, same shape: `league_id=
  "uefa_-_champions_league"`, `slug_prefix="ucl"`, `TEAM_NAME_ALIASES` (12
  entries).
- `mappers/run.py` — `liga_mx`/`ucl` imports added (alphabetized into the
  existing import line); `League.LIGA_MX: liga_mx.LEAGUE` and `League.UCL:
  ucl.LEAGUE` added to `LEAGUES`; updated the now-stale comment above
  `--league` (it previously said "wnba/mls/liga_mx/ucl/ufc" have no module —
  now only wnba/ufc are unwired).
- `tests/mappers/test_polymarket_soccer.py` — `import pytest` added; 4
  registry tests parametrized over `[League.LIGA_MX, League.UCL]`
  (`test_expansion_league_in_leagues`, `_kalshi_is_none`,
  `_polymarket_config_present`, `_optic_table_types_covers_9_soccer_market_
  types`), 2 slug/optic_league_id tests (one per league), and per-league
  alias-overlay test blocks mirroring MLS's pattern
  (`test_{liga_mx,ucl}_alias_resolves_fixture` /
  `_alias_without_scope_does_not_match`, parametrized over each league's
  alias pairs; `_alias_regression_normal_franchise_still_matches` (Liga MX:
  Atlante FC↔Atlante FC; UCL: parametrized over FK Crvena zvezda + FC Thun,
  both already-OK-without-alias cases); `_alias_genuinely_absent_team_still_
  drops` per league) — 47 new tests total.

**Test counts:**
- `.venv/bin/python -m pytest tests/mappers/test_polymarket_soccer.py -x -q`
  → `114 passed` (67 pre-existing + 47 new).
- `.venv/bin/python -m pytest tests/mappers/ -q` → `490 passed, 11 skipped`
  (baseline 441 passed/7 skipped + 47 new explicit tests + 2 new
  auto-parametrized `test_output_order_covers_all_used_types[liga_mx]` /
  `[ucl]` passes = 490; + 4 new auto-parametrized skips —
  `test_kalshi_table_types_and_ignored_disjoint[liga_mx]`,
  `[ucl]` and `test_px_suffix_longest_first[liga_mx]`, `[ucl]` — = 11; no
  pre-existing test dropped or newly failing).

**Goldens unchanged (structural argument, identical to Task 7a):**
`gold_row()` extracts only the 12 non-polymarket fields; `attach_polymarket_
row` only ever stamps polymarket_* fields onto an already-existing optic row.
`_active_team_aliases` stays `{}` for every league whose `PolymarketConfig.
team_name_aliases` is the default empty dict (every league except MLS/Liga
MX/UCL) — behavior for EPL/WORLD_CUP/MLB/ATP/WTA/NBA/NCAAB/NFL/NHL is
unchanged by construction. No `data/` fetch directory was present in this
environment to run `scripts/check_gold.py` against real Liga MX/UCL bridge
rows (same limitation noted in prior task reports).

**Lint:** `.venv/bin/python -m ruff check --fix mappers/leagues/liga_mx.py
mappers/leagues/ucl.py mappers/run.py tests/mappers/test_polymarket_soccer.py`
→ clean except the **pre-existing** `run.py:4` E501 (module usage-line
docstring, untouched by this diff — confirmed via `git stash` that it's
present on the pre-task baseline too). `pyright` on the same files: the new
`liga_mx.py`/`ucl.py`/`run.py` changes are clean; `test_polymarket_soccer.py`
carries 32 `reportOptionalMemberAccess`/`reportArgumentType` findings on
`PolymarketConfig | None` narrowing — **confirmed pre-existing** (16 of these
already exist on the pre-task baseline from Task 7a's own MLS alias tests,
which access `cfg.team_name_aliases`/`cfg.question_style` without an
`assert cfg is not None` narrowing line; my new Liga MX/UCL tests mirror that
same established pattern, adding 16 more of the same kind). Not introduced by
this task in kind, only in count; the brief's required lint gate is
`ruff check --fix`, which is clean.

**Concerns:**
- UCL's alias coverage (12/25 real mismatches found) is genuinely partial —
  13 clubs from Q1/Q2 legs that had already concluded by probe time have no
  confirmed Optic name and are left unaliased. This is explicitly
  fail-safe (dropped market, never a wrong mapping) per the brief's mandate,
  but a follow-up re-probe once UCL reaches the group stage (a more stable,
  longer-lived fixture list) would likely close most of the remaining gap.
- The pre-existing `reportOptionalMemberAccess` pyright findings on the test
  file (see Lint) were not introduced by this task but were extended
  proportionally (same pattern as Task 7a's own tests) rather than fixed,
  since fixing them would mean touching the pre-existing MLS test functions
  (out of this task's explicit "do NOT change MLS" scope).
- `player_goals` in both leagues' `OPTIC.table_types` is dead weight on the
  poly side (poly never asks the "N+ goals" ladder for mls/mex/ucl — 0/8,330
  bridge rows per wave-4 probe section C) — kept per the brief's explicit
  "clone the template" instruction; harmless, same rationale as MLS.
- One genuine near-miss caught during this task: an earlier draft alias
  ("FC Thun" → "FC Thun Berner Oberland") was NOT actually needed — plain
  containment already resolves it — and was caught by its own
  `test_ucl_alias_without_scope_does_not_match` parametrized case failing
  (the assertion that it does NOT match without the overlay was false). This
  is direct evidence the verification tests are doing real work, not just
  mirroring the intended answer.
