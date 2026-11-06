# RFQ mapping-gap classification

A true gap is fixed in code (see `CLAUDE.md`): vocab in
`mappers/vocab/*_markets.py`, parser profiles in `mappers/profiles/`,
venue league catalogues in `mappers/exchanges/*_leagues.py`, aliases in
`mappers/vocab/*_aliases.py` / `mappers/vocab/crypto_team_ids.py`. Add a
test in `tests/mappers/`, open an MR, read the `regression:mapping-gate`
row delta; removed rows need a waiver in `regression/waivers.toml`. No
tip pins, no console cards.

The dated wave sections (A3 to E) are historical notes. Their
`config/<league>/team_aliases.toml`, tip `ignore`/`map` and console
Review steps are retired.

Working taxonomy for `reporting_us.rfq_latest` legs that lack
`optic_fixture_id` / `market` / `selection` under `MAPPING_FAILED` /
`UNMAPPED`. Evidence SQL lives under `BigQuery/sql/rfq_*.sql`.

Workflow: inventory → classify → code change + test → MR + gate →
deploy → remeasure.

## Decision tree

1. **Non-optic / empty-leg** → out of mmmapper market-rule path (Wave D).
2. **Identity resolves + row already in `markets_us.market_mapping`** →
   **maker-lag** (Wave C), not an alias/rule gap.
3. **Optic-priceable + not in `market_mapping`** → **true gap**:
   alias / market_rule / fixture / horizon / optic-unpriced / expected-ignored.

Join key for Kalshi inventory: RFQ `platform_mapping.market_ticker` ↔
`market_mapping.source_ids.market_id` (`sportsbook = 'Kalshi'`).

---

## Optic-unpriced shapes (expected residual)

Leave unmapped; do not invent Optic coords.

| Shape | Platforms | Notes |
|-------|-----------|-------|
| **Half-corners** | Polymarket soccer | Full-game corners may map; 1st/2nd-half corners have no Optic market (`polymarket.py` soccer corners comment). |
| **Exact score** | Polymarket soccer | Recognizer exists (`soccer_exact_score_rule`); only map when Optic prices `correct_score` for that league. Otherwise residual. |
| **Doubles** | Kalshi ATP/WTA/ITF; Polymarket tennis | Kalshi: no doubles scope in `mappers/vocab/kalshi_scopes.py`, so doubles stay unmapped. Poly: slash-joined names dropped in tennis match-winner parse. |

---

## Wave A3 — Kalshi UFC true gaps

- Series: `KXUFCFIGHT` moneyline only for this wave.
- Prod probe (`rs-marketmaking`, 2026-08-11): ~33k true-gap occ vs ~220k
  maker-lag occ on `KXUFCFIGHT`.
- **Only future true-gap event:** `KXUFCFIGHT-26AUG15WELORO`
  (Wells vs Orolbay Uulu). Aliases `WEL` / `ORO` pinned in
  `config/ufc/team_aliases.toml` with kalshi_raw title evidence.
- **Not in `market_mapping` after pin** ⇒ remaining work is **Wave Sync**
  (publish mappings), not more aliases.
- Past Aug-8 card still appears in the RFQ window; stubs `VAZ` / `CAN`
  pinned. Do **not** steal `FOR` (Tyrell Fortune) for Foro Antunes.

SQL: `BigQuery/sql/rfq_ufc_fight_true_gaps.sql`,
`BigQuery/sql/rfq_kalshi_title_probe.sql`.

---

## Wave B residuals (actionable vs document-only)

### KXLEAGUESCUP / KXCLUBF game moneyline

- **Leagues Cup:** Aug-9 true-gap sides (`AME`, `ATX`, `SD`, …) already
  resolve via `config/leagues_cup/team_aliases.toml`. No new pins; residual
  is publish / fixture / lag, not missing codes.
- **Club friendlies:** evidenced non-colliding stubs added 2026-08-11
  (`PAL`, `CAR`, `CHD`, `FRO`, `MCI`, `ATM`, `LEC`, `SSM`, `OLO`, `SAB`,
  `PAR`, `SAM`, `LEE`, `PRO`, `IMP`, `SOC`, `TVA`, `OLM`, `ATH`, plus
  `VOL`/`KAL` title refresh).
- **2026-08-11/12 Optic pins:** `BOL`/`REC`(HUE), `MDL`(CML)/`ULG`(LAN),
  `ALC`/`MAJ`; Thai `THA`/`AYU`/`PAD`/`CHO` stubs without Optic rows.
- **Left untouched (collisions):**
  - `UNI` → `FCU` (Union Berlin); Salamanca on `KXCLUBFGAME-26AUG11UNICOR`
    also uses `UNI`.
  - `VIL` → `VI2` (Villarreal B); Villarrobledo on `SOCVIL` also uses `VIL`.
  - `PAU` → `BGP` (Pathum); `PAULEE` is the same Pathum code.

