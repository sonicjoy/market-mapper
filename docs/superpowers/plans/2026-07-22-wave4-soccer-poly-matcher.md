> Historical. Tip/console references are retired; see CLAUDE.md.

# Wave 4 — Soccer Polymarket matcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Polymarket recognizer rules + configs so poly soccer combo legs stamp onto every OpticOdds soccer market optic prices, across the parity soccer leagues (EPL, WORLD_CUP) and the expansion soccer leagues (MLS, LIGA_MX, UCL) — wiring parity + expansion of the sport together, validating on the in-season members (MLS/Liga MX/UCL).

**Architecture:** Reuse the frozen Phase-3 `(Scope,SideMode)` `build_rows` dispatch unchanged. Add soccer recognizer functions to `mappers/exchanges/polymarket.py` and a shared soccer `market_rules` tuple that each soccer league's `PolymarketConfig` references. Expansion leagues additionally get a new `OpticConfig` (from the optic probe) + `LeagueConfig` with `KALSHI=None`, registered in `mappers/run.py`. Two dormant SideModes (`THREE_WAY_FIXED`, `YESNO`) go live for the first time.

**Tech Stack:** Python, mmmapper `mappers/` package. Tests: `.venv/bin/python -m pytest tests/mappers/` (NO poetry). Lint: `.venv/bin/python -m ruff check --fix`.

## Global Constraints

- Byte-identical golden gate: existing MLB / tennis golden outputs MUST NOT change; full `tests/mappers/` stays green; no test dropped.
- `build_rows` dispatch is FROZEN — new leagues/forms add recognizer rules + config only, never editing the dispatch.
- Flip-safety: side is ALWAYS bound to the outcome label or the entity named in the question, never an array index; a market that cannot resolve both complementary sides drops whole.
- Never invent a mapping optic did not price — a poly leg stamps onto an existing optic row or drops.
- Parity target = poly-offered forms ∩ optic table_types, per league. Build only forms present in BOTH.
- BQ probes are bounded + reported; optic probes hit the optic API (`fetch.optic`).
- Ruff clean on changed lines (pre-existing HEAD errors out of scope). mypy/pyright import-resolution false-positives for `mappers.*` are known and ignorable.
- Git trailer on every commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## Mappable soccer forms (from the poly form histogram + WORLD_CUP OpticConfig ceiling)

Build recognizers for these (poly question form → optic market_id → SideMode):

| poly question form | example | optic market_id | internal MarketType | SideMode |
|---|---|---|---|---|
| full game total | `A vs. B: O/U 2.5` | `total_goals` | GAME_TOTAL | OVER_UNDER (GAME) |
| team total | `A vs. B: A O/U 1.5` | `team_total` | TEAM_TOTAL | OVER_UNDER (TEAM) |
| spread | `Spread: A (-1.5)` | `asian_handicap` | POINT_SPREAD | SPREAD_TEAM |
| 3-way ML — team win | `Will A win on 2026-07-22?` | `moneyline` (3-way) | MONEYLINE_3WAY | THREE_WAY_FIXED |
| 3-way ML — draw | `Will A vs. B end in a draw?` | `moneyline` (3-way) | MONEYLINE_3WAY | THREE_WAY_FIXED (`_TIE`) |
| 1st-half total | `A vs. B: 1st Half O/U 1.5` | `1st_half_total_goals` | FIRST_HALF_TOTAL | OVER_UNDER (GAME) |
| 1st-half winner | `A leading at halftime?` | `1st_half_moneyline` (3-way) | FIRST_HALF_WINNER_3WAY | THREE_WAY_FIXED |
| 1st-half draw | `A vs. B: Draw at halftime?` | `1st_half_moneyline` (3-way) | FIRST_HALF_WINNER_3WAY (`_TIE`) | THREE_WAY_FIXED |
| BTTS | `A vs. B: Both Teams to Score` | `both_teams_to_score` | BTTS | YESNO (GAME) |
| 1st-half BTTS | `A vs. B: Both Teams to Score in First Half` | `1st_half_both_teams_to_score` | FIRST_HALF_BTTS | YESNO (GAME) |
| player goals (WC) | `Player: 1+ goals` | `player_goals` | PLAYER_GOALS | YESNO_AS_OU (PLAYER) |

