# Goalscorer mapper

**Audience:** operators running Kalshi anytime-goalscorer mappings, and whoever
deploys or extends the job.

Kalshi lists a goal ticker per player per match
(`KXEPLGOAL-26AUG25ARSCHE-ARSBSAKA7-1`), and Optic only maps some of them. This
job fills the gap. For each upcoming fixture it rebuilds every player code
(`ARSBSAKA7-1`) a team carried in its last 60 days of mappings onto tonight's
fixture part, and publishes the result as overrides. These are guesses. Kalshi
only lists a match's goal markets about 35 minutes before kick-off, and a
player's code can change between matches (kit number, club, spelling). So a
listing check runs every 10 minutes and moves each guess Kalshi doesn't list
onto the listed market for that player. After each game day the job looks for
goal tickers that traded as RFQ legs but had no mapping, and asks a human in
Slack to name the player. Those answers become the history for the next
pre-game run.

**Ticker parsing debt.** This job reads player codes out of Kalshi tickers
(`goalscorer/codes.py`). `CLAUDE.md` forbids new ticker parsing; do not extend
it. The main mapper already maps these markets from typed fields: market type
from Kalshi's scope ("Goalscorer", "1st Goalscorer" in
`mappers/vocab/kalshi_scopes.py`), line from `strike_type` + `floor_strike`,
both in `mappers/exchanges/kalshi.py`. When you touch the code helpers, move
them to those typed fields.

Code: `goalscorer/` (`python -m goalscorer --help`). Its own image, namespace,
ServiceAccount and CI jobs — nothing is shared with the mapping console or the
mapper VM.

## Workloads

Namespace `goalscorer-mapper`, manifests `deploy/k8s/goalscorer-mapper/`.

| Workload | Kind | Schedule (UTC) | What it does |
|---|---|---|---|
| `goalscorer-pregame` | CronJob | 05:00, 13:00, 21:00 | Map today's and tomorrow's fixtures: anytime, plus 2+ / 3+ onto `player_goals` 1.5 / 2.5 and first goalscorer onto `first_goal_scorer`. Posts a summary when it publishes anything. Idempotent. |
| `goalscorer-listing` | CronJob | every 10 min | For events dated yesterday to tomorrow, read Kalshi's listing and move each pre-game guess Kalshi doesn't list onto the one free listed market with the same player name, or the same code apart from the kit number. Moves go to the job log, not Slack. Each goal line and first goalscorer is checked against its own listed markets. Guesses with no match are left alone, in case Kalshi lists the player later. Events whose markets have all closed are skipped, and the mapping rows that can block a move are read once per run. |
| `goalscorer-reconcile` | CronJob | 06:30 | Yesterday's games: one item per unmapped player whose 1+, 2+, 3+ or first goalscorer market traded. Codes already known from earlier games are recorded straight away (anytime, `player_goals` 1.5 / 2.5 and `first_goal_scorer`); the rest get one review card per player. Traded 2+ / 3+ / first goalscorer markets of players already mapped on 1+ are recorded too. No summary line; counts are in the job log. |
| `goalscorer-pnl` | CronJob | 09:00 UK time (Europe/London; other jobs are UTC) | Yesterday's goalscorer-combo PnL (1d / 7d / 30d) as a PDF in the channel. Anytime and first goalscorer legs both count; first goalscorer series show as e.g. *UCL First Goal*, and their codes as `BARLYAMAL10 FG`. |
| `goalscorer-slack-bot` | Deployment | always on | Socket Mode listener: card buttons and channel commands. |

Leagues: EPL, La Liga and UCL are built in. More can be added from Slack (below).

## Slack (#goalscorer-alerts)

### Review cards

Each unmapped player from `reconcile` is posted as one card, headed by his code
without the line (`MCIEHAALA9`), whichever of his 1+ / 2+ / 3+ / first
goalscorer markets traded. One decision maps them all: the anytime row, then
`player_goals` over 1.5 / 2.5 from the `-2` / `-3` tickers and `first_goal_scorer`
from the first goalscorer ticker, each by the same rules (below). Card options:

