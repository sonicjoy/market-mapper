> Historical. Tip/console references are retired; see CLAUDE.md.

# Polymarket → OpticOdds matcher: full-Kalshi-parity + expansion (Phases 4–9)

**Date:** 2026-07-22
**Repo:** `mmmapper`
**Branch:** `feat/polymarket-parity-expansion` (off `feat/polymarket-optic-matcher` @ 9f2f9e7 — Phase 3 / MR !40)
**Predecessor spec:** `2026-07-22-polymarket-full-taxonomy-parity.md` (Phase 3, MLB — shipped)

## Goal

Bring the Polymarket matcher to **full parity with the Kalshi matcher** across every league mmmapper wires, then **expand** to the leagues Polymarket actually runs in RFQ that mmmapper does not yet map. End state: for every league in scope, Polymarket combo legs stamp onto the same optic market surface the Kalshi matcher already reaches (parity), plus poly-only optic coverage for the expansion leagues.

Motivation: Polymarket's own rows in optic (`source_ids` passthrough) are thin, but optic prices these markets from other sportsbooks (draftkings/fanduel/pinnacle/…). The matcher stamps a poly leg onto ANY optic row matched by team/player, regardless of source sportsbook — so poly coverage is bounded by what optic prices, not by what optic tags as Polymarket. Kalshi already maps that full surface; parity mirrors it onto poly.

## Scope

**11 leagues, two workstreams:**

- **Parity 6** (mmmapper module + `OpticConfig` + `KalshiConfig` already exist; work = poly recognizer rules + poly config only): **NFL, NHL, NBA, NCAAB, EPL, WORLD_CUP**.
- **Expansion 5** (enum-only in mmmapper — no module, no Kalshi matcher, no optic config; work = net-new poly-only module: probe → `OpticConfig` + `PolymarketConfig` + `LeagueConfig` with `KALSHI=None`): **MLS, LIGA_MX, UCL, WNBA, UFC**.

Already at/above parity (out of scope, done in Phase 3): **MLB, ATP, WTA**.

Out of scope: esports (cs2/val/lol/dota2), minor-soccer divisions, cricket, ITF, NWSL — optic prices no odds source for these; MAPPING_FAILED is correct. Not building Kalshi matchers for the expansion 5 (goal is poly mapping).

## Key structural insight — sport-family reuse

The `(Scope,SideMode)` recognizers in `build_rows` are **sport-shaped, not league-shaped**, and `build_rows` is frozen (adding a league = rules + config only, per the module docstring contract). Order the waves by sport and the expansion leagues inherit the parity wave's recognizers:

- Expansion **soccer** (MLS/LIGA_MX/UCL) reuses the **EPL/WORLD_CUP** soccer rules → new work is `OpticConfig` probe + `LeagueConfig` wiring only.
- Expansion **basketball** (WNBA) reuses the **NBA** basketball rules → same.
- Only **UFC** is greenfield: no existing MMA market_types, no Kalshi reference — net-new taxonomy.

This collapses "parity 6 + expansion 5" to ~6 recognizer-building waves + mostly-wiring expansion, plus one greenfield UFC wave.

## Architecture

Reuse the Phase-3 core unchanged:

- `PolymarketConfig.market_rules` = ordered tuple of `question -> ParsedMarket | None` recognizers, first non-None wins.
- `build_rows` dispatches on `(Scope, SideMode)`; **do not edit the dispatch** — add recognizer rules + config.
- **Flip-safety invariant (binding):** side is ALWAYS bound to the outcome label or the entity named in the question, never to an array index; a market that cannot resolve both complementary sides drops whole.
- **Two dormant SideModes go live** (implemented + unit-tested, never exercised by a live rule until now):
  - `THREE_WAY_FIXED` — soccer 3-way moneyline (draw leg → `_TIE`), basketball half-winners (3-way).
  - `YESNO` — BTTS, to-advance (team-scope), player double/triple-double.