### Recognizer contract (verified against `polymarket.py`)

- Each recognizer has signature `def rule(question: str, cfg: PolymarketConfig) -> ParsedMarket | None` (type alias `MarketRule`). It reads `cfg.question_style` for name normalization via `_norm_name(name, cfg.question_style)`. Tests must call `rule(question, cfg)` with a soccer `PolymarketConfig`.
- `parse_question(question, cfg)` takes the `PolymarketConfig` (NOT a rules tuple); it iterates `cfg.market_rules` and returns the first non-None. Tests parse via a config whose `market_rules=soccer_market_rules`.
- `ParsedMarket` fields: `market_type, team_a, team_b, side_mode, entity, line, date, fixed_side_team, affirmative_label`. `date` is injected by the pipeline from the slug — recognizers do NOT set it.
- `THREE_WAY_FIXED` contract: emits ONLY the affirmative outcome (label `affirmative_label`, default `"yes"`) as ONE row; `fixed_side_team=<team>` → that team's abbrev, `fixed_side_team=None` → `_TIE` (draw). The complementary "No" outcome does not emit — this is the documented single-sided exception to the two-sided flip-safety rule.
- `PolymarketConfig` fields: `slug_prefix, optic_league_id, market_types (dict[str,MarketType]), question_style, market_rules`. Every league config (Tasks 6–7) must set all of them.
- `question_style` is `Literal["mlb_suffix", "tennis_prefix"]`. Soccer likely uses `"mlb_suffix"` (the `A vs. B` full-name form); if Task-1 finds it insufficient, extend the Literal with a new soccer style.

Deliberately DROPPED (optic does not price in the wired config — confirmed unmappable unless the Task-1 optic probe finds otherwise): exact_score, team_1h_total, team_2h_total, game_2h_total, to_score_first, 2h_winner, 2h_draw, neither_first, player assists/shots. Task 1 probes whether optic prices `correct_score` / 2nd-half / team-half so these can be revisited; if found, they become a follow-up wave, NOT this one.

## File Structure

- `mappers/exchanges/polymarket.py` — add soccer recognizer functions + a `soccer_market_rules` builder. One responsibility: turn a soccer question string into a `ParsedMarket`. ~11 small recognizers + shared helpers.
- `mappers/leagues/epl.py`, `mappers/leagues/world_cup.py` — add `POLYMARKET` config referencing the shared soccer rules (parity leagues; `OpticConfig` already exists).
- `mappers/leagues/mls.py`, `mappers/leagues/liga_mx.py`, `mappers/leagues/ucl.py` — NEW league modules (expansion): `OpticConfig` from probe + `PolymarketConfig` + `LeagueConfig` with `KALSHI=None`.
- `mappers/leagues/__init__.py`, `mappers/run.py` — register the 3 new leagues in `LEAGUES`.
- `tests/mappers/test_polymarket_soccer.py` — NEW: unit test per recognizer + dormant-mode live-question tests.
- `.superpowers/sdd/wave-4-probe-findings.md` — Task 1 output.

---

### Task 1: Optic + poly soccer probe

**Files:**
- Create: `.superpowers/sdd/wave-4-probe-findings.md`

**Interfaces:**
- Produces: the findings file that finalizes every later task's exact strings — real poly question templates per soccer league, the optic `market_id` + `selection` + `points` shapes optic returns for a live soccer fixture, team-name agreement (poly `question` names vs optic `home_team`/`away_team`), and a yes/no on whether optic prices `correct_score` / 2nd-half / team-half (the dropped forms).

- [ ] **Step 1: Enumerate optic's true soccer market ceiling.** For a live MLS fixture and a live Liga MX fixture, fetch all odds and list every distinct `market_id` optic returns (not just the wired table_types). Command:

```bash
cd /Users/victor-cristianpopa/Code/mmmapper
GCP_PROJECT=marketmaking-test .venv/bin/python -m fetch.optic --league mls --out-dir /tmp/wave4probe/mls 2>&1 | tail -5
python - <<'PY'
import json, collections
c = collections.Counter()
for line in open("/tmp/wave4probe/mls/optic_fixtures_odds.jsonl"):
    row = json.loads(line)
    for odd in row.get("odds", []):
        c[odd.get("market_id","")] += 1
for m, n in c.most_common():
    print(f"{n:6d}  {m}")
PY
```

