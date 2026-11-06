> Historical. Tip/console references are retired; see CLAUDE.md.

# Polymarket → OpticOdds active matcher — design

- **Date:** 2026-07-21
- **Status:** approved (design), pending implementation plan
- **Repos:** `mmmapper` (matcher, primary) + `mmpolymarketrfq` (maker consumption)
- **Related memory:** greg-mapping-optic-passthrough-polymarket, combo-mapping-coverage-gaps, norway-teamtotal-flip-incident, combo-leg-mapping-ignores-outcomes

## Problem

The Polymarket combo-RFQ maker (`mmpolymarketrfq`) declines **~71 % of RFQs that reach mapping** with `MAPPING_FAILED` (43 % of *all* evaluations). Root cause, established by evidence (2026-07-21):

- The position_id ↔ clob_token_id **bridge is healthy** (`no_gamma ≈ 0.3 %`).
- The semantic slug parser in the maker is **dead** (`parsed=0`, fifwc-only; no World Cup live).
- **`no_optic` dominates:** the leg's `clob_token_id` is not mapped by OpticOdds — 88 % of leg-tokens reaching the overlay step (`no_optic=8777` vs `1195` mapped), and ~93 % of the full bridge universe (see coverage table).

Coverage measurement of today's 22,548-token RFQ universe against every existing poly-mapping source, **identical in test and prod**:

| source | coverage |
|---|---|
| `opticodds_us.prices_dedup_state` (poly) — what the maker reads today | 1,586 (7.0 %) |
| `markets_us.market_mapping` (greg) — poly rows | 700 (3.1 %), 152 of them unique |
| **union of all four (test+prod × both tables)** | **1,738 (7.7 %)** |

`market_mapping`'s Polymarket rows are a **verbatim optic `source_ids` passthrough** — mmmapper has *no* Polymarket active matcher (it actively matches only Kalshi / PX / crypto.com / Runshop). So ~92 % of RFQ'd tokens have **no mapping in any source**. OpticOdds prices only ~9 leagues; Polymarket combos span 56+ (esports, minor soccer divisions have no odds source at all).

## Goal / non-goals

**Goal:** build a Polymarket active matcher in mmmapper (mirroring the Kalshi/PX pattern) that maps `clob_token_id → optic (fixture/market/selection/line/side)` for every market Polymarket RFQs *and* OpticOdds prices, writing constructed rows into `markets_us.market_mapping`; and change the maker to consume them.

**Non-goals:**
- The ~70 % of tokens in leagues OpticOdds does not price (esports, minor soccer). No odds source ⇒ unpriceable ⇒ `MAPPING_FAILED` is correct. Out of scope (separate lever: expand optic ingestion).
- Exotic/period markets optic does not price even in covered leagues (F5 innings, 1st-half, "leading at halftime"). Guard #3 drops them; they stay declined.

## The mapping chain (invariant)

- **position_id → clob_token_id** — owned by the **bridge** (`raw_ingestion_us.polymarket_position_token_bridge`). Unchanged.
- **clob_token_id → optic** — produced by the **new matcher**, written to `market_mapping` keyed by `source_ids.selection_id = clob_token_id`.
- **maker composes them** at read time: bridge gives position→clob, then clob→optic via the union read.

The matcher operates purely at the **single-market (clob) level** — the level optic understands. It never keys on position_id (position_id is carried only as nullable provenance). The bridge stays the sole owner of position↔clob.

## Design decisions (locked)

1. **Scope:** all 9 optic-priced leagues (comprehensive — "if Polymarket RFQs it, we want it mapped"), delivered in waves.
2. **Input:** Approach A — the matcher's poly feed = the **bridge table** (already carries `slug`, `question`, `outcome_label`, `condition_id`, `clob_token_id` per RFQ'd token; the exact RFQ universe, pre-fetched, geoblock-proxy already solved).
3. **Output:** greg's `markets_us.market_mapping` (constructed `Polymarket` rows, like Kalshi/PX). Maker reads the union.
4. **Flip-safety:** guards + tests, emit novel (below).

## Architecture & data flow

```
[mmmapper crons]
  (existing) bridge loader ─► raw_ingestion_us.polymarket_position_token_bridge
                              (position_id, clob_token_id, condition_id,
                               outcome_index, outcome_label, slug, question)
  (NEW) mapping run:
    1. fetch/polymarket.py  ── reads bridge (active, in-window cond_ids),
                               groups rows by condition_id ─► polymarket_markets.jsonl
                               (one line/market: cond_id, slug, question,
                                outcomes[{idx,label,clob_token_id,position_id}])
    2. parse_market(line)   ── slug/title ─► (league, home, away, date) = MatchKey
    3. optic schedule index ── (existing) from optic_fixtures_odds.jsonl
    4. match MatchKey ─► optic fixture     (no fixture → skip: uncovered league, expected)
    5. polymarket.build_rows ── title/slug ─► market_type/line; per outcome bind
                               side to outcome_label; apply flip-safety guards
                               ─► CanonicalRow (+ polymarket_* stamp fields)
    6. load_mappings.flatten_rows ── source_ids={"selection_id": clob_token_id}
                               ─► MERGE markets_us.market_mapping (sportsbook="Polymarket")

[mmpolymarketrfq maker — unchanged except one read]
    _load_singles_optic_map_sync reads UNION(prices_dedup_state[poly], market_mapping[poly])
        keyed by clob_token_id ─► {clob_token_id → optic coords + side}
    bridge read (position→clob) UNCHANGED; build_singles_store keys by position_id UNCHANGED
```

