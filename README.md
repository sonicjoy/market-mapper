# Market Mapping

Fetch events and markets from Optic, Kalshi, ProphetX, Polymarket,
Polymarket US, crypto.com, Novig, DKEX, SX Bet, Underdog and Huddle,
then produce a JSON mapping between exchanges
where they represent the same real-world outcome, and load it to
BigQuery. Optic is the schedule spine. For World Cup, Runshop
(betbuilder) fixture and market ids are stamped onto Optic rows so
downstream clients can resolve `txOddsFixtureID` + `market_id` prices
from the same `markets_us.market_mapping` table.

Mapping rules are code. Leagues, market vocab, venue league ids and
aliases live in Python under `mappers/`, ship by merge request and are
checked by the mapping regression gate. Rules for agents and humans:
[`CLAUDE.md`](CLAUDE.md).

## How it works

Four independent runtimes. Do not treat VM `post_load` as gap harvest,
and do not hold `pipeline.lock` for the Polymarket bridge.

| Runtime | Where | Cadence |
|---------|--------|---------|
| **Mapper** | GCE `market-mapping-test` / `market-mapping` via `infra/cron_pipeline.sh` | every 15 min (`pipeline.lock`) |
| **Polymarket position bridge** | same VMs via `infra/cron_polymarket_bridge.sh` | `8,23,38,53` (`polymarket_bridge.lock`) |
| **[gap-propose](docs/mapping-rules/gap-propose.md)** | GKE CronJob `gap-propose` in namespace `mapping-console` | every 30 min; RFQ harvest → console cards (legacy; not a way to ship mapping) |
| **[goalscorer mapper](docs/goalscorer-mapper.md)** | GKE namespace `goalscorer-mapper` (own image + deploy jobs) | pre-game 4×/day, reconcile + PnL daily, Slack bot always on |

The mapper tick (`infra/run_pipeline.sh`):

1. **Fetch** (`python -m fetch`) — runs each exchange fetcher as a
   subprocess and writes JSONL snapshots to a timestamped directory
   `data/<YYYY-MM-DD>/<HH_MM>/` (e.g. `optic_fixtures_odds.jsonl`,
   `kalshi_markets.jsonl`, `polymarket_markets.jsonl`,
   `runshop_fixture_chain.jsonl` when `world_cup` is on the tip). Optic
   is required (it is the schedule index); the other exchanges are
   optional and failures there still produce partial mappings. Which
   leagues to fetch still comes from the legacy tip. Runshop fetch reads
   the betbuilder price API for active `txOddsFixtureID`s, then enriches
   them from poly / txodds Postgres (see `docs/adding-runshop.md`).
2. **Map** (`python -m mappers.run <data_dir> --write-mappings`) —
   for each tip league, builds canonical rows from the Optic schedule,
   matches Kalshi / PX / Polymarket / crypto.com / other venue markets onto
   them, reconciles against Optic's own `source_ids` as ground truth,
   and (World Cup) stamps Runshop fixture + market ids onto Optic-merged
   rows. Writes `<data_dir>/mappings.jsonl`.
3. **Load** (`python -m BigQuery.load_mappings <data_dir>/mappings.jsonl`)
   — merges rows into `markets_us.market_mapping` in the project
   named by `GCP_PROJECT`. Each exchange (Kalshi, Prophet X, Polymarket,
   crypto.com, Runshop, prediction markets from Optic `source_ids`)
   becomes one row per sportsbook.

The Polymarket **position bridge** (combos-rfq catalog → BQ) is a
**separate** VM cron. It must not hold `pipeline.lock`. See
[`docs/polymarket-bridge.md`](docs/polymarket-bridge.md).

**AI validation** (`python -m BigQuery.ai_validation`) runs on its own
two-hourly cron rather than in the tick. Gemini judges whether each
Kalshi / Polymarket / crypto.com / Novig row we published really carries
the contract we claim, once ever per mapping, into
`markets_us.market_mapping_ai_validation`. See `docs/ai-validation.md`.

VM crontab (raw stashes, ITF synth, disk cleanup, …) is
[`infra/crontab`](infra/crontab), applied on every mapper deploy.

## Mapping rules are code

Where rules live (full table in [`CLAUDE.md`](CLAUDE.md)):

- market vocab: `mappers/vocab/*_markets.py`, `mappers/market_types.py`
- parser profiles (sport × venue): `mappers/profiles/`
- venue league tables: `mappers/exchanges/dkex_leagues.py`,
  `mappers/exchanges/sxbet_leagues.py`, `NOVIG_LEAGUE_NAMES` /
  `UNDERDOG_LEAGUE_SLUGS` in `mappers/vocab/`
- code-owned alias / id tables: `mappers/vocab/*_aliases.py`,
  `mappers/vocab/crypto_team_ids.py`, `mappers/exchanges/*_names.py`