Expected: a ranked list of optic soccer `market_id`s. Record it. Note presence/absence of `correct_score`, `2nd_half_*`, team-half markets.

- [ ] **Step 2: Pull real poly question templates per soccer league.** Bounded BQ (report bytes; ~17MB):

```bash
bq query --project_id=rs-marketmaking --use_legacy_sql=false --format=prettyjson '
SELECT SPLIT(slug,"-")[OFFSET(0)] lp, question, outcome_label, slug
FROM `marketmaking-test.raw_ingestion_us.polymarket_position_token_bridge`
WHERE SPLIT(slug,"-")[OFFSET(0)] IN ("mls","mex","ucl")
  AND (question LIKE "%O/U%" OR question LIKE "Will %" OR question LIKE "%Both Teams%"
       OR question LIKE "Spread:%" OR question LIKE "%halftime%")
ORDER BY lp, question LIMIT 400'
```

Record the exact templates + the `outcome_label` values (e.g. Over/Under, Yes/No) for each form. Confirm the `Will A win on DATE?` / `end in a draw?` triple and its `outcome_label`s.

- [ ] **Step 3: Team-name agreement.** For 5 fixtures present in BOTH the optic pull and the bridge, compare poly `question` team names to optic `home_team`/`away_team`. Record whether `_norm_name` (mlb_suffix containment) matches, or a new `question_style` is needed. Write all findings to `.superpowers/sdd/wave-4-probe-findings.md`.

- [ ] **Step 4: Commit the findings file.**

```bash
git add .superpowers/sdd/wave-4-probe-findings.md
git commit -m "chore(wave4): soccer optic+poly probe findings"
```

---

### Task 2: Soccer OVER_UNDER + SPREAD recognizers (reuse-mode forms)

**Files:**
- Modify: `mappers/exchanges/polymarket.py` (add recognizers)
- Test: `tests/mappers/test_polymarket_soccer.py` (create)

**Interfaces:**
- Consumes: `ParsedMarket`, `SideMode`, existing `_norm_name` / `_player_prop_rule` helpers, `MarketType.GAME_TOTAL/TEAM_TOTAL/POINT_SPREAD/FIRST_HALF_TOTAL` from `market_types.py`. Exact question templates + `outcome_label`s from Task-1 findings.
- Produces: recognizer functions `soccer_total_rule`, `soccer_team_total_rule`, `soccer_spread_rule`, `soccer_first_half_total_rule` (each `question -> ParsedMarket | None`), returning `ParsedMarket` with the SideMode/scope from the mappable-forms table above.

- [ ] **Step 1: Write failing tests** for the four recognizers using the EXACT question strings from Task-1 findings. Example (finalize strings from findings):

```python
def test_soccer_full_total():
    pm = soccer_total_rule("Austin FC vs. Seattle Sounders FC: O/U 2.5")
    assert pm.market_type == MarketType.GAME_TOTAL
    assert pm.side_mode == SideMode.OVER_UNDER
    assert pm.scope == Scope.GAME
    assert pm.line == 2.5
    assert pm.team_a == "Austin FC" and pm.team_b == "Seattle Sounders FC"

def test_soccer_team_total_binds_named_team():
    pm = soccer_team_total_rule("Austin FC vs. Seattle Sounders FC: Austin FC O/U 1.5")
    assert pm.market_type == MarketType.TEAM_TOTAL
    assert pm.entity == "Austin FC"  # TEAM scope entity is the named team
    assert pm.line == 1.5

def test_soccer_spread_signs_named_team():
    pm = soccer_spread_rule("Spread: Austin FC (-1.5)")
    assert pm.market_type == MarketType.POINT_SPREAD
    assert pm.side_mode == SideMode.SPREAD_TEAM
    assert pm.entity == "Austin FC" and pm.line == -1.5

def test_soccer_first_half_total():
    pm = soccer_first_half_total_rule("Austin FC vs. Seattle Sounders FC: 1st Half O/U 1.5")
    assert pm.market_type == MarketType.FIRST_HALF_TOTAL
    assert pm.line == 1.5

def test_soccer_team_total_not_matched_by_full_total_rule():
    # guard ordering: the team-total question must NOT be captured by the full-total rule
    assert soccer_total_rule("Austin FC vs. Seattle Sounders FC: Austin FC O/U 1.5") is None
```