Properties: input == RFQ universe; coverage capped at optic-fixture leagues (unmatched = expected decline); side bound to `outcome_label`, never array index.

## Components — mmmapper

| Component | File | What |
|---|---|---|
| Fetch | `fetch/polymarket.py` (NEW) + register in `fetch/__main__.py` `FETCHERS` | BQ-query the bridge → group by `condition_id` → `polymarket_markets.jsonl` (one line/market with outcomes). |
| Model + parse + build | `mappers/exchanges/polymarket.py` (NEW) | `parse_market(line)->PolyMarket|None`; `PolymarketConfig` (per-league slug prefix + title-pattern → `MarketType` table); `build_rows(...)->list[CanonicalRow]`. Ports/generalizes the maker's `parse_combo_market`/`resolve_token_mappings`. |
| Canonical row | `mappers/shared.py` `CanonicalRow` | add `polymarket_condition_id`, `polymarket_token_id` (clob), `polymarket_slug`, `polymarket_position_id` (nullable provenance) — mirror the `crypto_*` stamp block. |
| Pipeline | `mappers/pipeline.py` | add `POLYMARKET: PolymarketConfig|None` to `LeagueConfig`; load poly jsonl + MatchKey-match (mirror crypto ~1065-1134); call `polymarket.build_rows` + merge/carry-novel (~1245-1258); emit `polymarket` block in `canonical_row_to_json`. |
| Write | `BigQuery/load_mappings.py::flatten_rows` | constructed `Polymarket` yield: `source_ids={"selection_id": clob_token_id}`, emitted **only when optic's own `source_ids` lack a `"Polymarket"` entry** for this row. `OPTIC_MAPPED_SPORTSBOOKS` is KEPT unchanged — the passthrough remains the source of optic-already-mapped Polymarket rows (incl. Wave 0's +152); the constructed block covers only the optic-unmapped tokens, avoiding a same-MERGE-key double-emit. (Original plan said "remove Polymarket from the set" — corrected 2026-07-21: that would drop existing passthrough coverage.) |
| Per-league config | `mappers/leagues/{mls,ucl,liga_mx,mlb,atp,wta,atp_challenger,wnba,ufc}.py` | add `POLYMARKET=PolymarketConfig(...)` to each covered league's `LEAGUE`. |

## Flip-safety guards (emit gate in `build_rows`)

Every emitted poly row must pass **all**:

1. **Side bound to `outcome_label`**, never array index. `label=="No"` on a Yes/No market → `side="no"`; team / over-under / scoreline labels → affirmative `side="yes"` naming the selection/line the label states. (Closes the latent index-based side bug — `combo-leg-mapping-ignores-outcomes` — at the source.)
2. **Complementary-pair consistency:** a binary market's two tokens must resolve to complementary optic selections (over↔under, team↔opponent, Yes↔No). Else drop the whole market.
3. **market_type must exist in optic for that fixture.** No optic `total_goals` line for the game → don't emit a `total_goals` poly row.
4. **Cross-check where optic already maps the clob:** assert our parsed side/selection agrees with optic's `source_ids["Polymarket"]`; mismatch → drop + log (parser-bug signal). **[IMPLEMENTED post-Wave-1, commit f4db57d]** — `pipeline._build_optic_poly_index` builds a global `{clob → optic row_key}` from optic's own `source_ids["Polymarket"]`/`["Polymarket (USA)"]`; the poly pass then constructs only *novel* tokens (optic maps nowhere), skips *agrees* (optic maps identically → passthrough emits), and drops+logs *conflicts* (optic maps the clob to a different row_key than our parse). This was built as the prerequisite before the ambiguous-label tennis wave, exactly as this note originally required.
5. Unmatched fixture (uncovered league) → skip silently (expected).

## Maker consumption change — mmpolymarketrfq

One function: `_load_singles_optic_map_sync` (`common/mapping_loader.py:651`).

- Source becomes the **UNION** of `prices_dedup_state[poly]` and `market_mapping[poly]`, keyed by `clob_token_id`, **market_mapping winning on conflict** (flip-safe constructed mapping).
- **Consume the matcher's explicit `side`/`selection_line`** from the row instead of `build_singles_store` re-deriving side by index (`:777`) — closes the same latent index-flip on the read side.
- Everything else — bridge read, `build_singles_store` keying by position_id, YES-only gate — unchanged.
- Wave-0 shippable alone: unioning `market_mapping` in yields **+152 tokens (+9.6 % relative)** immediately, before any matcher rows exist.