- code-seeded market rules: `mappers/seed/*_rules.py`

A change is: edit the code, add a test next to it, run
`GCP_PROJECT=rs-marketmaking .venv/bin/pytest -q`, open the MR. The
`regression:mapping-gate` CI job replays recent prod ticks and reports the
row delta; removed rows need a waiver in `regression/waivers.toml`. See
[`regression/README.md`](regression/README.md).

Sides and identity come from typed venue fields, never from parsing a
ticker, slug or symbol.

### Legacy: the BigQuery rule-set tip

The activated tip (`markets_us.mapping_leagues` / `mapping_market_rules` /
`mapping_entities`, `P_*` / `S0_*` rule sets) is retiring. Parts of the
mapper still load it through `mappers/seed/sot.py`: the map run set
(`mappers/seed/tip_leagues.py`), and league exchange settings and aliases
for venues that have no code table yet. That is migration debt. Do not add
leagues, rules or aliases to the tip; move what you touch into code.
Unit tests read a frozen copy, `tests/fixtures/sot/tip.json`. Background:
[`docs/mapping-rules/m1-status.md`](docs/mapping-rules/m1-status.md).

## Mapping console (legacy)

The console SPA (`console/`) and control-plane API
(`mappers/control_plane/`), including Mapper Chat, are still deployed
(`deploy/k8s/mapping-console/`) but are not a way to ship mapping. Do not
stage pins, approve Proposed cards or extend the console or Mapper Chat.
The `gap-propose` CronJob still drafts cards; read them, if at all, as a
list of code changes to make. Details: [`console/README.md`](console/README.md).

## Key directories

| Path | Purpose |
|------|---------|
| `fetch/` | Per-exchange fetchers + `__main__.py` orchestrator |
| `mappers/profiles/` | Parser-profile registry (sport × sportsbook grammars) |
| `mappers/vocab/` | Shared market-type maps and ticker grammars |
| `mappers/exchanges/` | Shared per-exchange parsing/matching machinery |
| `mappers/pipeline.py` | The league-agnostic matching pipeline |
| `mappers/control_plane/` | Legacy console API, Mapper Chat, gap harvest (not a way to ship mapping) |
| `mappers/seed/` | Code-seeded market rules (`*_rules.py`); legacy tip loader (`sot.py`, `tip_*.py`) |
| `console/` | Legacy mapping console SPA |
| `BigQuery/` | Loaders and SQL for `market_mapping` and rule tables |
| `deploy/k8s/mapping-console/` | GKE manifests (console Deployment + `gap-propose` CronJob) |
| `infra/` | Mapper VM bootstrap, crontab, 15-minute pipeline |
| `regression/` | Mapping regression gate (`regression:mapping-gate`) |
| `synthetic/` | Synthetic fixtures for uncovered Kalshi series (ITF) |
| `vendor/` | Runshop World Cup vendor data (archive, not live SoT) |
| `docs/` | Design notes and playbooks |
| `tests/` | pytest unit tests |

## Setup