- **Accept: _name_** — shown when one candidate clearly matches the code.
- **Pick a player** — the best matches, then every goalscorer selection the
  books list for that game.
- **Other…** — type the name. It is snapped to the books' spelling
  (case/accent-insensitive); tick *Use exactly as typed* only when no book lists
  the player yet.
- **Dismiss** — close the card without recording anything.

The card is rewritten with the outcome and who chose it, so it can't be
resolved twice. If this job had already mapped the chosen player to a different
ticker for that game (a stale guess), the decision replaces it with an override,
which takes effect within 15 minutes. A player mapped by Optic or anyone else is
never replaced: the card says so, and the fix is a code change in the mapper
(`mappers/exchanges/kalshi.py`, with a test and the `regression:mapping-gate`
delta), not a console pin.
If the ticker is already mapped to another player, nothing changes. If it is
already mapped to the chosen player, his 2+ / 3+ and first goalscorer markets
are still filled in. The
name must be the Optic selection string: that is what the
RFQ pricer joins on, so a misspelt name maps a ticker that never prices.

### Channel commands

Post one of these as a top-level message; the bot replies in the thread.
Anything else is ignored.

| Message | Effect |
|---|---|
| `international_-_friendlies` | Add an Optic league. The Kalshi series is derived from the league's moneyline mappings (`KX…GAME` → `KX…GOAL`) and checked against Kalshi. Its upcoming fixtures are mapped straight away. |
| `international_-_friendlies KXFRIENDLYGOAL` | Add a league with an explicit series (when it can't be derived). |
| `202608110FBC008C` or `19089-22537-2026-08` | Map one Optic fixture (fixture id or game_id), even outside the registered leagues. |
| `KXEPLGAME-26AUG25ARSCHE` (any ticker on the match, or its kalshi.com link) | Map the match that ticker belongs to. |

Single-match mapping skips every player already covered, so re-posting is safe.

`GOALSCORER_SLACK_APPROVER_IDS` (prod overlay) restricts buttons and commands to
listed Slack user ids; empty means anyone in the channel.

## How mappings are written

| Path | Used by | Where it lands |
|---|---|---|
| Pub/Sub `mapping-override-us`, `mapping_source=HENRY`, attribute `source=goalscorer-mapper` | pregame, map-one-match | `opticodds_us.mapping_override` → `prices_state_merge_us` (every 15 min) creates/updates the `opticodds_mapping` and `prices_dedup_state` rows |
| Same topic, attribute `source=goalscorer-listing` | listing check | as above; re-points the selection's row at the listed ticker |
| Same topic, attribute `source=goalscorer-review` | review cards that replace a stale ticker | as above, for a game of any age (the merge updates existing rows regardless of date) |
| Direct INSERT, `mapping_source=HENRY` | reconcile, review cards | `opticodds_us.opticodds_mapping` rows for **played** games — the history pre-game reads back |
| Append-only INSERT | add league | `markets_us.goalscorer_leagues` (latest row per `league_id` wins; `active=false` removes one, built-ins included) |

Pre-game never overrides a selection Optic already maps (`ORIGINAL`) or that
anyone else has an override on. It republishes only when its own ticker for a
selection changed (e.g. a new kit number). Listing-check moves and review
decisions carry their own `source`, so pre-game counts them as someone else's
and never reverts them. A player in both teams' histories takes the code from
his most recent game.

### 2+ / 3+ goal lines

Kalshi lists up to three markets per player: `-1` 1+ (anytime), `-2` 2+ and
`-3` 3+. From the same player code, pre-game also publishes the player's 2+ and
3+ tickers onto Optic `player_goals` over 1.5 and over 2.5 (selection = the same
Optic name as his anytime row). The override has the same shape as Optic's own
`player_goals` rows (its Kalshi NHL rows included): `selection_line` `over`,
`points` and `selection_points` both the line (1.5 / 2.5), and Optic's per-player
`grouping_key` (`bukayo_saka:1.5`). The Kalshi mapper (`GREG`) currently writes
`selection_points` 0 on these rows, which Optic doesn't.

The rules mirror anytime, per line: any `player_goals` row another mapper wrote
(the Kalshi mapper's `GREG` rows, Optic's `ORIGINAL`) and any other source's
override is left alone, and our own override is only republished when its ticker
changed. A line is mapped even when the player's anytime row belongs to Optic.
Kalshi doesn't list 2+ / 3+ for every player; a guess on a market that never
lists simply never prices. The listing check corrects line guesses too, each line
against its own listed markets (a 2+ guess only moves onto a listed 2+ ticker),
by the same name / code-apart-from-kit rule. That matters: a pre-game line row
holds the key the Kalshi mapper would write its own row under, so a stale guess
would otherwise block the correct mapping.

### First goalscorer

Kalshi's first goalscorer series is the anytime one with `FIRSTGOAL` for `GOAL`,
and its tickers carry the player's code without a line:
`KXUCLFIRSTGOAL-26OCT13GALBAR-BARLYAMAL10` is the same player as
`KXUCLGOAL-26OCT13GALBAR-BARLYAMAL10-1`. Pre-game maps it onto Optic
`first_goal_scorer` in Optic's own shape (as anytime: `selection_line` empty,
points 0, `grouping_key` `default`, yes side only), under exactly the anytime
rules. Optic's feed already maps most Kalshi first goalscorer markets itself
(`ORIGINAL`), so pre-game mostly fills gaps. The listing check corrects first
goalscorer guesses against their own Kalshi event. Player history reads
first goalscorer rows as well as anytime rows, which teaches pre-game codes for
players Optic only maps on first goalscorer.