## League-coverage phasing

Guard #3 auto-drops any market type optic does not price, so exotic legs stay correctly declined.

**Reordered by mmmapper-league existence (verified 2026-07-21).** mmmapper league modules that exist: atp, epl, mlb, nba, ncaab, nfl, nhl, world_cup, wta. Of the 9 optic-priced-for-Polymarket leagues, only **mlb, atp, wta** already exist — adding Polymarket to those is just a `PolymarketConfig` + the matcher module. mls/ucl/liga_mx/wnba/ufc need *new* league modules built first (League enum + config dir + `OpticConfig`; and `LeagueConfig.KALSHI` must be made Optional, since it's currently required). So the cheapest pattern-proving wave targets an existing league, not soccer.

| Wave | Leagues | New league module? | Recoverable-standard (approx, today) | Notes |
|---|---|---|---|---|
| **0** | — | — | +152 tokens (union read, zero matcher) | shipped as Plan 1 |
| **1 baseball** | mlb | no — exists | ~306 (game_total 206 + moneyline 100) | pattern-proving; F5/period + many props are unpriceable-by-optic → correctly dropped |
| **2 tennis** | atp, wta | no — exist | ~1,000 unmapped (match winner / total games / total sets); player-entity | shared tennis parser across 2 existing leagues |
| **3 soccer** | mls, ucl, liga_mx | **yes** — build modules | highest volume (mls ~1.8k etc.); hardest cases (draw→MONEYLINE_3WAY+_TIE, BTTS) | biggest yield; also make `KALSHI` Optional |
| **4 basketball** | wnba | yes — build | moneyline / total points / spread | |
| **5 mma** | ufc | yes — build MMA from scratch | fight winner | no MMA league in mmmapper at all |

mlb first proves the end-to-end plumbing (bridge-fed fetch → text-parse → merge-onto-optic → maker consumption → guards) on an existing league with modest but real yield; tennis and soccer then scale the coverage. Re-measure lift per wave with the bridge-vs-`market_mapping` harness.

### mlb market-type mapping (Wave 1)
Poly mlb single question formats (from the bridge): moneyline = `"<Team A> vs. <Team B>"` (side bound to the `outcome_label` team name); total = `"<Team A> vs. <Team B>: O/U <N>"`. Optic mlb (`OpticConfig.table_types`): `moneyline`→MONEYLINE, `run_line`→POINT_SPREAD, `total_runs`→GAME_TOTAL. The matcher produces canonical rows with these `MarketType`s so they merge onto optic's rows; the written `market_id` comes from the merged optic odd (`_optic_base`), not synthesized. F5/first-inning and most player props are dropped by guard #3 (optic doesn't price them for these tokens).

## Testing & go-live gate

**mmmapper:**
- Per-market-type unit tests on the parser (side bound to label; complementary-pair drop; line parsing).
- `tests/mappers/test_polymarket_integration.py` — fixture dir → pipeline → assert rows + stamps + guards.
- A `Polymarket` case in `tests/BigQuery/test_flatten_rows.py` (`source_ids` shape).
- Extend `verify_source_ids` cross-check for Polymarket.

**maker:** update `tests/test_mapping_loader.py` for the union read + side-from-row (not index).

**Go-live gate (QUOTE_LIVE=true — matters):** matcher lands rows in **test** `market_mapping` → maker in test consumes them → **side-correctness audit on a sample of flip-prone types (totals, BTTS, spreads)** + coverage-lift measurement, *before* scaling waves. A wrong side is catastrophic (Norway 2026-07-09); a missed map is safe — so audit gates each wave.

## Risks

- **Title-parse flips** (the Norway class). Mitigated by guards #1/#2/#4 + per-type tests + the batch/reviewable nature + the per-wave audit gate. Not zero — hence the gate.
- **Bridge/matcher freshness coupling** — both are mmmapper crons (~3h). Acceptable.
- **Real ceiling** — even a perfect matcher only recovers the covered-league standard-market subset; absolute lift is bounded (7.7 % → target measured per wave, not assumed). The 70 % tail needs optic ingestion, out of scope.

## Appendix — evidence

- Funnel (live worker, 2026-07-21): `Singles-optic overlay: 1195 tokens (gamma_markets=4986 singles_mapped=3817 no_gamma=14 no_optic=8777)`; `mapping built: ... parsed=0 no_parse=5000 ... leagues=[]`.
- Decline path: `rfq.fail("MAPPING_FAILED")` (`MMutils/handlers/rfq_manager.py:541`) → `rs-marketmaking.trading_us.rfq.reason` (poly rows persist to marketmaking-test).
- Maker mapping env: `MAPPING_PROJECT_ID=marketmaking-test`, `USE_POSITION_BRIDGE=true`, `QUOTE_LIVE=true`.
- Coverage harness SQL: `scratchpad/dual.sql` (bridge tokens × {prices_dedup_state, market_mapping} × {test, prod}).
