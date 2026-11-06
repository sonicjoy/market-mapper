> Historical. Tip/console references are retired; see CLAUDE.md.

# Wave 5 — Basketball Polymarket matcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add Polymarket recognizer rules + configs so poly basketball combo legs stamp onto every OpticOdds basketball market optic prices, across parity leagues (NBA, NCAAB — existing OpticConfig) and expansion WNBA (poly-only, `KALSHI=None`), validating on the in-season member (WNBA).

**Architecture:** Reuse the frozen `(Scope,SideMode)` `build_rows` dispatch. Add basketball recognizers to `mappers/exchanges/polymarket.py` + a shared `basketball_market_rules` tuple + `BASKETBALL_MARKET_TYPES` dict. Reuse the Wave-4 machinery unchanged: OVER_UNDER (totals, team-totals, player props), SPREAD_TEAM (spread), THREE_WAY_FIXED (half-winners — optic models NBA halves 3-way), YESNO (double/triple-double), the `team_name_aliases` overlay + `team_alias_scope`, and the single-team THREE_WAY_FIXED pipeline resolution. WNBA gets a new poly-only module.

**Tech Stack:** Python, mmmapper `mappers/`. Tests `.venv/bin/python -m pytest tests/mappers/` (NO poetry). Lint `.venv/bin/python -m ruff check --fix`.

## Global Constraints

- Byte-identical golden gate: existing MLB/tennis/soccer + kalshi/optic/px golden outputs unchanged; full `tests/mappers/` green; no test dropped.
- `build_rows` dispatch FROZEN — add rules + config only.
- Flip-safety: side bound to outcome label or question-named entity, never array index; unresolvable → drop whole.
- Never invent a mapping optic didn't price — stamp onto an existing optic row or drop.
- Coverage target = poly-offered basketball forms ∩ optic `table_types`, per league. Build only forms present in BOTH.
- Probe before build; bounded BQ, reported bytes; optic probes via `fetch.optic`.
- Ruff check clean on changed lines. Pyright `mappers.*` import diagnostics are a known false-positive.
- Git trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Wave-5 prereq (from Wave-4 final review):** add `assert LEAGUE_SECRET.keys() >= SUPPORTED_LEAGUES.keys()` in `fetch/optic.py` (or derive the secret by sport) — `SUPPORTED_LEAGUES` is now derived from `LEAGUES`, so WNBA missing from the hand-maintained `LEAGUE_SECRET` would `KeyError` mid-fetch. Fold into the WNBA wiring task.

## Parity targets (from Wave-4 code discovery — confirm live in Task 1)

- **NBA optic** (`nba.py` table_types): moneyline, point_spread, total_points, team_total, 1st_half_{moneyline,point_spread,total_points}, 1st_half_moneyline_3-way, 2nd_half_moneyline_3-way, player_{points,assists,rebounds,made_threes,blocks,steals,turnovers}, player_double_double, player_triple_double, player_{steals_+_blocks,points_+_assists,points_+_rebounds,points_+_rebounds_+_assists,rebounds_+_assists}.
- **NCAAB optic**: NBA minus 2nd-half, minus player props, minus team_total (moneyline, point_spread, total_points, 1st_half_{moneyline,point_spread,total_points}, 1st_half_moneyline_3-way).
- **WNBA optic**: UNKNOWN — Task 1 probes the live optic ceiling + WNBA optic `league_id`.
- **Poly basketball forms**: UNKNOWN — Task 1 form-histogram (wnba prefix in-season; nbasl summer-league ML-only). NBA/NCAAB absent from July bridge (offseason) → their configs are forward-ready, validated when season opens.

Likely mappable basketball forms (confirm ∩ in Task 1): moneyline (2-way — NBA has no draw, so TEAM_LABEL or single-team YES per team without a TIE leg), point_spread, total, team_total, 1st/2nd-half winner (optic 3-way → THREE_WAY_FIXED), 1st-half spread/total, player points/assists/rebounds/threes/blocks/steals (OVER_UNDER PLAYER), double-double/triple-double (YESNO PLAYER).

## File Structure

- `mappers/exchanges/polymarket.py` — basketball recognizers + `basketball_market_rules` tuple + `BASKETBALL_MARKET_TYPES` dict.
- `mappers/leagues/nba.py`, `mappers/leagues/ncaab.py` — add `POLYMARKET` config (OpticConfig exists).
- `mappers/leagues/wnba.py` — NEW poly-only module (OpticConfig from probe + PolymarketConfig + LeagueConfig KALSHI=None + team aliases).
- `mappers/run.py` — register WNBA.
- `fetch/optic.py` — `LEAGUE_SECRET` superset guard (Wave-5 prereq).
- `tests/mappers/test_polymarket_basketball.py` — NEW.
- `.superpowers/sdd/wave-5-probe-findings.md` — Task 1 output.

## Tasks

### Task 1: Basketball optic + poly probe
Probe: (a) optic basketball market ceiling for a live WNBA fixture + WNBA optic `league_id` (via `leagues/active?sport=basketball`); confirm NBA/NCAAB optic table_types; (b) poly basketball form histogram + exact question templates + outcome labels for the `wnba` bridge prefix (and `nbasl` summer league), bounded BQ; (c) 2-way vs 3-way moneyline encoding on poly (basketball has no draw — determine how poly encodes it); (d) team-name + player-name agreement (mlb_suffix / normalize_player_name) → alias needs. Write `.superpowers/sdd/wave-5-probe-findings.md`. Finalizes Tasks 2+.

### Tasks 2–N: basketball recognizers (finalized from Task 1)
One task per recognizer family (mirror Wave-4 granularity): moneyline; spread + 1st-half spread; totals (game/team/half); half-winners (THREE_WAY_FIXED — first basketball 3-way); player props (OVER_UNDER PLAYER — reuse `_player_prop_rule`); double/triple-double (YESNO PLAYER — first PLAYER-scope YESNO); assemble `basketball_market_rules` + `BASKETBALL_MARKET_TYPES`. Each: unit tests per rule + dormant-path integration tests + ordering guards. Exact strings from Task-1 findings.

### Task W1: wire NBA + NCAAB (parity)
`POLYMARKET` config on both referencing `basketball_market_rules`; optic_league_id from existing OpticConfig; per-league mapped-vs-dropped form breakdown.

### Task W2: wire WNBA (expansion, poly-only)
New `wnba.py`: OpticConfig from Task-1 ceiling, PolymarketConfig (slug prefix from Task 1, optic league_id from Task 1), LeagueConfig `KALSHI=None`; team-name aliases from Task-1 check; register in `LEAGUES`; add the `LEAGUE_SECRET` superset guard in `fetch/optic.py`; confirm no unguarded `.KALSHI`/`.PX` runtime access.

### Task V: local validation
Fetch + map WNBA end-to-end (`fetch.optic --league wnba` + `fetch.polymarket` + `mappers.run --league wnba --json`); stamp counts by form; 0 mismatches; player-prop entity binding + half-winner selection spot-checks; drop analysis.

## Self-Review
Every basketball form optic prices + poly offers has a recognizer (Tasks 2–N); NBA/NCAAB wired (W1); WNBA poly-only wired (W2) + LEAGUE_SECRET guard; dormant PLAYER-scope YESNO (DD/TD) first-exercised with integration tests; probe resolves optic ceiling + poly forms + name agreement (Task 1); validation (V). Exact strings deferred to Task-1 findings BY DESIGN (probe-first).