- **Expansion = poly-only:** `LeagueConfig.KALSHI=None` (the Optional path Task-1 built; this is its first live use — verify `list_aliases.py` / any unguarded `KALSHI.` access, ledger finding M1).
- **UFC:** net-new MMA market_types in `market_types.py` (method-of-victory, round groups, fight-goes-distance) gated on the Wave-9 probe; only forms present in BOTH optic and the poly bridge get built.
- **question_style / team-name normalization:** today only `mlb_suffix` + `tennis_prefix`. Each new sport's probe confirms whether `mlb_suffix` containment-match suffices or a new style is needed (real poly question strings vs optic names).

## Non-negotiable invariants (global constraints)

1. **Byte-identical golden gate.** Existing MLB / tennis golden outputs must not change across any wave. Full `tests/mappers/` stays green; no test dropped.
2. **`build_rows` dispatch is frozen** — new leagues add rules + config only.
3. **Flip-safety** (above) holds for every new rule; drop-whole on unresolvable sides.
4. **Never invent a mapping optic did not price** — a poly leg stamps onto an existing optic row or drops.
5. **Probe before build.** BQ probes are bounded + dry-run-approved by the human first (standing rule). Optic probes hit the optic API (`fetch.optic`).
6. **Parity target = Kalshi coverage ∩ optic table_types**, per league (below). Do not build a form optic does not price, or that poly does not offer.

## Parity target per league (from code discovery, with citations)

Kalshi coverage = the league's `KalshiConfig.table_types`; optic ceiling = its `OpticConfig.table_types`. Build the intersection on the poly side.

- **NFL** (`nfl.py`): MONEYLINE, POINT_SPREAD, GAME_TOTAL. All optic-priced. Reuses TEAM_LABEL / SPREAD_TEAM / OVER_UNDER.
- **NHL** (`nhl.py`): MONEYLINE, POINT_SPREAD (puck line → optic `puck_line`), GAME_TOTAL. Same 3 modes.
- **NBA** (`nba.py`): MONEYLINE, POINT_SPREAD, GAME_TOTAL, TEAM_TOTAL, FIRST_HALF_POINT_SPREAD, FIRST_HALF_TOTAL, FIRST_HALF_WINNER_3WAY (→THREE_WAY_FIXED), SECOND_HALF_WINNER_3WAY (→THREE_WAY_FIXED), player props PTS/AST/REB/3PT/BLK/STL (→OVER_UNDER PLAYER), DOUBLE_DOUBLE + TRIPLE_DOUBLE (→YESNO PLAYER).
- **NCAAB** (`ncaab.py`): subset of NBA — MONEYLINE, POINT_SPREAD, GAME_TOTAL, FIRST_HALF_POINT_SPREAD, FIRST_HALF_TOTAL, FIRST_HALF_WINNER_3WAY. No player props / team total / 2H.
- **EPL** (`epl.py`): MONEYLINE_3WAY (→THREE_WAY_FIXED, draw→`_TIE`), POINT_SPREAD (optic `asian_handicap`), GAME_TOTAL.
- **WORLD_CUP** (`world_cup.py`): the richest — MONEYLINE_3WAY, POINT_SPREAD, GAME_TOTAL, TEAM_TOTAL, PLAYER_GOALS (anytime-scorer ladder, N+ = over N−0.5), FIRST_HALF_WINNER_3WAY, FIRST_HALF_POINT_SPREAD, FIRST_HALF_TOTAL, BTTS (→YESNO), FIRST_HALF_BTTS, TOTAL_CORNERS, TEAM_TOTAL_CORNERS, TO_ADVANCE (→YESNO team-scope). Settlement-basis caveats (knockout ET-inclusive) documented in-config — a merge concern, not a recognizer concern.
- **Expansion soccer (MLS, LIGA_MX, UCL):** whatever the per-league optic probe prices, mapped with the WORLD_CUP/EPL soccer recognizers. Likely subset (3-way ML, spread, total, BTTS; corners/scorer if priced).
- **Expansion WNBA:** whatever optic prices, mapped with NBA basketball recognizers (ML, spread, total, team total, halves, player props).
- **Expansion UFC:** greenfield — probe decides. Fighter moneyline (H2H by name) is the floor; method-of-victory / round-total / distance only if both optic and poly carry them.

