---
name: rfq-unmapped-leg-coverage
description: >-
  Drive optic-priceable RFQ leg coverage on reporting_us.rfq_latest toward
  residual-only: inventory unmapped legs, split maker-lag vs true gap vs
  expected residual, then fix each true-gap class in code (vocab, venue
  table, matcher) with a test, an MR and the regression gate. Use for RFQ
  mapping coverage, MAPPING_FAILED / UNMAPPED legs, "platform fully mapped",
  or "what's left to map".
---

# RFQ unmapped-leg coverage

Mission: map optic-priceable RFQ legs so `optic_fixture_id`, `market` and
`selection` are set. 100% of every RFQ is not possible (non-Optic leagues,
empty legs, shapes Optic does not price). Drive the priceable set to
residual-only.

Policy: `CLAUDE.md`. Fixes are code changes. Taxonomy notes:
`docs/rfq-mapping-gap-classification.md`. Dashboard SQL:
`docs/mapping-coverage-grafana.md`.

## Checklist

```
- [ ] 1. Inventory (prod rs-marketmaking; validate SQL on marketmaking-test first)
- [ ] 2. Classify each bucket: maker-lag | true gap | expected residual | out of scope
- [ ] 3. Group true gaps by class (one venue field / vocab entry / table line
         fixes all of them), not by ticker
- [ ] 4. Fix the class in code + test (add-team-alias / add-new-league skills)
- [ ] 5. GCP_PROJECT=rs-marketmaking .venv/bin/pytest -q; MR; read the
         regression:mapping-gate delta
- [ ] 6. After deploy, remeasure; stop when only residuals remain
```

## Time window (coverage dashboard)

- `last_updated > CURRENT_TIMESTAMP() - INTERVAL 3 HOUR`
- `first_publish_time > CURRENT_TIMESTAMP() - INTERVAL 48 HOUR`
- Reasons `MAPPING_FAILED`, `UNMAPPED` only (exclude pricing / stake /
  creator declines)

## Inventory SQL

Substitute `{project}` → `marketmaking-test` | `rs-marketmaking`.

| Platform | File |
|----------|------|
| Polymarket | `BigQuery/sql/rfq_unmapped_legs_polymarket.sql` (+ `_drilldown`, `_samples`) |
| Kalshi / ProphetX | `BigQuery/sql/rfq_unmapped_legs_kalshi_prophetx.sql`, `rfq_unmapped_legs_kalshi_drilldown.sql` |
| Kalshi titles | `BigQuery/sql/rfq_kalshi_title_probe.sql` |
| UFC | `BigQuery/sql/rfq_ufc_fight_true_gaps.sql` |
| crypto.com | `BigQuery/sql/crypto_rfq_unmapped_classify.sql`; see `crypto-mapping-gap-investigation` skill |

### Join keys

| Platform | RFQ field | Mapping field | Note |
|----------|-----------|---------------|------|
| Kalshi | `platform_mapping.market_ticker` + `$.side` | `source_ids.market_id` + `selection_id` (`sportsbook='Kalshi'`) | Join ticker **and** side; Yes mapped does not clear No |
| Polymarket | `platform_mapping.token_id` (= position_id) | `source_ids.selection_id` (= clob) | via `raw_ingestion_us.polymarket_position_token_bridge` |
| crypto.com | legs in `metadata.quote_details` (`qr.symbols[].legs[].symbol`) | `source_ids.symbol` | `reason_detail` is only `{n} of {m} legs mapped` |

`markets_us.market_mapping` is partitioned on `start_date`; always filter
it.

These joins compare ids for equality. Do not parse the ticker, slug or
symbol to decide what a leg is.

### Maker-lag vs true gap

```text
unmapped RFQ leg
  └─ id already in market_mapping? → maker-lag: maker side, not a mapper change
  └─ not in market_mapping + Optic-priceable → true gap
        ├─ venue field / vocab / venue table missing → fix in code (this skill)
        ├─ Optic fixture missing or beyond horizon → residual
        └─ expected-ignored shape (table below) → residual
```

## Expected residuals (do not invent mappings)

| Shape | Why |
|-------|-----|
| Polymarket moneyline / exact-score **No** (matcher emits Yes only) | Residual |
| Kalshi game-winner **No** | Mapped as the opponent's Yes only where `complements_hold` (`mappers/kalshi_complement.py`): no-draw sports or `_RULES_READ_LEAGUES` (nfl, cfl, ufc, mlb, nhl). Soccer 3-way No maps as double chance. Others (ncaaf, cricket, npb / kbo, boxing) stay residual; read the league's settlement rules before adding it |
| Polymarket team-to-advance, HT lead, half-corners, any-other score | Residual unless a recognizer exists |
| Handicap crumbs `Name (±1.5)`, `Set Handicap:` / `Map Handicap:` | Not names; never alias them |
| Esports `Map N Winner` / `Game N Winner` | Unmappable |
| Beyond Optic horizon | Residual until Optic lists it |
| Past events whose fixtures left Optic | A fix only helps future events |
| crypto.com MLB 1st–3rd inning spread / total | No Optic counterpart (F3 ML 3-way is mapped as `f3_moneyline_3way`) |
| Polymarket leg dropped with stderr `passthrough identity: dropping clob …` | Optic's own Polymarket id named another player or game (`mappers/poly_passthrough_identity.py`). Missing beats wrong. A nickname of the same person is a code alias (add-team-alias), never a loosened `names_fit` |

## Fixing a true-gap class

Find the owning module in the `CLAUDE.md` table and change it there:

- Unknown market shape → venue or sport vocab (`mappers/vocab/*_markets.py`,
  `mappers/vocab/kalshi_scopes.py`) or the sport profile
  (`mappers/profiles/`).
- Venue does not reach a league → venue league table (add-new-league skill).
- Name / id does not bind → code alias or id table (add-team-alias skill).
- Matcher drops a typed field it should read → the venue module in
  `mappers/exchanges/`.

Each fix gets a test under `tests/mappers/` that fails without it, and the
mapper must skip, not raise, on the next unknown instance of the class.

`gap-propose` still runs and drafts console cards. Treat its output as a
list of candidate code changes; never approve the cards.

## Related

- `.cursor/skills/add-team-alias/SKILL.md`
- `.cursor/skills/add-new-league/SKILL.md`
- `.cursor/skills/crypto-mapping-gap-investigation/SKILL.md`
- `docs/rfq-mapping-gap-classification.md`, `docs/mapping-coverage-grafana.md`