- [ ] **Step 2: Run to verify fail.** `Run: .venv/bin/python -m pytest tests/mappers/test_polymarket_soccer.py -x` → FAIL (rules undefined).

- [ ] **Step 3: Implement the four recognizers** matching Task-1 templates. Full-total rule must reject team-total strings (a capitalized team token before `O/U`), mirroring MLB's `mlb_total_rule` guard. Team-total binds `entity` to the named team; spread signs the line on the named team (reuse the MLB spread parsing). First-half-total parses the `1st Half O/U N` suffix.

- [ ] **Step 4: Run to verify pass.** `Run: .venv/bin/python -m pytest tests/mappers/test_polymarket_soccer.py -x` → PASS.

- [ ] **Step 5: Full suite + lint.** `Run: .venv/bin/python -m pytest tests/mappers/ && .venv/bin/python -m ruff check --fix mappers/exchanges/polymarket.py tests/mappers/test_polymarket_soccer.py` → all green, goldens unchanged.

- [ ] **Step 6: Commit.** `git add -A && git commit -m "feat(poly/soccer): total, team-total, spread, 1st-half-total recognizers"`

---

### Task 3: Soccer BTTS + 1st-half-BTTS recognizers (first live YESNO)

**Files:**
- Modify: `mappers/exchanges/polymarket.py`
- Test: `tests/mappers/test_polymarket_soccer.py`

**Interfaces:**
- Consumes: `SideMode.YESNO`, `MarketType.BTTS`, `MarketType.FIRST_HALF_BTTS`. Task-1 `outcome_label` values for BTTS (expect Yes/No).
- Produces: `soccer_btts_rule`, `soccer_first_half_btts_rule`.

- [ ] **Step 1: Write failing tests** — BTTS parses to `SideMode.YESNO`, GAME scope, and (critically, first live YESNO exercise) `build_rows` emits two rows Yes→"yes"/No→"no" bound to outcome labels. Include a `build_rows` integration test that feeds the `ParsedMarket` + a synthetic 2-outcome poly market and asserts the two rows' sides.

```python
def test_soccer_btts_parse():
    pm = soccer_btts_rule("Austin FC vs. Seattle Sounders FC: Both Teams to Score")
    assert pm.market_type == MarketType.BTTS
    assert pm.side_mode == SideMode.YESNO and pm.scope == Scope.GAME

def test_soccer_btts_first_half_parse():
    pm = soccer_first_half_btts_rule(
        "Austin FC vs. Seattle Sounders FC: Both Teams to Score in First Half")
    assert pm.market_type == MarketType.FIRST_HALF_BTTS

def test_btts_first_half_not_captured_by_plain_btts():
    assert soccer_btts_rule(
        "A vs. B: Both Teams to Score in First Half") is None  # ordering guard
```

- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** both recognizers; plain-BTTS rule must reject the `in First Half` variant (ordering guard).
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Full suite + lint** (goldens unchanged).
- [ ] **Step 6: Commit.** `git commit -m "feat(poly/soccer): BTTS + 1st-half-BTTS recognizers (first live YESNO)"`

---

### Task 4: Soccer 3-way moneyline recognizers (first live THREE_WAY_FIXED)

**Files:**
- Modify: `mappers/exchanges/polymarket.py`
- Test: `tests/mappers/test_polymarket_soccer.py`

**Interfaces:**
- Consumes: `SideMode.THREE_WAY_FIXED`, `MarketType.MONEYLINE_3WAY`, `MarketType.FIRST_HALF_WINNER_3WAY`, the `fixed_side_team` / `_TIE` mechanics of `build_rows` THREE_WAY_FIXED.
- Produces: `soccer_ml_team_win_rule`, `soccer_ml_draw_rule`, `soccer_first_half_leader_rule`, `soccer_first_half_draw_rule`.

- [ ] **Step 1: Write failing tests** for the poly 3-way encoding. `Will A win on DATE?` → affirmative row for team A on `moneyline` 3-way; `Will A vs. B end in a draw?` → affirmative row `_TIE`; `A leading at halftime?` → `1st_half_moneyline` team A; `A vs. B: Draw at halftime?` → `1st_half_moneyline` `_TIE`. Include a `build_rows` integration test asserting each emits exactly ONE affirmative row with the correct `fixed_side_team`/`_TIE`. Use EXACT strings + date format from Task-1 findings.

