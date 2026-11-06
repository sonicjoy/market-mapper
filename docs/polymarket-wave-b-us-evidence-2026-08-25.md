# Wave B / US evidence — 2026-08-25

> Historical note. Tip/console steps here are retired; see CLAUDE.md.

Artifacts: `scratch/poly_wave_b_us_evidence_2026-08-25.json`

## Card B — `korea_k1` / `kor`

**Not a Path 2 off problem.** Tip already has:

- `slug_prefix=kor`, `optic_league_id=korea_-_k1_league`
- `fixture_source=bq`, horizon 1440h
- Kalshi `KXKLEAGUE` enabled

Baseline: ~71k occ as `actionable game-line gap` (Path 2 on + Optic name match).

Live probes:

| Check | Result |
|-------|--------|
| Optic fixtures (`korea_-_k1_league`, -2d..+40d) | **37 fixtures, 20 with_odds** |
| `market_mapping` rows for `league=korea_k1` (same window) | **0 rows across all sportsbooks** |
| Bridge moneyline samples | Present (`kor-bch-dae1-2026-09-05-*`, etc.) |

**Root cause hypothesis:** BQ-optic pipeline is not publishing `korea_k1` rows at all (no Optic spine → Path 2 has nothing to stamp onto). Next ops checks:

1. Confirm `korea_k1` is in `BQ_OPTIC_LEAGUES` and the BQ-optic CronJob ran recently.
2. Mapper / BQ-optic logs for `korea_k1` completeness gate / alias bootstrap / empty prices.
3. `opticodds_prices` presence for those fixture ids.

**Do not** re-propose the league tip. Fix is pipeline / Optic-BQ ingest, not another Review card.

## US track (Wave US)

Ticker-equality join to `Polymarket (USA)` `source_ids.market_id` (3h/48h unmapped US legs):

| Metric | Value |
|--------|------:|
| Unmapped US legs | 152,589 |
| Already in MM (maker-lag) | 43,300 (~28%) |
| True absence | 109,289 |
| Distinct tickers | 809 |

Top unmapped wrapper × inner (occ):

- `aec-itfwo` 37.9k, `aec-setkameua` 13.8k, `atc-lal` 10.0k, `aec-npb` 7.2k,
  `aec-ufc` 6.3k, `aec-kbo` 6.2k, `atc-epl` 6.0k, `atc-kl1` 5.5k, …

`Polymarket (USA)` soccer rows in MM for wired soccer leagues: **0**.

### Findings

1. **~28% of US unmapped volume is maker-lag** — ticker already published; maker cache / join.
2. **US soccer is Optic passthrough absence** (`us_optic_no_passthrough`) — wrappers like `atc-lal` / `atc-epl` / `atc-kl1` have no Path 2 fallback; Optic is not exposing `polymarket_usa_` on soccer.
3. **`market_id` without `selection_id`** (both sides share one ticker) remains a candidate maker-lag cause — flag to maker team.
4. No engine change required in mmmapper today.

## Cards F / G

Esports + cricket remain **needs_code** until tip factory gains non-soccer Path 2 recognizers or Python league modules land + deploy. Soccer tip-only poly fix (`soccer_market_rules` on empty tip poly) is in this branch and unblocks Cards C–E after deploy.
