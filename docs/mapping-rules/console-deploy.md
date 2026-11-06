> Retired: the mapping console / tip is not a way to ship mapping. Rules are code — see CLAUDE.md.

# Mapping console — local vs GKE

**Audience:** operators who need to find, run down or switch off the
mapping console and the CronJobs that ride its deploy.

## Local (API + Vite)

Two processes, same as [`console/README.md`](../../console/README.md):

1. **API** — `uvicorn mappers.control_plane.app:app` on `:8001` (or `:8000`).
2. **SPA** — `npx vite` in `console/` on `:5173`. Vite proxies `/api/*` → the API (strips the `/api` prefix) and injects a local IAP email header.

## Cluster (GKE)

One image, one process — patterned on mm-trading-dash:

| Piece | Location |
|-------|----------|
| Dockerfile | `deploy/Dockerfile` (node builds SPA → python + uvicorn) |
| Manifests | `deploy/k8s/mapping-console/` (`base` + `overlays/test-us`, `overlays/prod-us`) |
| Namespace | `mapping-console` |
| Workload Identity KSA | `mapping-control-plane` → `mapping-control-plane@<project>.iam.gserviceaccount.com` |
| Listen | `:8000` — probes hit `GET /healthz` → `{"ok": true}` |
| Hosts (IAP) | test `https://mapping.mm-test.whiteswandata.com`, prod `https://mapping.mm.whiteswandata.com` |

The same overlay (`base/kustomization.yaml`) also deploys three CronJobs on
the mapping-console image and `mapping-control-plane` SA:

| CronJob | Schedule | Off switch |
|---|---|---|
| `gap-propose` | `*/30 * * * *` | `MAPPING_PIPELINE_GAP_PROPOSE=0` (`overlays/*/gap-propose-env.yaml`); AI suggestions `MAPPING_PIPELINE_GAP_SUGGEST=0`. See [`gap-propose.md`](gap-propose.md) |
| `oom-fold-rank` | `2,17,32,47 * * * *` | `spec.suspend: true` + `MAPPING_PIPELINE_OOM_FOLD_RANK=0` (`overlays/*/oom-fold-rank-env.yaml`) |
| `mismap-alert` | `7 * * * *` | `MAPPING_MISMAP_ALERT=0` (`overlays/*/mismap-alert-env.yaml`) |

Deleting or suspending the console Deployment without these CronJobs leaves
them running; check all three.

Console env that matters when switching off (`overlays/*/env.yaml`):

- `MAPPING_CP_ALLOW_ACTIVATE` — prod is `1` (Approve activates a tip
  candidate). Set `0` to stop the console changing what the mapper loads.
- `MAPPING_CP_CHAT` — Mapper Chat; `0` to disable. See [`mapper-chat.md`](mapper-chat.md).
- `MAPPING_CP_CATALOG` — Catalog page + override API.

### CI

- Branch `test`: `build:mapping-console:test` (Kaniko → Artifact Registry
  `mapping-console/app`), then `deploy:mapping-console:test` (auto).
- Branch `main`: `build:mapping-console:prod` (auto),
  `deploy:mapping-console:prod` (manual Play; `needs:` `regression:mapping-gate`).

The mapper VM is a separate deploy (`deploy:mapping-pipeline:test` /
`deploy:mapping-pipeline:prod`). Playing the console jobs does **not** update
the mapper. New venue jobs get their own app dir, image and CI jobs; do not
add them to this overlay.

A redeploy re-applies the overlay, so any off switch must be committed to the
overlay, not only patched on the live cluster.

## R_068 prod hold

Lifted 2026-09-21; history and the switch-off procedure for `oom-fold-rank`
and Catalog: [`r068-prod-hold.md`](r068-prod-hold.md).