### ATP doubles — expected out-of-scope

Unmapped on Kalshi (no doubles scope in `mappers/vocab/kalshi_scopes.py`). Polymarket
doubles (slash names) similarly dropped. Do not expand Optic doubles mapping
in this plan.

### EPL Polymarket — beyond horizon

Prod bridge samples (2026-08-11): heavy volume on **2026-08-21 … 08-24**
match moneylines / totals / team totals (e.g. `epl-ars-cov-2026-08-21-*`),
~10–13 days out from the probe date — outside the usual Optic short
horizon. Also exact-score slugs on the same fixtures. **Confirm as
beyond-horizon / optic-unpriced residual; do not invent mappings.**

### MLB Kalshi player props — expected ignored

Market type comes from Kalshi's typed scope (`Sport.BASEBALL` in
`mappers/vocab/kalshi_scopes.py`), never the series ticker. Scopes listed
there ("Hits", "Home Runs", "RBIs", "Stolen Bases", "Strikeouts",
"Outs Recorded", ...) map when Optic joins; an unlisted scope stays
unmapped.

---

## Wave C — Maker-lag join-key hypothesis

**Symptom:** RFQ leg optic fields null, but the same Kalshi `market_ticker`
(or Polymarket clob / selection id) **is** present in `market_mapping`.

**Hot spots:** Kalshi `KXNFL` + `KXUFC`; Polymarket `itf` / `atp` / `mlb`.

**Hypothesis to verify (investigation only):**

1. Maker joins RFQ `platform_mapping.market_ticker` (+ side) to
   `source_ids.market_id` (and maybe a different side field than we write).
2. Polymarket path: RFQ `token_id` is **position_id**; mapping publish uses
   `source_ids.selection_id` = **clob_token_id** — requires
   `raw_ingestion_us.polymarket_position_token_bridge`.
3. Stale maker cache / sportsbook string mismatch / mapping freshness.

File findings for maker repos; only change mmmapper if our write path’s
join key is wrong (`BigQuery/load_mappings.py`).

---

## Wave D — Crypto `MAPPING_FAILED` empty legs (updated 2026-08-12)

Crypto.com combo RFQs fail with `MAPPING_FAILED` and **`legs = []`**. The
exchange **did** send legs — they live in `metadata.quote_details` /
`qr.symbols[].legs[]`. The Java maker (`mmcryptorfq`) aborts on the first
unmapped `NX.F.OPT.*` symbol and never writes structured `legs`.

**Join key** (docs/adding-crypto.md ~1112–1119): `markets_us.market_mapping`
`sportsbook='crypto.com'` `JSON_VALUE(source_ids,'$.symbol')` exact, then
strip `\\.YYYYMMDD$`. Do **not** join RFQ symbol to Optic `market_id` /
`ARP-…` keys.

Remeasure SQL: `BigQuery/sql/crypto_rfq_maker_lag_vs_true_gap.sql`.

### Last-hour split (prod `rs-marketmaking`)

| When | IN mapping (maker-lag) | NOT in mapping (true gap) |
|------|------------------------|---------------------------|
| Diagnosis (earlier 2026-08-12) | 62 symbols / **4,888** RFQs | 42 symbols / **271** RFQs |
| Remeasure (same day, pre-deploy) | 68 symbols / **7,182** RFQs | 101 symbols / **837** RFQs |

Maker-lag share stayed ~90%+. **mmmapper cannot drop the IN-mapping class** —
those rows already exist in BQ. Success for Track A is a maker cache refresh.

### Track A — mmcryptorfq handoff (volume win)

Error string (legacy): `reason_detail = "no mapping for symbol NX.F.OPT.…"`.
Since 2026-09 the maker writes `"{n} of {m} legs mapped, minimum is 2"` and
stores NX symbols in `metadata.quote_details` (`qr.symbols[].legs[].symbol`).
Harvest / Grafana SQL must unnest `quote_details`, not regex `reason_detail`
alone. Python pricing expects pre-mapped legs.

**Asks:**

1. Confirm lookup is `JSON_VALUE(source_ids,'$.symbol')` + `sportsbook='crypto.com'`.
2. Cache refresh cadence after pipeline `load_mappings`.
3. Exact-then-maturity-suffix-stripped lookup (`\\.YYYYMMDD$`).
4. Optional: persist partial `legs[]` on fail so dashboards do not parse
   `metadata.quote_details`.

**Evidence (row exists in `market_mapping`; maker still fails):**

| Symbol | 1h RFQs | Sample `external_rfq_id` |
|--------|---------|--------------------------|
| `NX.F.OPT.MLB-00002-260812-M.O.1.1.20261130` | 1393 | `5062045982365883988` |
| `NX.F.OPT.MLB-00003-260812-M.O.1.1.20261130` | 1064 | `5080060380983010257` |
| `NX.F.OPT.MLB-00001-260812-M.O.1.1.20261130` | 888 | `5080060380983010975` |
| `NX.F.OPT.UFC-00001-260815-M.O.1.1.20261231` | 217 | `5080060380983010194` |

