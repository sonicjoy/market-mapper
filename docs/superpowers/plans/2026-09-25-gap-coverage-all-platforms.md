> Historical. Tip/console references are retired; see CLAUDE.md.

# Gap coverage for every RFQ platform

**Date:** 2026-09-25
**Trigger:** crypto.com combo `NX.F.OPT.COMBOS-20260924.O.1.19189011`
(UEFA Nations League legs) failed with `MAPPING_FAILED`; gap-propose never
drafted a league pin.
**Goal:** every `MAPPING_FAILED` / `UNMAPPED` symbol or ticker on every RFQ
platform either becomes a pin on Proposed or carries a named outcome/reason,
with operators alerted when neither happens.

## Evidence (prod, 2026-09-25)

- UNL legs: Optic `uefa_-_nations_league`; no tip `UNL`; not in
  `market_mapping`.
- Mapping failures (24h) not in gap inventory today: `cryptocom-inplay`
  (~128k), `novig` (~4.6k), `prophetx` (~2.9k).
- Crypto harvest skips `league_not_wired`; only Polymarket drafts
  `mapping_league` from RFQ demand.
- Scheduled coverage alert removed 2026-09-23; gap-propose Slack is mostly the
  Review card.

## Why the gap was invisible (code facts)

1. `crypto_rfq_symbols_sql` filters `platform = 'cryptocom'` (excludes in-play).
2. `gap_inventory_sql` has no Novig or ProphetX CTEs.
3. `allow_kalshi_ticker` drops unwired Kalshi series before harvest.
4. `league_not_wired` is hard-skipped in `collect_crypto_probe_pins`.
5. Kalshi `unknown ticker type` is stderr-only in `pipeline.py`.

## Invariants

- Human Approve on Proposed; gap-propose never activates the tip.
- Pins via `pin_flow.verify_pins` / `draft_and_verify`; `names_fit` unchanged.
- Fail closed on ambiguous Optic / slug collision / no clone / `needs_code`.
- New flags default **on** (`MAPPING_GAP_LEDGER`, `MAPPING_PIPELINE_GAP_ONBOARD`).
- Keep existing walk/pin caps (OOM history).

## Phase 1 — See every gap (PR 1)

- [ ] **1.1** `rfq_platforms.py` — book ↔ `rfq_latest.platform` values; used by
  `gap_inventory_sql`, `crypto_rfq_symbols_sql`, and copy-paste SQL under
  `BigQuery/sql/`.
- [ ] **1.2** Unknown platform in the RFQ window → Slack warning + ledger
  `unknown_platform`.
- [ ] **1.3** Include `cryptocom-inplay` in crypto inventory.
- [ ] **1.4** Keep unwired Kalshi series in ranked inventory (`needs_league`).
- [ ] **1.5** Novig + ProphetX inventory keys (PX: `event_id:line_id`; Novig:
  confirm `market_mapping` join field for RFQ `market_ticker` UUID).
- [ ] **1.6** Per-tick outcomes per inventoried key: `pinned | skipped |
  maker_lag | expected_residual | needs_league | needs_probe | not_walked |
  unknown_platform`. Persist to `markets_us.mapping_gap_ledger` (schema PR in
  mm-infrastructure); writer no-ops if table missing (`MAPPING_GAP_LEDGER`,
  default on).
- [ ] **1.7** Slack summary per tick (demand + outcome counts, top unexplained
  keys); alert when demand persists with no pin/reason (configurable thresholds).
- [ ] **1.8** Grafana ledger panels in `docs/mapping-coverage-grafana.md`.
- [ ] **1.9** Tests: platform SQL parity, `fetch_rfq_inventory` coverage,
  ledger outcome per key, alert rules.
- [ ] **1.10** Docs/skills: `gap-propose.md`, `rfq-unmapped-leg-coverage`,
  `crypto-mapping-gap-investigation` (no standalone alert).

## Phase 2 — Draft every fixable gap (PR 2)

- [ ] **2.1** Shared `gap_fix_onboard.py` (extract Polymarket `_try_onboard`);
  `MAPPING_PIPELINE_GAP_ONBOARD` default on.
- [ ] **2.2** crypto `league_not_wired` → onboard/enable (`UNL` fixture test).
- [ ] **2.3** Kalshi unwired prefix → onboard/enable.
- [ ] **2.4** ProphetX unwired tournament → onboard/enable.
- [ ] **2.5** Novig (after join spike) → probe + onboard.
- [ ] **2.6** Kalshi unknown ticker types → `harvest_missing_market_rules`.
- [ ] **2.7** Top skips on the pipeline Proposed card (`reason`, demand).
- [ ] **2.8** Unmapped Why / Mapper Chat stage onboard pins through the same
  helper and `draft_and_verify` (existing console surfaces; no new page in scope).
- [ ] **2.9** Mapper fail-safe for unknown `meta_league`.
- [ ] **2.10** `test_pin_flow`, add-new-league / rfq-unmapped skills.

## Phase 3 — Residual audit

Count 7d by class (`tournament_future`, `catalogue_miss`, `missing_optic`,
horizon/stale, `SIDE_NOT_SUPPORTED`); product decision before code.

## Rollout

Phase 1 → test → prod → Phase 2 per book → quality gate each PR.

## Manual UNL

Editor: `mapping_league` with Optic `uefa_-_nations_league`, crypto `UNL`
(`crypto_generic_v1`); clone soccer market rules; enable other books only
with evidence.

## Open questions

1. Ledger: BQ table (default) vs Slack + Grafana on `rfq_latest` only.
2. Novig `market_mapping` join key for RFQ UUID `market_ticker`.
3. Alert thresholds (defaults: demand 50, 4 ticks ≈ 2h).