## Wave decomposition

| Wave | Leagues | Type | New work | Coder model |
|---|---|---|---|---|
| 4 | NFL, NHL | parity, rules-only | proves non-MLB team-name norm | sonnet |
| 5 | NBA, NCAAB | parity, rules-only | first THREE_WAY_FIXED + first YESNO + player props | sonnet |
| 6 | EPL, WORLD_CUP | parity, rules-only | soccer 3-way, BTTS, to-advance, goals, corners | sonnet |
| 7 | MLS, LIGA_MX, UCL | expansion, poly-only | OpticConfig probe + wiring (reuse wave-6 rules) | haiku (wiring) + sonnet (probe) |
| 8 | WNBA | expansion, poly-only | OpticConfig probe + wiring (reuse wave-5 rules) | haiku (wiring) + sonnet (probe) |
| 9 | UFC | expansion, greenfield | new MMA taxonomy + module + probe | sonnet |

Each wave = one plan file, its own SDD run (per-task implementer + opus task reviewer), a final wave review (opus). Waves executed in order (5 rides 4's normalization proof; 6 builds soccer rules; 7 rides 6; 8 rides 5; 9 standalone).

## Per-wave task shape

1. **Probe** (sonnet, or opus if design-bearing) — optic API + bounded dry-run-approved BQ bridge query → `.superpowers/sdd/wave-N-probe-findings.md`: optic `market_id`s present, real poly question strings, team/player-name agreement, per-form market counts. Finalizes the wave's rule list.
2. **Rules + config** (sonnet; haiku for pure-wiring expansion tasks) — recognizers + `PolymarketConfig` / `OpticConfig` / `LeagueConfig`, matching Kalshi ∩ optic.
3. **Tests** (sonnet) — unit test per rule; dormant-mode live-question tests where first-exercised; byte-identical golden assertion.
4. **Local validation** (controller) — `GCP_PROJECT=marketmaking-test .venv/bin/python -m fetch.optic/-m fetch.polymarket` into `data/<date>/<HH_MM>` then `-m mappers.run <dir> --league X --json`; count new stamps, assert 0 market-type/line mismatches, over/under balance.

## Risks

- **Dormant-mode first-exercise** (THREE_WAY_FIXED, YESNO): validate against LIVE poly questions, not only synthetic `ParsedMarket` unit tests. First live use is Wave 5/6.
- **Team-name normalization** beyond mlb_suffix/tennis_prefix: probe confirms per sport; new `question_style` if containment-match fails.
- **WORLD_CUP concluded 2026-07-19**: live optic pricing thin; validate off a historical bridge snapshot rather than a live run.
- **UFC taxonomy net-new**: could slip; isolated to Wave 9, gated on probe.
- **`KALSHI=None` first live use** (expansion): guard/verify every unguarded `KALSHI.` access (ledger M1: `list_aliases.py:328`).

## Model assignment (SDD)

Sonnet + haiku coders (haiku for the super-simple pure-wiring expansion tasks), opus task reviewers/overseers, opus final whole-branch review.

## Test / lint commands

- Suite: `.venv/bin/python -m pytest tests/mappers/` (NO poetry, NO bare python).
- Lint: `.venv/bin/python -m ruff check --fix` (clean on changed lines; pre-existing HEAD errors out of scope).
- Local run: see Per-wave task shape step 4 (`GCP_PROJECT=marketmaking-test`; dir MUST be `<date>/<HH_MM>` — pipeline parses it as fetch_time).
