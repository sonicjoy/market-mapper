> Retired: the mapping console / tip is not a way to ship mapping. Rules are code — see CLAUDE.md.

# R_068 prod hold (2026-09-18, lifted 2026-09-21)

G2 fold+rank and G5 Catalog reached prod before G1 schema (`fixture_id`,
`is_rfq_winner`, `rank_class`) existed on `rs-marketmaking.opticodds_us.opticodds_mapping`.
Hold lifted 2026-09-21 after G1 schema verified on prod and test G2 soak passed.
Both are **on** in prod today. The mapping pipeline VM is unrelated.

## Switching them off

| Surface | Off | File |
|---|---|---|
| CronJob `oom-fold-rank` | `spec.suspend: true` and `MAPPING_PIPELINE_OOM_FOLD_RANK=0` | `deploy/k8s/mapping-console/overlays/prod-us/oom-fold-rank-env.yaml` |
| Catalog page + override API | `MAPPING_CP_CATALOG=0` | `deploy/k8s/mapping-console/overlays/prod-us/env.yaml` |

Commit the change, then on `main` wait for `build:mapping-console:prod` and
Play `deploy:mapping-console:prod`. For an immediate stop, the live CronJob
was patched like this on 2026-09-18:

```powershell
kubectl --context gke_rs-marketmaking_us-east4-b_primary-cluster-us -n mapping-console `
  patch cronjob oom-fold-rank --type merge --patch-file <suspend.json>
```

A live patch alone does not stick: the next `deploy:mapping-console:prod`
re-applies the overlay, so the overlay must carry the same setting.

Confirm with `kubectl ... get cronjob oom-fold-rank` (`SUSPEND=True`).