Install [mise](https://mise.jdx.dev) (recommended) — it manages
Python 3.13, the virtualenv, and loads `.env` automatically:

    mise install
    pip install -e ".[dev]"

Or bring your own Python 3.13:

    python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt

### Required environment

- **`GCP_PROJECT`** — the GCP project used for both Secret Manager
  (API keys) and BigQuery. `marketmaking-test` for test,
  `rs-marketmaking` for prod. Put it in a `.env` file at the repo
  root (`GCP_PROJECT=marketmaking-test`); mise and the cron script
  load it automatically. Without mise, set it in your shell
  (PowerShell: `$env:GCP_PROJECT = 'marketmaking-test'`).
- **gcloud auth** — API keys come from `gcloud secrets`, so the CLI
  must be authenticated: `gcloud auth login`. The Python BigQuery
  client additionally needs `gcloud auth application-default login`.
  Console local use needs ADC as an identity that can run jobs in
  `marketmaking-test` (see `console/README.md`).
- **Runshop (World Cup only)** — besides the usual Kalshi/Optic/PX
  secrets, the pipeline needs `runshop_betbuilder_api_key`,
  `runshop_poly_db_password`, and `runshop_txodds_fusion_db_password`
  in Secret Manager (both `marketmaking-test` and `rs-marketmaking`).
  Deploy verifies them via `infra/verify_runshop_secrets.sh`. Details:
  `docs/adding-runshop.md`.

## Workflow (mise tasks)

    mise run fetch          # fetch events/markets from all exchanges
    mise run map data/...   # run mappers to produce cross-exchange mapping
    mise run write data/... # same, writing mappings.jsonl
    mise run load data/...  # load mappings.jsonl to BigQuery
    mise run smoke          # smoke-test pipeline output in data/
    mise run ai-validate -- --dry-run   # AI-audit the mappings (see docs/ai-validation.md)
    mise run check          # pyright type-check the whole project
    mise run test           # pytest unit tests
    mise run ci             # pytest + pyright (CI test stage)
    mise run quality        # full CI quality gate (size/bandit/interrogate/…)
    mise run hooks-install  # install pre-commit hook (quality + pyright)

Or call Python directly:

    python -m fetch --league nba ncaab --out-dir data
    python -m mappers.run data/<date>/<HH_MM> --write-mappings
    python -m BigQuery.load_mappings data/<date>/<HH_MM>/mappings.jsonl
    python scripts/smoke.py data/
    pyright .
    python -m pytest tests/

### Git pre-commit hook

To run the **quality gate** and **pyright** before every commit (same as the CI
`quality` and `pyright` jobs):

    mise run hooks-install

Or on Windows:

    .\scripts\install-git-hooks.ps1

Requires `pip install -e ".[dev]"` (pytest, pyright, ruff, bandit, pip-audit,
interrogate, pytest-cov). `GCP_PROJECT` defaults to `marketmaking-test` when
unset. Run `mise run quality` manually without committing. Bypass once with
`git commit --no-verify`.

Note `mappers.run` takes the *timestamped* directory the fetch
created (printed as `Output: ...`), not the bare `data/` root.

## Adding a new sport or league

Follow `.cursor/skills/add-new-league/SKILL.md` (venue league tables,
vocab, profiles) and `.cursor/skills/add-team-alias/SKILL.md` (code alias
and id tables). Both end in a test, an MR and the regression gate.

The map run set is the enabled tip leagues plus `CODE_LEAGUES`
(`mappers/seed/tip_leagues.py`, `mappers/seed/code_leagues.py`); a brand-new league on the tip-only
paths (see `CLAUDE.md`) needs that moved to code first. Raise it rather than adding a tip row.

A new sport or venue grammar is a parser profile in `mappers/profiles/`
(registered in `PROFILES`, `mappers/profiles/registry.py`) plus vocab in
`mappers/vocab/`. Worked examples: `docs/adding-soccer.md`,
`docs/adding-crypto.md`, `docs/adding-novig.md`, `docs/adding-dkex.md`,
`docs/adding-sxbet.md`, `docs/adding-underdog.md`. Older docs that describe
console proposals or Kalshi ticker grammar are out of date on those points.

## CI/CD

GitLab CI runs on every merge request and on pushes to `test` / `main`:

| Stage | Jobs |
|-------|------|
| `test` | `pyright`, `quality` (includes the pytest run), `regression:mapping-gate` (with its `:plan`, `:run` ×5 and `:venv` jobs) |
| `build` | `build:mapping-console:test` (auto on `test`), `build:mapping-console:prod` (auto on `main`) |
| `deploy` | `deploy:mapping-pipeline:test` (auto on `test`), `deploy:mapping-pipeline:prod` (manual on `main`); `deploy:mapping-console:test` (auto on `test`), `deploy:mapping-console:prod` (manual on `main`) |

`deploy:mapping-pipeline:prod` and `deploy:mapping-console:prod` both
`needs:` `regression:mapping-gate`, so a red gate cannot ship them.

Mapper deploy checks out the branch on the target VM and refreshes
Python deps via `infra/deploy.sh`. Console deploy applies
`deploy/k8s/mapping-console` overlays (console + `gap-propose`
CronJob). Playing the console jobs does **not** update the live
mapper; playing mapper-prod does **not** roll the console.

One-time GCP/GitLab setup: `docs/gitlab-ci-setup.md`. Console cluster
prereqs: `docs/mapping-rules/console-deploy.md`.

## Further reading

- `docs/lingo.md` — domain vocabulary
- `CLAUDE.md` — mapping rules are code; tip and console are legacy
- `regression/README.md` — the mapping regression gate
- `docs/mapping-rules/m1-status.md` — legacy BQ tip tables
- `docs/mapping-rules/control-plane-api.md`, `docs/mapping-rules/gap-propose.md` —
  legacy console API and harvest
- `mappers/docs/match-logic.md` — how matching works
- `mappers/docs/optic-game-id-clones.md` — two Optic ids, one `game_id`
- `docs/polymarket-bridge.md` — position_id ↔ clob_token_id catalog
- `docs/rfq-mapping-gap-classification.md` — RFQ leftover vs maker-lag
- `docs/adding-world-cup-2026.md`, `docs/adding-soccer.md`,
  `docs/adding-crypto.md`, `docs/adding-runshop.md`,
  `docs/adding-novig.md` — worked examples of extending the system
  (Novig is the one source that returns Optic's own fixture / team /
  player ids, so it joins by id instead of by name).
- `docs/deploy-to-gcp.md` — mapper VM and cron setup
- `docs/gitlab-ci-setup.md` — CI/CD variables and deploy service accounts
