# Deploy to GCP

## Context

This repo is filesystem-based: fetch API responses, store them as
files, map them back to fixtures, compare against gold regression
outputs, and upload to BigQuery.  We want to automate the pipeline to
run hourly.

Key constraint: preserve the filesystem-oriented architecture.  No
rearchitecting to put everything behind API calls or into a database.

## Options considered

### Cloud Run Jobs + GCS FUSE

Mount a GCS bucket as a POSIX filesystem via GCS FUSE.  Cloud
Scheduler triggers the job hourly.  Pay only while the job runs
(seconds to minutes, not 24/7).  Files persist in GCS between runs
and appear as normal paths to the scripts.  Native IAM for BigQuery
access, no key management.

GCS FUSE has higher latency than local disk and some POSIX gaps (no
hard links, `rename` isn't atomic on directories), but for "fetch,
store, compare, upload" workflows this is fine.  See the detailed
assessment below.

### Cloud Run Jobs + Filestore (NFS)

Same as above but with a Filestore-backed persistent volume instead of
GCS FUSE.  Full POSIX compliance and lower latency, but Filestore has
a minimum provisioned cost (~$20+/month basic tier) and requires a VPC
connector.  Overkill for our workload — we don't need file locking,
atomic renames, or heavy random I/O.

### Fly.io Machines + Volumes

Fly Machines can auto-stop when idle and wake on schedule.  Volumes
are real ext4 filesystems.  Very VM-like but lighter weight.  Downside:
not in GCP, so BigQuery access needs a service account key rather than
implicit IAM.

### Spot VM + Cloud Scheduler

Cloud Scheduler calls a Cloud Function that starts a small spot VM,
runs the pipeline, and shuts down.  Real filesystem, real VM, 70-90%
cheaper than on-demand.  More moving parts than Cloud Run Jobs but
zero filesystem compromises.

### Full VM (Compute Engine) (chosen, deployed 2026-03-18)

Always-on VM.  Maximum flexibility and the most familiar model.
Costs ~$19/month for an `e2-small` with 160GB `pd-balanced` in
`us-east4-c`, which is irrelevant at this project's scale.  The
real advantage: a real ext4 filesystem where `find`, `grep`, and
AI coding agents work without friction.  See "Agent-driven
debugging" below.

Provisioning and bootstrap took about an hour.  Scripts are in
`infra/`.  Hourly cron runs fetch→write-mappings→load-to-BQ.
Can revisit Cloud Run Jobs or other options if scaling or cost
becomes a concern, but at current volumes this is fine.

## CI/CD (GitLab)

Code deploys via GitLab CI — no manual `git pull` on the VMs.

| Branch | Environment | GCP project | Deploy |
|--------|-------------|-------------|--------|
| `test` | test VM | `marketmaking-test` | automatic after CI passes |
| `main` | prod VM | `rs-marketmaking` | manual gate in GitLab UI |

Pipeline (`.gitlab-ci.yml`):

1. **test** — `pytest` + `pyright` on merge requests and branch pushes.
2. **deploy** — `gcloud compute ssh` runs `infra/deploy.sh` on the
   target VM (sync code, refresh deps, reconcile the crontab from
   `infra/crontab`), then starts `infra/run_pipeline.sh` in the
   background — the **same** scheduled fetch → map → BQ job — so new
   mapper configuration goes live soon without blocking the CI job.

The scheduled cron (every 15 min, per `infra/crontab`) still runs on
schedule. Set `DEPLOY_SKIP_PIPELINE=1` on the VM to skip the post-deploy
run in an emergency.

One-time setup (service accounts, CI variables, VM deploy token):
`docs/gitlab-ci-setup.md`.

### In-container cron on GKE (how MMOpticOdds does it)

The team's OpticOdds repo solves a similar problem — scheduled Python
jobs that fetch from an API and upsert into BigQuery — but takes a
different approach.  Their price service runs as a long-lived GKE
Deployment (always-on pod serving an API via uvicorn), and the
scheduled work is bolted on by running the Linux `cron` daemon inside
the same container.

How it works:

1. The Dockerfile installs `cron`, copies a crontab file to
   `/etc/cron.d/`, and the `CMD` starts both `service cron start` and
   `uvicorn` in the same process.

2. On each trigger, cron runs a wrapper shell script
   (`run_fixtures_cron.sh`) that executes the Python job
   (`get_fixtures.py`).

3. Cron processes don't inherit container environment variables, so
   the wrapper hacks around this: the `CMD` dumps env vars to
   `/app/.env.runtime` at startup, and the wrapper reads
   `/proc/1/environ` (PID 1's environment) plus that file before
   running Python.

4. Logs are tee'd to `/var/log/cron.log` and stdout so they appear
   in Kubernetes pod logs.

5. Deployments are manual: shell scripts that `docker build`, push to
   Artifact Registry, and `kubectl apply` inline YAML.  No CI/CD
   pipeline.

This works, but has real drawbacks:

- **Paying 24/7** for a pod that runs the cron job once a day (or
  every 8 hours).  The API server needs to be up anyway, but the
  coupling means the cron job can't scale or fail independently.
- **Fragile env var forwarding.**  The `/proc/1/environ` trick breaks
  if PID 1 is a shell wrapper or init process.  The `.env.runtime`
  dump must be kept in sync with any new env vars the job needs.
- **No job-level observability.**  A failed cron run is a log line in
  a long-lived pod, not a discrete job execution with its own status,
  duration, and retry policy.  You have to grep pod logs to find it.
- **No filesystem needed.**  Their pipeline is API-to-BigQuery with no
  intermediate files, so none of the FUSE/filesystem considerations
  apply.  The in-container approach made sense as path of least
  resistance when the pod already existed.

| | MMOpticOdds (in-container cron) | Our plan (Cloud Run Jobs) |
|---|---|---|
| Scheduling | Linux cron inside a 24/7 GKE pod | Cloud Scheduler triggers a job |
| Compute cost | Always-on | Pay per execution |
| Data flow | API to BigQuery, no files | API to files to BigQuery |
| Env vars | Hacked via `/proc/1/environ` | Native Cloud Run injection |
| Job visibility | Grep pod logs | Discrete job executions with status |
| Deployment | Manual shell scripts + `kubectl` | `gcloud run jobs deploy` |
| Failure handling | Exit code in a log line | Built-in retries, alerting, dead-letter |

The comparison reinforces the Cloud Run Jobs choice.  We need a
filesystem (they don't), we don't have a long-running API server to
piggyback on, and we want per-execution observability without parsing
pod logs.  The in-container cron pattern is a pragmatic shortcut when
a pod already exists for other reasons, but it's not a model to
follow for standalone scheduled work.

## Why Full VM over Cloud Run Jobs + GCS FUSE

Cloud Run Jobs + GCS FUSE was the original plan.  The pipeline itself
(fetch, map, upload) would run fine on FUSE — it reads/writes known
paths sequentially, no POSIX edge cases.  But ad-hoc investigation
killed it.

AI coding agents (Claude Code, etc.) are the primary debugging tool
for this project.  Their core strength is grepping and finding across
files to locate anomalies.  Over GCS FUSE, every `stat()` and
`read()` is a network round-trip.  Grepping across months of date
directories — exactly the investigation pattern agents excel at —
would be unusably slow.  The suggested mitigation (use `gsutil`
instead of `grep`) defeats the purpose: you'd have to fight the
agent's natural tools rather than let it work.

A full VM gives:

- Real ext4 filesystem — `find`, `grep`, agents all work natively.
- SSH in and run Claude Code interactively against production data.
- Cron on the box for scheduling.  No Cloud Scheduler, no Docker
  required (though Docker still works for reproducibility).
- Same GCP project as BigQuery; auth via IAM.
- Cost (~$5–15/month for an `e2-small`) is irrelevant.

## Claude Code auth on a headless VM

Claude Code's subscription auth uses an OAuth flow that opens a web
browser.  On a headless VM, there is no browser.  Installing a
desktop browser on a server just to complete the OAuth handshake is
ugly and fragile.

Options to investigate:

- **Copy auth tokens from a local machine.**  Claude Code stores
  session credentials in `~/.claude/`.  Copying the relevant auth
  files to the VM may allow it to use an existing session.  Tokens
  may expire and need periodic refresh.
- **SSH port forwarding.**  Run `claude login` on the VM but tunnel
  the OAuth callback back to a local browser via
  `ssh -R <port>:localhost:<port> <vm>`.  Depends on how the
  redirect URI is structured.
- **API key.**  Buy a small amount of API credit (separate from the
  subscription) and set `ANTHROPIC_API_KEY` on the VM.  Zero auth
  friction, but a separate billing line.

Greg says: I am not sure this is an issue: if all the data is in the VM 
it should trivial to sync locally and debug and develop locally.

## GCS FUSE: detailed assessment (archived)

This assessment was done when Cloud Run Jobs + GCS FUSE was the
leading option.  The pipeline would work fine on FUSE, but the
`find`/`grep` limitation (risk #3) made it unsuitable for
agent-driven debugging.  Kept for reference.

gcsfuse is GA, actively maintained (~monthly releases), and backed by
a dedicated Google team.  It underpins ML workloads on GKE and Vertex
AI, so it gets real investment.  That said, "GA" means Google supports
it — it does not mean "behaves like ext4."

### Why it suits this repo

Our pipeline is the sweet spot: sequential batch job, single writer,
small JSONL files, read-once or write-once.  The file I/O surface is
~40 direct `open()` / `Path` calls across fetch, mappers, BigQuery
loading, and scripts.  Two thin wrappers exist (`shared.lines()` for
JSONL iteration, `shared.load_aliases()` for TOML config) but
everything else is bare stdlib.  gcsfuse means zero code changes.

### POSIX gaps and whether they matter here

| Gap | Impact |
|-----|--------|
| `rename()` is copy+delete, not atomic | We don't use `rename()`.  No impact. |
| No `flock()` / advisory locking | Single writer per job.  No impact. |
| Permissions are fake (all 0644/0755) | IAM controls real access.  No impact. |
| No partial writes / mid-file patching | We write whole files.  No impact. |
| `shutil.copytree/rmtree` edge cases | Only in `verify_date_migration.py`, a one-off script not in the production pipeline. |

### Latency budget (same-region Cloud Run → GCS)

| Operation | Latency |
|-----------|---------|
| Uncached small-file read | 20–100 ms |
| Small-file write + `close()` | 50–200 ms |
| `ls` on a directory with ~100 entries | 100–500 ms |
| Cached stat / metadata hit | sub-ms |

For a typical pipeline run (read ~4 input JSONL + 3–6 TOML configs,
write gold + mappings), the total FUSE overhead is a few seconds.
Negligible for a batch job that already spends most of its time on
HTTP fetches.

### Recommended cache config

Since we're the only writer during a job execution, aggressive
metadata caching is safe:

```
metadata-cache-ttl-secs=-1
stat-cache-max-size-mb=-1
type-cache-max-size-mb=-1
```

File-content caching (`file-cache:max-size-mb`) is less useful
because most files are read once per run.  The caches don't persist
between Cloud Run executions — every run starts cold.

### Risks to watch

1. **`data/` directory growth.**  GCS "directories" are fake (object
   prefix listings).  As months of date directories accumulate,
   `iterdir()` / `glob()` over top-level `data/` will slow down.
   Scripts that scan all dates (`smoke.py`, `check_gold`) will feel
   this first.  Mitigation: scope scanning scripts to recent dates,
   or archive old date dirs to a separate prefix.

2. **Memory budget.**  Streaming writes (gcsfuse v3.0+) reserve
   ~96 MiB per open file handle.  We only open one file at a time so
   this is fine, but size the Cloud Run instance with headroom.
   There was a Cloud Run OOM bug (gcsfuse#2908, fixed May 2025) —
   pin to a recent gcsfuse version.

3. **`find` and `grep` across `data/`.**  Shell-level tools like
   `find` and `grep -r` issue a stat or read for every object they
   touch — each one a network round-trip through FUSE.  On a local
   filesystem this is instant; over GCS FUSE with months of date
   directories it could be unusably slow.  This matters most for
   ad-hoc debugging (grepping for a fixture ID across all dates,
   finding recent files, etc.).  Mitigation: use `gsutil` or
   `gcloud storage` for bulk searches (server-side prefix listing,
   no per-object FUSE overhead), or scope shell tools to a single
   date directory.

4. **Cold-start config reads.**  `tomllib.load()` on 3–6 small TOML
   config files hits GCS on every run (~200–600 ms total).  Not a
   problem at current scale, but consider baking config into the
   Docker image if it grows.

### Why not gcsfs (the Python library) instead

gcsfs would require:

- Replacing ~40+ `open()` / `Path` calls with `GCSFileSystem` API.
- Replacing all pathlib operations (`exists()`, `is_dir()`,
  `iterdir()`, `glob()`, `mkdir()`) with gcsfs equivalents.
- Building a dual-path abstraction so local dev still works without
  GCS credentials — every `mise map <dir>` would need to know
  whether `<dir>` is local or `gs://`.
- Handling `tomllib.load()` and `shutil` compatibility.

The result: more code, a new dependency, and local development
becomes second-class.  gcsfs makes sense for high-throughput parallel
I/O or environments where FUSE isn't available.  Neither applies
here.
