# CLAUDE.md — `mmmapper` <!-- L2 repo card. ≤150 lines. Template: docs/templates/REPO-CARD.md (mm-workspace). -->
<!-- card_version: 1.1 · updated: 2026-11-05 · repo_commit: 60991eb9 (2026-11-05) · plane: mapping -->

The hard rules are the next section. Module cards: `mappers/CLAUDE.md`, `console/CLAUDE.md`, `BigQuery/CLAUDE.md`.

## Agent rules — read before changing how a venue market maps
**Mapping rules are code.** Leagues, market types, selection vocab, venue league ids and aliases are Python,
reviewed in an MR and gated by the mapping regression gate (`regression:mapping-gate`).

| What | Where |
|---|---|
| Market-type vocab per sport | `mappers/vocab/*_markets.py`, `mappers/market_types.py` |
| Parser profiles (sport × venue grammar) | `mappers/profiles/` |
| Venue league catalogues (typed venue league id → Optic league) | `mappers/exchanges/*_leagues.py` |
| Venue-specific matching | `mappers/exchanges/<venue>*.py` |
| Code-owned alias / id tables | `mappers/vocab/*_aliases.py`, `mappers/vocab/crypto_team_ids.py` |
| Code-seeded market rules | `mappers/seed/*_rules.py` |

A mapping change = edit code, add a test next to it, `GCP_PROJECT=rs-marketmaking .venv/bin/pytest -q`, open the MR,
let the gate show the row delta. Removed rows need a waiver in `regression/waivers.toml`; added rows are reported, not gated.

- **The BigQuery rule-set tip is retiring** (`mapping_rule_current`, `mapping_leagues` / `mapping_market_rules` /
  `mapping_entities`, `P_*` / `S0_*` rule sets, `mappers/seed/sot.py`, `tip_*.py`). Never add a league, rule, alias or
  pin to it; no `activate_mapping_rule_set` as a fix. New code must not read it; when you touch code that does, move the
  rule into code. Code wins when a code table and the tip disagree (`_with_code_crypto_team_ids` in `mappers/pipeline.py`
  still lets the tip win — debt). Known gap: the league run set (`mappers/run.py` `load_tip_leagues`) and
  Polymarket / ProphetX / crypto.com venue league ids (`mappers/seed/tip_factories.py`) still come from tip rows; a
  brand-new league on those paths needs that moved to code first — raise it, do not add a tip row.
- **The mapping console is dead** (`console/`, `mappers/control_plane/`: Editor, Cart, Proposed, Mapper Chat, gap-propose,
  pin verify). Do not fix a gap by staging a console pin or extend the console. Gap output is a list of code changes.
- **No ticker or symbol parsing.** Sides, strikes, market types and identity come from typed venue fields (Kalshi
  `floor_strike` / `strike_type` / `custom_strike`, PolyUS gateway `league_id` and sides, Optic ids), written out
  explicitly. Never split, regex or suffix-match a ticker, slug or symbol. Existing parsing is debt: replace it when touched.
- **Never loosen name matching** (`names_close`, `names_fit`) to bind a venue id. A wrong bind is worse than an unmapped
  market; pin the id in the code table instead.
- GitLab, not GitHub (`glab`, merge requests). `git fetch origin` and branch from `origin/main`.
- No new BigQuery tables in `rs-marketmaking` without asking. Makers only look up mmmapper rows; guards and vocab live here.
- Files stay at or under 500 lines (CI quality job).

## What this is
The estate's cross-venue market mapper. Every 15 min a **GCE VM tick** fetches each venue's catalogue, builds rows on
the OpticOdds schedule (Optic REST v3 is the spine; every row carries Optic `game_id`/`fixture_id`/`market_id`/
`selection`), binds each venue contract by typed ids and code tables, and MERGEs into **`markets_us.market_mapping`**
(one row per game × market × outcome × `sportsbook`). Venues: Kalshi, ProphetX, crypto.com, Polymarket (global),
Polymarket US, Novig, DKEX, SX Bet, Underdog; Betfair/DraftKings by Optic passthrough; Huddle/Runshop when the tip asks.
Downstream: every maker looks rows up (never maps itself); `oom-fold-rank` folds them into
`opticodds_us.opticodds_mapping`; MMOpticOddsV2 derives its stream coverage from `market_mapping` since 2026-10-19.
Maintained by Silviu Simeria + Victor Popa.