## Configuration

Set through the `goalscorer-mapper-config` ConfigMap (overlays) and the
`goalscorer-slack` Secret.

| Variable | Default | Meaning |
|---|---|---|
| `GCP_PROJECT` | — | BQ + Pub/Sub project |
| `GOALSCORER_SLACK_CHANNEL_ID` | — | Channel for cards, summaries, reports. Unset = Slack off (log only). |
| `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` | — | From the ExternalSecret (prod only) |
| `GOALSCORER_SLACK_APPROVER_IDS` | empty | Allowed Slack user ids |
| `GOALSCORER_LOOKBACK_DAYS` | 60 | How far back team history reaches |
| `GOALSCORER_PREGAME_DAYS_AHEAD` | 1 | Pre-game covers today plus this many days |
| `GOALSCORER_MAPPER_ENABLED` | 1 | `0` makes the CronJobs exit without doing anything |
| `GOALSCORER_DRY_RUN` | 0 | Log overrides/inserts/Slack posts instead of doing them |

## Operations

Run locally against test (ADC credentials):

    GCP_PROJECT=marketmaking-test GOALSCORER_DRY_RUN=1 python -m goalscorer pregame
    GCP_PROJECT=rs-marketmaking GOALSCORER_DRY_RUN=1 python -m goalscorer listing   # logs the moves it would publish
    GCP_PROJECT=marketmaking-test python -m goalscorer map KXEPLGAME-26AUG25ARSCHE

Run a CronJob now:

    kubectl -n goalscorer-mapper create job --from=cronjob/goalscorer-reconcile gs-reconcile-$(date +%s)

`reconcile` and `pnl` have `backoffLimit: 0`, because a retry would post every
card, or the report, twice. A failed run posts `:x: goalscorer <cmd> failed` to
the channel.

Test (`marketmaking-test`) has no Slack app. The bot is scaled to 0 and
`reconcile`/`pnl` are suspended, while `pregame` runs for real against test
data. Smoke the others by hand as above.

## Deploy

Everything is declarative; bring-up is one Play per repo, plus the one-time
Slack app below.