```python
def test_soccer_ml_team_win_binds_named_team():
    pm = soccer_ml_team_win_rule("Will Austin FC win on 2026-07-22?")
    assert pm.market_type == MarketType.MONEYLINE_3WAY
    assert pm.side_mode == SideMode.THREE_WAY_FIXED
    assert pm.fixed_side_team == "Austin FC"

def test_soccer_ml_draw_is_tie():
    pm = soccer_ml_draw_rule("Will Austin FC vs. Seattle Sounders FC end in a draw?")
    assert pm.market_type == MarketType.MONEYLINE_3WAY
    assert pm.fixed_side_team is None  # resolves to _TIE in build_rows

def test_first_half_leader_and_draw():
    assert soccer_first_half_leader_rule("Austin FC leading at halftime?").market_type \
        == MarketType.FIRST_HALF_WINNER_3WAY
    assert soccer_first_half_draw_rule(
        "Austin FC vs. Seattle Sounders FC: Draw at halftime?").market_type \
        == MarketType.FIRST_HALF_WINNER_3WAY
```

- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** the four recognizers. The team-win rule extracts the team before ` win on `; the draw rule extracts nothing (→ `_TIE`); the halftime-leader rule extracts the team before ` leading at halftime`. Flip-safety: the affirmative side is the question-named team — never an index.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Full suite + lint** (goldens unchanged).
- [ ] **Step 6: Commit.** `git commit -m "feat(poly/soccer): 3-way ML + 1st-half-winner recognizers (first live THREE_WAY_FIXED)"`

---

### Task 5: Player-goals recognizer + shared `soccer_market_rules` tuple

**Files:**
- Modify: `mappers/exchanges/polymarket.py`
- Test: `tests/mappers/test_polymarket_soccer.py`

**Interfaces:**
- Consumes: `_player_prop_rule` (from Phase 3), `MarketType.PLAYER_GOALS`, `SideMode.YESNO_AS_OU`, `Scope.PLAYER`.
- Produces: `soccer_player_goals_rule` and `soccer_market_rules` — the ordered tuple of ALL soccer recognizers (ordering matters: most-specific first — team-total before full-total, 1st-half-BTTS before BTTS, draw rules before team-win, player-goals before anything). Later tasks reference `soccer_market_rules`.

- [ ] **Step 1: Write failing tests** — `Player: 1+ goals` → PLAYER_GOALS over 0.5 (N+ = over (N−0.5)); `2+ goals` → over 1.5. Assert `soccer_market_rules` is an ordered tuple and that a team-total question resolves to TEAM_TOTAL (not full-total) when parsed through the whole tuple via `parse_question`.

```python
def test_soccer_player_goals_ladder():
    pm = soccer_player_goals_rule("Achraf Hakimi: 1+ goals")
    assert pm.market_type == MarketType.PLAYER_GOALS and pm.line == 0.5
    assert soccer_player_goals_rule("Achraf Hakimi: 2+ goals").line == 1.5

def test_soccer_rules_ordering_team_total_wins():
    # cfg is a soccer PolymarketConfig whose market_rules=soccer_market_rules
    pm = parse_question("A vs. B: A O/U 1.5", soccer_cfg)
    assert pm.market_type == MarketType.TEAM_TOTAL
```

- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** `soccer_player_goals_rule` (reuse `_player_prop_rule`; only `goals`, NOT assists/shots) and assemble `soccer_market_rules` in the correct order.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Full suite + lint.**
- [ ] **Step 6: Commit.** `git commit -m "feat(poly/soccer): player-goals rule + ordered soccer_market_rules"`

---

### Task 6: Wire parity soccer leagues — EPL + WORLD_CUP

**Files:**
- Modify: `mappers/leagues/epl.py`, `mappers/leagues/world_cup.py`
- Test: `tests/mappers/test_polymarket_soccer.py`

**Interfaces:**
- Consumes: `soccer_market_rules`, existing `OpticConfig` (both leagues already have soccer optic table_types).
- Produces: `POLYMARKET = PolymarketConfig(market_rules=soccer_market_rules, question_style=<from Task-1>)` on both league modules.