| Unit | Where | Schedule / size | Prod deploy (manual) · last green |
|---|---|---|---|
| Mapper VM | GCE `market-mapping` (test `market-mapping-test`) — `infra/crontab`, `infra/deploy.sh` | tick `*/15` + cron lines (kalshi/novig raw, ITF synth, PM bridge, token resolutions, cleanup) | `deploy:mapping-pipeline:prod` (needs gate + pyright + quality) |
| Mapping console + CronJobs gap-propose, **oom-fold-rank**, mismap-alert | GKE ns `mapping-console` — `deploy/k8s/mapping-console/` | Deployment 1; `*/30`, `2,17,32,47`, `7 * * * *` | `deploy:mapping-console:prod` (needs gate) |
| dkex-catalogue | ns `mapping-console`, `dkex` pool — `deploy/k8s/dkex-catalogue/` | CronJob `4,19,34,49` | `deploy:dkex-catalogue:prod` |
| ai-validation (Gemini judge) | ns `mapping-console` — `deploy/k8s/ai-validation/` | CronJob **suspended** (`base/cronjob.yaml:23`); VM cron removed | `deploy:ai-validation:prod` |
| goalscorer-mapper (Kalshi goalscorer + Slack bot) | ns `goalscorer-mapper` — `deploy/k8s/goalscorer-mapper/` | bot 1; pregame `0 5,13,21`, listing `*/10`, reconcile, pnl | `deploy:goalscorer-mapper:prod` |

Console: https://mapping.mm.whiteswandata.com (IAP gateway, `mm-consoles-gateway/prod/02-configmap-nginx.yaml:177`); one
uvicorn serves API + SPA. Test env is stale (branch `test` last pushed 2026-09-30); MRs go straight to `main`.

## Run · test · gate · deploy
```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt \
  && .venv/bin/pip install ruff bandit pip-audit interrogate pytest pytest-cov pytest-xdist PyYAML pyright
GCP_PROJECT=rs-marketmaking .venv/bin/pytest -q                  # AGENTS.md quick check (tests/, ~4.8k tests)
.venv/bin/pyright .                                               # CI job pyright
# CI quality job (mm-ci-templates v1.3.1; ruff warn-only; pytest -n auto --dist loadscope):
GCP_PROJECT=marketmaking-test QUALITY_SRC="mappers BigQuery fetch regression goalscorer" QUALITY_COV_PKG=mappers \
  QUALITY_COV_MIN=0 QUALITY_INTERROGATE_MIN=75 COVERAGE_CORE=sysmon bash ../mm-ci-templates/scripts/quality.sh
# NOT `mise run quality` — scripts/run-quality.sh scans fewer dirs and clones templates v1.1.1
# regression:mapping-gate (prod runner, read-only SA mmmapper-regression@) replays prod *_fetch_raw ticks + incidents.toml
#   through candidate vs prod SHAs; removed rows need regression/waivers.toml. Not runnable locally.
```
Open MRs with `Refs #N`, never `Closes`. A mapping change = code + test + MR to `main` + gate row delta, **then someone presses `deploy:mapping-pipeline:prod`**
(owner-confirmed). Recipes: `.cursor/skills/add-new-league/`, `.cursor/skills/add-team-alias/`.

## Layout
| Path | What |
|---|---|
| `infra/crontab` · `infra/run_pipeline.sh` | what prod runs and in what order (fetch → map → load → checks) |
| `fetch/__main__.py` · `fetch/<venue>.py` | venue inputs; Optic required, others parallel |
| `mappers/run.py` · `mappers/pipeline.py` | league fan-out · the matcher (`pipeline.run()`) |
| `mappers/exchanges/<venue>*.py` · `mappers/vocab/` · `mappers/profiles/` | where a venue mapping is fixed (ids, aliases, grammar) |
| `mappers/seed/code_leagues.py` · `tip_factories.py` | `CODE_LEAGUES` · venue league ids (code vs legacy tip) |
| `BigQuery/load_mappings.py` | stage + MERGE key, deletes, override lane, post-load ALERT checks |
| `regression/live_gate.py` · `materialize.py` · `waivers.toml` | the mapping gate and what it covers |
| `deploy/k8s/mapping-console/overlays/prod-us/env.yaml` | prod console flags (activation, chat, override lane) |

## Contracts it depends on
- **Writes**: `markets_us.market_mapping` (+`_stage`), `market_mapping_ai_validation`, `mapping_audit_events`,
  `mapping_work_items`, `optic_passthrough_blocklist`; `opticodds_us.opticodds_mapping` (fold),
  `opticodds_us.opticodds_fixtures` (synthetic only); `raw_ingestion_us.*_fetch_raw`, `kalshi_raw`, `novig_raw`,
  `dkex_raw`, `polymarket_position_token_bridge`, `polymarket_token_resolutions`. `BigQuery/client.py:33` refuses DML
  outside `markets_us` / `opticodds_us` / sandbox.
