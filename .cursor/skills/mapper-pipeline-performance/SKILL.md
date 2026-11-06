---
name: mapper-pipeline-performance
description: >-
  Reports mapper-cron and gap-propose CronJob performance on test and prod:
  map/fetch/post_load timings, 15-min skip rate, in-memory snapshot
  index, and GKE harvest duration/actions. Use for "performance report",
  mapper cron, post_load, pipeline_gap_propose, gap-propose, or "how's
  test/prod mapping performance".
---

# Mapper + gap-propose performance report

Three **independent** pipelines. Never treat VM `post_load` as harvest. The Polymarket bridge is **not** a mapper STEP.

| Pipeline | Where | Cadence | Lock |
|----------|--------|---------|------|
| **Mapper** | GCE `market-mapping` / `market-mapping-test` via `infra/cron_pipeline.sh` | `*/15` | `logs/pipeline.lock`; `flock -u 200` before `post_load` |
| **Poly bridge** | same VMs via `infra/cron_polymarket_bridge.sh` | `8,23,38,53` | `logs/polymarket_bridge.lock` — **not** `pipeline.lock`. Catalog page ~6 min. Log: `logs/polymarket_bridge.log` |
| **gap-propose** | GKE CronJob `gap-propose` in `mapping-console` | `*/30`, `concurrencyPolicy: Forbid` | own Job; does **not** hold the mapper lock |

Mapper `post_load` is runshop prices + `crypto_id_name_check` (swapped crypto_id pins). Coverage gap alerts no longer run on the VM. Harvest is `python -m mappers.control_plane.pipeline_gap_propose` on the mapping-console image. This skill only reports its runtime; its cards are not a way to ship mapping (`CLAUDE.md`).

## When to run

User asks for a performance report, mapper cron health, post_load time, or gap-propose duration. Default **both** envs unless they name one.

## Workflow

```
- [ ] 1. gcloud auth (SSH + kubectl). If "Reauthentication failed": gcloud auth login --update-adc (joe.luo@whiteswandata.com)
- [ ] 2. SSH both mapper VMs — HEAD, start/skip, STEP lines, snapshot indexed
- [ ] 3. kubectl both GKE contexts — CronJob, Jobs, logs for gap-propose
- [ ] 4. Pair mapper STEPs carefully (overlapping ticks interleave the same log)
- [ ] 5. Render a canvas (do not dump the report as a markdown table)
- [ ] 6. Chat: headline + link the canvas
```

SSH and kubectl recipes: [reference.md](reference.md).

## Mapper signals

| Signal | How to read |
|--------|-------------|
| `STEP name=map sec=N` | Index working if ~100–150s (pre-index was 750–980s) |
| `snapshot indexed: …` | JSONL KV on; empty-Optic leagues log `skip: … no optic fixtures` |
| `STEP name=post_load` | runshop + `crypto_id_name_check`. The old ~30–50s included coverage gap checks, which no longer run. Multi-thousand-sec values are leftover VM harvest ticks — call them out, do not average them in as "current" |
| `skip: previous pipeline run still active` | Next `:15` lost the lock (fetch+map still running) |
| `Pipeline start` during another tick's `post_load` | Lock-before-post_load working |

Prod fetch is ~270–300s; test fetch is ~510–530s. That is why test still skips every other slot.

## gap-propose signals

| Signal | How to read |
|--------|-------------|
| Job `DURATION` | Wall time. Healthy complete ~20 min prod / ~40 min test. Cap is **60 min** (`activeDeadlineSeconds`); flag **DeadlineExceeded** or the timeout Slack alert |
| `pipeline gap-fix done action=proposed\|skip\|blocked` | Outcome |
| `skip: no new pins (harvested=N already_in_review=M)` | Harvest ran; no new Review card |
| `blocked:` | Live-name collisions; same set repeating is a known waste |
| `optic_cache` / `crypto_catalogue` | BQ warm; HTTP only on misses |
| polymarket pin slots | Same **100** pin-producing events per book as Kalshi/crypto (`MAX_EVENTS`); stamp gateway names only for inners harvest walks; TTL unions prefixes so RFQ churn does not restamp |
| `poly_usa_close` phases | `phase=start` (before BQ), `phase=loaded` (after tickers + Optic rows), `phase=done` — each line may include `mem_pct` from cgroup |
| CronJob retry | `backoffLimit: 0` — OOM must not replay the same harvest and block `Forbid` |
| Timeout Slack | `killed by CronJob timeout` on `#marketmaking-mapping-alerts` when the 60m cap fires before propose |

Kill switch: `MAPPING_PIPELINE_GAP_PROPOSE=0` on the CronJob env. AI suggestions are on by default (`MAPPING_PIPELINE_GAP_SUGGEST=0` to disable). Do not skip pre-harvest sibling combine.

## Canvas

Write `C:/Users/Joe Luo/.cursor/projects/c-repos-mmmapper/canvases/mapper-cron-performance-report.canvas.tsx`.

Must include:

1. As-of UTC + HEADs + GKE image tags if collected
2. **Mapper** section: map series, typical steps, start vs skip
3. **gap-propose** section: last Job durations, last `action`, running-over-schedule
4. Source caption (VM `pipeline.log` + `kubectl` Jobs/logs)

Import only `cursor/canvas`. No empty-state placeholders. Read the canvas skill before editing the `.canvas.tsx`.

## Chat summary

Lead with whether map is still ~2 min and whether gap-propose is finishing inside 30 min. Link the canvas. Do not paste oauth URLs.