- [ ] **Step 1: Write failing test** asserting `LEAGUES[League.EPL].POLYMARKET is not None` and that a WORLD_CUP player-goals question parses through its config.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** — add `POLYMARKET` config to both modules referencing `soccer_market_rules`; set `question_style` per Task-1 team-name finding.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Full suite + lint.**
- [ ] **Step 6: Commit.** `git commit -m "feat(poly/soccer): wire EPL + WORLD_CUP polymarket configs"`

---

### Task 7: Wire expansion soccer leagues — MLS, LIGA_MX, UCL (KALSHI=None)

**Files:**
- Create: `mappers/leagues/mls.py`, `mappers/leagues/liga_mx.py`, `mappers/leagues/ucl.py`
- Modify: `mappers/leagues/__init__.py`, `mappers/run.py`
- Test: `tests/mappers/test_polymarket_soccer.py`

**Interfaces:**
- Consumes: `soccer_market_rules`; the optic `market_id` list from Task-1 (to build each `OpticConfig.table_types`); `LeagueConfig` with `KALSHI=None` (the Optional path).
- Produces: three new league modules + registration in `LEAGUES` / `run.py` CLI choices.

- [ ] **Step 1: Write failing tests** — `League.MLS in LEAGUES`, `LEAGUES[League.MLS].KALSHI is None`, `LEAGUES[League.MLS].POLYMARKET is not None`, and its `OpticConfig.table_types` contains `total_goals`/`both_teams_to_score`/`moneyline` per Task-1.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement** the three modules (OpticConfig table_types from Task-1 optic probe, soccer PolymarketConfig, `LeagueConfig(KALSHI=None, ...)`), register in `__init__.py` `LEAGUES` and `run.py`. Verify NO unguarded `KALSHI.` access breaks (ledger M1: check `list_aliases.py:328`).
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Full suite + lint** (goldens unchanged; new leagues do not perturb existing outputs).
- [ ] **Step 6: Commit.** `git commit -m "feat(poly/soccer): wire MLS + LIGA_MX + UCL (poly-only, KALSHI=None)"`

---

### Task 8: Local validation run

**Files:** none (controller-run; findings appended to `.superpowers/sdd/wave-4-probe-findings.md`).

- [ ] **Step 1: Fetch + map** an in-season soccer league end-to-end:

```bash
cd /Users/victor-cristianpopa/Code/mmmapper
D=data/2026-07-22/$(printf '%02d_%02d' 20 00)   # <date>/<HH_MM> — pipeline parses as fetch_time
GCP_PROJECT=marketmaking-test .venv/bin/python -m fetch.optic --league mls --out-dir "$D"
GCP_PROJECT=marketmaking-test .venv/bin/python -m fetch.polymarket --out-dir "$D"
.venv/bin/python -m mappers.run "$D" --league mls --json > /tmp/wave4-mls.json
```

- [ ] **Step 2: Verify** stamps: count poly→optic soccer stamps by form; assert 0 market-type/line mismatches, over/under balance, and that `moneyline_3way` legs bind the correct selection (spot-check 3 fixtures against the source questions). Record counts + any mismatch in the findings file.
- [ ] **Step 3: Commit** the validation note.

## Self-Review

- **Spec coverage:** every mappable soccer form in the spec's histogram has a recognizer task (Tasks 2–5); parity leagues wired (Task 6); expansion leagues wired with `KALSHI=None` (Task 7); dormant modes first-exercised with `build_rows` integration tests (Tasks 3–4); optic ceiling + team-name norm resolved by probe (Task 1); local validation (Task 8). Dropped forms explicitly listed with the Task-1 rescue check for `correct_score`.
- **Placeholder scan:** exact question strings are deferred to Task-1 findings BY DESIGN (probe-first pattern) and every recognizer task instructs "use EXACT strings from Task-1 findings" with representative examples shown — not TBDs. Optic `market_id`s for expansion `OpticConfig` come from the Task-1 optic probe.
- **Type consistency:** `ParsedMarket` fields (`market_type`, `side_mode`, `scope`, `line`, `entity`, `team_a`, `team_b`, `fixed_side_team`) used consistently; `soccer_market_rules` is the single ordered tuple all soccer leagues reference.