- **Reads**: `opticodds_us.{opticodds_fixtures, prices_dedup_state, mapping_override}`, `processed_upstream_us.crypto_*`,
  `reporting_us.rfq_latest`, legacy tip tables (`mapping_rule_*`, `mapping_leagues`, `mapping_entities_current`).
- **Pub/Sub**: publishes `mapping-override-us` (→ `opticodds_us.mapping_override`), `application-alerts`, `oom-catalog-changed`.
  No Redis, no NATS, no MMutils import.
- **mm-infrastructure** `modules/mapping_control_plane/` (GSAs, IAM, VM deploy SA, gate SA, `dkex` pool, raw schemas);
  mm-consoles-gateway (console route); mm-ci-templates v1.3.1.

## Gotchas
1. **Merged ≠ live**: the VM only changes when `deploy:mapping-pipeline:prod` is pressed (`.gitlab-ci.yml:594-612`).
   Read the job or `mapper_git_commit` on fresh rows before saying "deployed" (MISTAKES 2026-10-15, 2026-10-20).
2. **One exception drops a whole league for every venue** while the tick exits 0 (`mappers/run.py:86-102`, prints
   `ALERT:`). Check the tick log before blaming Optic (MISTAKES 2026-10-22, ATP Challenger).
3. **The "dead" console can still change prod mapping without an MR**: prod sets `MAPPING_CP_ALLOW_ACTIVATE=1`
   (`overlays/prod-us/env.yaml:26`, `mappers/control_plane/settings.py:61-63`), every IAP user is APPROVER
   (`auth.py:42`), and the tick reads the activated tip (`pipeline.py:2521-2528`). `overlays/prod-us/sa.yaml:2`
   ("Activation stays disabled") is wrong.
4. **The BQ tip is still a live input**: the run league set is tip leagues (`mappers/run.py:46`) + `CODE_LEAGUES`, and
   aliases are seeded from it; the tip beats `CRYPTO_TEAM_IDS` unless overridden in `CRYPTO_TEAM_ID_OVERRIDES`.
   PolyUS/Underdog/DKEX/SX/Novig league ids are code (memory `underdog-leagues-are-code-in-mmmapper`).
5. **oom-fold-rank is load-bearing** although it ships with the console (`BigQuery/sql/oom_fold_rank.sql:105`); when
   joining `market_mapping` and `opticodds_mapping`, split on `mapping_source` or you double count (skill `mm-mapping-coverage`).
6. **The gate does not cover DKEX, Runshop, Huddle** (`regression/materialize.py` `NOT_IN_FETCH_TABLES`) — green is no
   evidence there. SX Bet and Underdog are replayed and diffed, but checked for `contract_reused` only.
7. **A new sportsbook must be replayed through the loader**, not just `mappers.run`: the 2026-09-24 Underdog fetcher hit
   the duplicate-key guard and froze test mapping for every book (MISTAKES 2026-09-24; `load_mappings.py:46-52`).
8. **Sides**: SX `selection_id` suffix is the maker's outcome (memory `sxbet-mmmapper-selection-id-suffix-is-maker-side`);
   PolyUS `long`/`short` rows are sideless Optic passthrough — never translate to yes/no
   (memory `polyus-long-short-side-is-unverified-optic-passthrough`).
9. **AI validation is off**: VM cron removed and the GKE CronJob is `suspend: true`; `docs/ai-validation.md` may still describe the old schedule.
10. **Stale docs**: README "no code-owned league list" (`README.md:210-212`; `CODE_LEAGUES` exists). Goalscorer runs 3×/day (`deploy/k8s/goalscorer-mapper/base/pregame-cronjob.yaml`).
11. **DKEX/Underdog name misses**: add an exact id pin in `mappers/exchanges/dkex_names.py` (`OPTIC_IDS_BY_DKEX_NAME`, `OPTIC_PLAYER_IDS_BY_DKEX_NAME`), never widen the matcher.

## Where to look
- Repo docs: `docs/adding-{underdog,dkex,sxbet,novig,crypto}.md`, `docs/goalscorer-mapper.md`, `docs/ai-validation.md`, `docs/polymarket-bridge.md`
- In-repo recipes: `.cursor/skills/add-new-league/`, `.cursor/skills/add-team-alias/`.
- Workspace-only (resolve inside `mm-workspace`, not this repo): skills `mm-mapping-coverage` (join keys, add a league),
  `sxbet-unmapped-fix`, `check-crypto-rfq`, `investigate-rfq-verdict`; `context/known-issues/mmmapper.md`. `mm-mapping-pipeline` is the **Huddle** matcher, not this repo.
