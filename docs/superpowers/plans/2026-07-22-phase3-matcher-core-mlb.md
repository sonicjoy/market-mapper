> Historical. Tip/console references are retired; see CLAUDE.md.

# Phase 3 — Matcher-core (Scope,Shape) refactor + shared taxonomy + MLB full taxonomy

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Generalize `mappers/exchanges/polymarket.py` from a 2-kind (moneyline/total) parser to a config-driven `(Scope,Shape)`-dispatched matcher at parity with crypto.com, land all shared-taxonomy changes the later phases need, and wire MLB's full optic-priced surface (player props, run-line spread, team-total, 1st-inning total).

**Architecture:** A per-league `PolymarketConfig.market_rules` (ordered recognizers: `question → ParsedMarket`) feeds a shape-dispatched `build_rows`. Side is always bound to the outcome label or the entity named in the question (flip-safety guard #1). MLB moneyline+total and tennis moneyline output stay byte-identical.

**Tech stack:** Python, mmmapper `mappers/`. Test runner: `.venv/bin/python -m pytest` (NO poetry, NO bare python).

## Global Constraints

- Existing behavior byte-identical: full `tests/mappers/` stays green with NO drop (baseline **324 passed / 5 skipped** at branch head `2ae4d5f`). MLB ml/total + tennis ml golden outputs unchanged.
- Flip-safety guards #1–#4 hold and extend to every new shape. Side bound to label/entity, never index. A market that can't cleanly resolve its sides is dropped whole.
- Poly rows STAMP onto an existing optic `row_key` or are dropped — `(market_type, entity, normalize_line(line), side)` must equal optic's for that market. Merge key = `(league, start_date, home, away, market_type, entity, normalize_line(line), side, grouping_key=None)`.
- Additive shared changes only (new enum members / MarketTypes / an optional field default) — no behavior change for other exchanges.
- `.venv/bin/python -m ruff check --fix` clean before each commit.

---

### Task 1: Shared-taxonomy additions (mechanical, additive, unblocks phases 4–6)

**Files:**
- Modify: `mappers/market_types.py` (add MLB player-prop + 1st-inning MarketTypes)
- Modify: `mappers/leagues/__init__.py` (add `League` members + `SPORT_MAP` + `Sport.MMA`)
- Modify: `mappers/pipeline.py` (`LeagueConfig.KALSHI` → optional + guard the kalshi pass)
- Test: `tests/mappers/test_market_types.py` (or nearest existing), `tests/mappers/` full run

**Interfaces produced (later phases consume):**
- New `MarketType`s: `PLAYER_HOME_RUNS`, `PLAYER_STRIKEOUTS`, `PLAYER_HITS`, `PLAYER_BASES`, `PLAYER_HITS_RUNS_RBIS` — all `(Scope.PLAYER, Shape.OVER_UNDER)`. `FIRST_INNING_TOTAL` — `(Scope.GAME, Shape.TOTAL)`. (Enum string values fixed in Task 3 from the optic probe; use `player_home_runs`, `player_strikeouts`, `player_hits`, `player_bases`, `player_hits_runs_rbis`, `first_inning_total` pending confirmation.)
- New `League` members: `WNBA` (`Sport.BASKETBALL`), `MLS`, `LIGA_MX`, `UCL` (`Sport.SOCCER`), `UFC` (`Sport.MMA`). Add `Sport.MMA` to the `Sport` enum. Add each to `SPORT_MAP`.
- `LeagueConfig.KALSHI: KalshiConfig | None = None` (was required-positional). The pipeline kalshi pass must be guarded on `cfg.KALSHI is not None` (mirror the existing PX/CRYPTO guards).

- [ ] **Step 1:** Add the MarketTypes (mirror the existing PLAYER_* block formatting). Add `Sport.MMA` + the 5 `League` members + `SPORT_MAP` rows.
- [ ] **Step 2:** In `mappers/pipeline.py`, change `LeagueConfig.KALSHI` to `KalshiConfig | None = None`; find the kalshi pass in `run()` and wrap it in `if cfg.KALSHI is not None:` (grep for the existing `if cfg.PX`/`if cfg.CRYPTO` guards and match the pattern). Confirm no other code assumes `cfg.KALSHI` is non-None (grep `\.KALSHI`).
- [ ] **Step 3:** Add a test asserting the new League members resolve in `SPORT_MAP` and the new MarketTypes have the intended `(scope, shape)`.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/mappers/ -q` → 324 passed / 5 skipped (no drop). ruff --fix.
- [ ] **Step 5:** Commit `feat(polymarket): shared taxonomy — MLB prop + 1st-inning MarketTypes, MMA sport, WNBA/soccer/UFC leagues, optional KALSHI`.

**Note (registry guard):** if any test/registry iterates `League` expecting a matching `mappers/leagues/<x>.py` module, adding members for not-yet-built leagues will fail. If so, gate that registry on modules that exist (or add the members per-phase instead) — report as a BLOCKED/⚠️ if discovered, do NOT stub fake modules.

---

### Task 2: Core `(Scope,Shape)` refactor of the matcher (behavior-preserving)

**Files:**
- Modify: `mappers/exchanges/polymarket.py` (the whole parse/build core)
- Modify: `mappers/pipeline.py` (poly pass: adapt to the new `parse_question`/`build_rows` signatures if they change)
- Test: `tests/mappers/test_polymarket.py`, `tests/mappers/test_polymarket_pipeline.py`, `tests/mappers/test_polymarket_*_integration.py`

**Interfaces produced (Task 3 + phases 4–6 consume):**
```python
class SideMode(Enum):
    TEAM_LABEL      = "team_label"       # MONEYLINE: each outcome label is a team name → fixture abbrev
    SPREAD_TEAM     = "spread_team"       # SPREAD: label=team → abbrev; named team carries the signed line, other negated
    OVER_UNDER      = "over_under"        # TOTAL/OVER_UNDER: Over→"over", Under→"under"
    YESNO_AS_OU     = "yesno_as_ou"       # player/team Yes-No-at-threshold: Yes→"over", No→"under"
    YESNO           = "yesno"             # GAME yes/no (BTTS): Yes→"yes", No→"no"
    THREE_WAY_FIXED = "three_way_fixed"   # only the affirmative outcome emits; side = parsed.fixed_side (team abbrev or _TIE); other outcome dropped

@dataclass(frozen=True)
class ParsedMarket:
    market_type: MarketType
    team_a: str | None            # normalized team names for fixture matching (GAME/TEAM markets); None for player-only forms
    team_b: str | None
    side_mode: SideMode
    entity: str | None = None     # PLAYER: normalize_player_name(player); TEAM-scope: normalized team NAME (build_rows resolves→abbrev); GAME: None
    line: float | None = None     # unsigned threshold, signed spread, or None
    date: str | None = None       # match date parsed from question when present ("Will X win on YYYY-MM-DD?")
    fixed_side_team: str | None = None   # THREE_WAY_FIXED: normalized team name whose Yes maps to that team's abbrev; None + THREE_WAY_FIXED ⇒ _TIE (draw)
    affirmative_label: str = "yes"       # THREE_WAY_FIXED/anytime-over-only: which outcome_label emits (default "yes")

# A market rule recognizes a question form and produces a ParsedMarket (or None).
MarketRule = Callable[[str, "PolymarketConfig"], ParsedMarket | None]
```
`PolymarketConfig` gains `market_rules: tuple[MarketRule, ...] = ()`. Existing `market_types: dict[str,MarketType]` and `question_style` are retained (rules reference them). `parse_question(question, cfg)` iterates `cfg.market_rules`, first non-None wins; returns `ParsedMarket | None`. If `market_rules` is empty, fall back to the current moneyline/total/tennis logic (so MLB/tennis configs keep working until Task 3 moves them to rules — OR migrate them to rules in this task; see Step 3).

`build_rows(market, parsed, *, home, away, home_name, away_name, start_date, cfg, league)` dispatches on `parsed.side_mode` (and `parsed.market_type.scope` for entity resolution):
- **TEAM_LABEL** (moneyline): 2 outcomes, each label→team abbrev via `_name_match`; require `{home,away}`; else drop.
- **SPREAD_TEAM**: each label→abbrev; the abbrev == the team named in the question carries `parsed.line`, the other `-parsed.line`; drop if not exactly the two teams.
- **OVER_UNDER / YESNO_AS_OU**: 2 outcomes → over/under; `entity` = (PLAYER) `parsed.entity`; (TEAM) resolve `parsed.entity` team-name→abbrev; (GAME) None; `line=parsed.line`.
- **YESNO** (BTTS): 2 outcomes → yes/no; entity per scope; `line=None`.
- **THREE_WAY_FIXED**: emit ONE row for `parsed.affirmative_label`; side = `parsed.fixed_side_team`→abbrev, or `_TIE` if `fixed_side_team is None`; drop the other outcome; `market_type` must be a `Shape.THREE_WAY` type. Use the `_TIE`/`TIE_SIDE` literal from `mappers/shared.py`.

Row stamp fields unchanged (`_stamp`). `_match_poly_fixture(parsed, fixtures, style)` unchanged except it reads `parsed.team_a/team_b/date` (now attributes, not dict keys) — update accordingly.

- [ ] **Step 1 (RED):** Write per-`SideMode` unit tests in `tests/mappers/test_polymarket.py` using `build_rows` directly with a hand-built `ParsedMarket` for each mode (moneyline 2-team, spread signed-and-negated, over/under player-entity, btts yes/no, three-way-fixed single-row + `_TIE`), asserting the exact `(market_type, entity, line, side)` per emitted row and drop-on-bad-arity. Run → fail (SideMode/ParsedMarket absent).
- [ ] **Step 2:** Implement `SideMode`, `ParsedMarket`, the refactored `build_rows` dispatch, and the `market_rules` field + rule-iterating `parse_question`. Update `_match_poly_fixture` for attribute access. Update the pipeline poly-pass call sites.
- [ ] **Step 3:** Migrate the EXISTING moneyline/total (mlb_suffix) and tennis moneyline (tennis_prefix) parsing into `market_rules` functions and attach them to the mlb/atp/wta configs — OR keep the fallback path and leave migration to Task 3. Whichever: MLB ml/total + tennis ml output MUST stay byte-identical.
- [ ] **Step 4 (GREEN + regression):** new unit tests pass; FULL `tests/mappers/` = 324+new passed, 5 skipped, no drop. Golden rows for mlb/tennis unchanged. ruff --fix.
- [ ] **Step 5:** Commit `refactor(polymarket): (Scope,Shape)-dispatched build_rows + market_rules config (behavior-preserving)`.

---

### Task 3: MLB full-taxonomy market_rules (player props + run-line + team-total + 1st-inning)

**Files:**
- Modify: `mappers/exchanges/polymarket.py` (add the MLB rule recognizers) OR `mappers/leagues/mlb.py` (rules co-located with the league config — decide in Task 2)
- Modify: `mappers/leagues/mlb.py` (`PolymarketConfig.market_rules`, and `OpticConfig.table_types` for the new optic market_ids)
- Test: `tests/mappers/test_polymarket.py`, `tests/mappers/test_polymarket_mlb_integration.py`

**TO BE FINALIZED from the MLB optic probe** (exact optic `market_id`s, optic player-entity representation, and exact Poly question strings). Coverage:
- `"<Player>: Home Runs O/U N"` (Over/Under labels) → `PLAYER_HOME_RUNS`, entity=`normalize_player_name(player)`, line=N, side over/under. Same shape for Strikeouts→`PLAYER_STRIKEOUTS`, Hits→`PLAYER_HITS`, Total Bases→`PLAYER_BASES`, Hits+Runs+RBIs→`PLAYER_HITS_RUNS_RBIS`.
- `"Spread: <Team> (-N)"` and/or `"<Team> (-N)"` → `POINT_SPREAD` (optic `run_line`), SPREAD_TEAM.
- Team total (exact Poly wording TBD) → `TEAM_TOTAL`, entity=team abbrev, over/under.
- `"1st N Innings O/U N"` / 1st-inning → `FIRST_INNING_TOTAL` (period-anchored; must NOT collide with full-game `GAME_TOTAL`).
- Wire `mappers/leagues/mlb.py` `OpticConfig.table_types` with the confirmed optic market_ids for each.

- [ ] Steps (RED unit test per form with real strings → implement rule → GREEN → integration test stamping onto a real optic MLB prop row + a wrong-player drop test → full suite → ruff → commit). Filled in before dispatch.

---

## Self-review
- Spec coverage: Task 1 = all shared additions; Task 2 = the (Scope,Shape) generalization + guards; Task 3 = MLB surface. Phases 4–6 depend only on Task 1/2 interfaces.
- Byte-identical gate on the existing 324 tests governs the refactor's correctness.
- Flip-safety: SideMode makes side-binding explicit per shape; THREE_WAY_FIXED single-emit + drop-other is the Kalshi-negative-stays-novel convention.