Earlier sample RFQ `5080060380983008623` (same MLB-00002 moneyline).

### Track B — mmmapper (true gaps; needs deploy + pipeline tick)

Harvest registry now includes MLS/UEL/UCOL/ARP/BRSA. `crypto_id` pins from
`crypto_security_def` (2026-08-12): MLS full slate; ESP ALA/GET/RAY/SEV;
UEL/UCOL clubs with EXTERNAL ids. EPL: catalogue present, **0** SecurityDef
EXTERNAL ids — do not invent.

Remeasure true-gap mix (1h, pre-deploy): MLB ladder 706, TENNIS 140, ESP 77,
EPL 38, UEL 26, MLS 22, ITSA 20, SOCCER 19, UCOL 10, NFL 7.

**Residuals (do not invent):**
- MLB high M.O. slots (`.53`, `.314`, `.293`, …) — prop/ladder tail
- `NFL-*-260913-*` — outside 96h Optic horizon
- `TENNIS-*` stale / left active (e.g. `260811`)
- `NX.F.OPT.SOCCER-0001-*` — opaque meta_league, not EPL/ESP
- `ITSA-*` — no Italy Serie A CRYPTO module
- `EPL-*` — upstream identity wait (no EXTERNAL ids)
- ESP Osasuna/Celta (`ESP-00003-260816`) — no SecurityDef `crypto_id` yet

---

## Wave E — ITF publish + Poly Europa/Conference (2026-08-11)

### Kalshi ITF / ITFW

Large alias batches are in `config/itf_men/team_aliases.toml` and
`config/itf_women/team_aliases.toml` (collision-aware multimaps). **Aliases
alone do not lift RFQ coverage** until:

1. Deploy this branch to the mapping VM (`infra/deploy.sh`).
2. Next `run_pipeline.sh` tick runs `mappers.run --write-mappings` +
   `BigQuery.load_mappings` for `itf_men` / `itf_women`.
3. Re-run `BigQuery/sql/rfq_unmapped_legs_kalshi_drilldown.sql` — expect
   `KXITFMATCH` true-gap occ to drop; residual = doubles (ignored) +
   missing Optic fixtures + unresolved codes.

**2026-08-11 top true-gap pin:** `KXITFMATCH-26AUG11BOBMEN` (kalshi_raw
title Bobo vs Mendez). Optic competitor ids from
`opticodds_us.opticodds_fixtures`: Dakotah Bobo `1FD7BEF293C93146` →
`[BOB]`, Mathias Mendez `BF3C97BC67098E60` → `[MME]` claiming `MEN`
alongside Thomas Menzel `[TMH3]` (multimap arbitrates).

(Historical: this wave pinned via the console. Retired; see `CLAUDE.md`.)

### Polymarket `uel` / `col` (+ `lec`)

Modules `europa_league.py` / `europa_conference_league.py` (+ Leagues Cup
poly `lec`) are on the **main API fetch** (not `BQ_OPTIC_LEAGUES`) because
Optic `/fixtures/active` returns fixtures. After deploy, the 15-min pipeline
publishes native poly rows. Expected residual: half-corners, any-other
score, 2H BTTS, team-to-advance (no poly recognizer), Optic-missing dates.

Inventory prefixes include `uel` / `col` / `lec` in
`rfq_unmapped_legs_polymarket*.sql`.

**2026-08-11 re-measure (prod vs test):**

- After `test`→`main` + `deploy:mapping-pipeline:prod` (`e5315be`), prod Optic API returns
  fixtures (`uel` 13 / `col` 30). Post-deploy tick stamped **`uel`** poly
  (`europa_league` Aug 13 ≈ 1425 MM rows).
- **`col` aborted** that tick: team_bootstrap created
  `config/europa_conference_league/team_aliases.toml` (empty-abbr STF3) but
  skipped unicode Optic abbr `ŽAL` (Žalgiris), so the completeness gate
  raised. Fix: commit `[ŽAL]` stub in that TOML and redeploy / remap.
- Same-slug “in bridge but not in MM” for UCL often means the RFQ leg is the
  **No** outcome of `THREE_WAY_FIXED` / exact-score (matcher emits affirmative
  Yes only). Over/Under is balanced; do not treat No-side three-way as a
  missing-alias bug.

---

## Related

- Inventory: `rfq_unmapped_legs_polymarket.sql`,
  `rfq_unmapped_legs_kalshi_prophetx.sql`, drill-downs.
- Code-owned rule layout: `CLAUDE.md`.
- Coverage dashboard copy-paste SQL: `docs/mapping-coverage-grafana.md`.
