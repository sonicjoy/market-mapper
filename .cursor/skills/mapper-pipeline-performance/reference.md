# Collect commands

## Mapper VMs

```text
prod: gcloud compute ssh market-mapping --zone=us-east4-c --project=rs-marketmaking --tunnel-through-iap
test: gcloud compute ssh market-mapping-test --zone=us-east4-c --project=marketmaking-test --tunnel-through-iap
repo: /home/gtod/mmmapper
log:  /home/gtod/mmmapper/logs/pipeline.log
```

Remote one-shot (quote for PowerShell; remote script is bash):

```bash
date -u '+%F %T UTC'
sudo -u gtod git -C /home/gtod/mmmapper log -1 --format='%h %ci %s'
sudo grep -E 'Pipeline start|Pipeline complete|skip: previous' /home/gtod/mmmapper/logs/pipeline.log | tail -n 36
sudo grep -E '^STEP name=map ' /home/gtod/mmmapper/logs/pipeline.log | tail -n 16
sudo grep -E '^STEP name=(fetch_total|load_fetch|map |load |post_load|total) ' /home/gtod/mmmapper/logs/pipeline.log | tail -n 40
sudo grep 'snapshot indexed' /home/gtod/mmmapper/logs/pipeline.log | tail -n 3
ps -ef | grep run_pipeline | grep -v grep
sudo grep -E 'Polymarket bridge start|Polymarket bridge complete|skip: previous polymarket bridge' /home/gtod/mmmapper/logs/polymarket_bridge.log | tail -n 12
```

`STEP name=map ` needs the trailing space so it does not match `map_league`.

## GKE gap-propose

```text
prod context: gke_rs-marketmaking_us-east4-b_primary-cluster-us
test context: gke_marketmaking-test_us-east4-b_primary-cluster-us
namespace:    mapping-console
```

```powershell
$ctx = 'gke_rs-marketmaking_us-east4-b_primary-cluster-us'  # or test context
kubectl --context $ctx -n mapping-console get cronjob gap-propose -o wide
kubectl --context $ctx -n mapping-console get jobs -l app=gap-propose --sort-by=.metadata.creationTimestamp
kubectl --context $ctx -n mapping-console get pods -l app=gap-propose -o wide
kubectl --context $ctx -n mapping-console logs -l app=gap-propose --tail=50
# last completed job:
kubectl --context $ctx -n mapping-console logs job/<job-name> --tail=50
```

Manifest: `deploy/k8s/mapping-console/base/gap-propose-cronjob.yaml` (`*/30`, Forbid, 1 CPU / 2Gi). SuccessfulJobsHistoryLimit is 2 — only the last couple of Jobs remain.

## Pairing interleaved mapper STEPs

Overlapping ticks write one `pipeline.log`. Prefer a window that starts at `Pipeline start` and ends at that tick's `Pipeline complete: data/…`. A `total` of ~900s with `post_load` ~40–50s is the post-split mapper. `post_load` of 1500s+ is a tick that still ran harvest on the VM (old code or mixed log).