| Order | Repo | Play | Creates |
|---|---|---|---|
| 1 | mm-infrastructure | `terraform_apply` (main) | GSA `goalscorer-mapper` + Workload Identity, BigQuery / Pub/Sub grants, `markets_us.goalscorer_leagues`, Slack token secret containers, ESO grant |
| 2 | — | one-time Slack app ([below](#slack-app-one-time)) | the two tokens in GSM |
| 3 | mmmapper | `deploy:goalscorer-mapper:prod` (main) | Namespace, ServiceAccounts, SecretStore, ExternalSecret, bot, CronJobs |

Terraform lives in mm-infrastructure: `goalscorer_mapper.tf`, the
`eso_goalscorer_mapper` block in `eso.tf`, `goalscorer_leagues` in
`modules/general_us`, and the token containers in `modules/secrets`. The ESO
SecretStore and `eso-sync` KSA ship in this repo's prod overlay, so there is no
`apply-stores.sh` step. Played out of order, the deploy fails at the
ExternalSecret wait without leaving anything behind that blocks the apply;
Play it again once steps 1–2 are done.

CI jobs run only when `goalscorer/`, `BigQuery/client.py`, the Dockerfile or the
manifests change:

- `test`: `build:goalscorer-mapper:test` → `deploy:goalscorer-mapper:test` (auto)
- `main`: `build:goalscorer-mapper:prod` (auto) → `deploy:goalscorer-mapper:prod` (manual Play)

The image (`deploy/goalscorer-mapper.Dockerfile`) goes to the existing
`mapping-console` Artifact Registry repo as `goalscorer-mapper`, so the runners'
writer grants already cover it.

Check: post `england_-_premier_league` in the channel. The bot should reply
that it's already mapped.

### Slack app (one-time)

This step can't be automated. Slack has no API to switch on Socket Mode or
mint an app-level token, and installing an app needs a person to approve it:

1. api.slack.com/apps → **Create New App → From an app manifest** → paste
   `deploy/goalscorer-mapper.slack-manifest.yaml` → **Install to Workspace**.
2. **Basic Information → App-Level Tokens** → generate one with
   `connections:write`.
3. Store both (after step 1 of the table, which creates the containers):

       printf %s 'xoxb-…' | gcloud secrets versions add goalscorer_slack_bot_token --data-file=- --project=rs-marketmaking
       printf %s 'xapp-…' | gcloud secrets versions add goalscorer_slack_app_token --data-file=- --project=rs-marketmaking

The bot joins #goalscorer-alerts on startup (a private channel still needs
`/invite @goalscorer-mapper`). Revoke the bot token that was hard-coded in the
original script.

## Changes from the original script

- Pre-game publishes through `mapping-override-us` with `mapping_source`. That
  replaces the direct INSERTs into `opticodds_mapping` and `mapping_override`,
  and the `--update-source` fix-up afterwards.
- Every query takes parameters (no SQL built from team or player names), and
  every query bounds partitions. Dry-run total is about 20 GB/day, mostly the
  30-day PnL.
- Slack buttons replace thread replies and the local `goalscorer_threads_*.json`.
  Decisions apply as soon as someone clicks, not at the next day's run.
- No local files. SQL, review JSON and thread files are gone, and so is the
  squad-file fallback, which had no input in a scheduled job.
- The reconcile ticker window follows the reconciled date (it previously used
  `CURRENT_TIMESTAMP - 1 day`). Auto-resolved codes are now actually recorded
  (the script only wrote them to a SQL file).
- Fixtures are deduplicated per game_id (latest publish).
- Player history takes the newest game first, instead of whichever game an
  unordered loop visited last.
- Name matching also transliterates ø/æ/ß/ł, and a tie at the top produces no
  suggestion.
- The PnL report counts only the registered leagues' `KX…GOAL-` and
  `KX…FIRSTGOAL-` legs (the script's `KX%GOAL%` also matched other series). Resolutions are aggregated per combo, so stakes no
  longer double-count.
