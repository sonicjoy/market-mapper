# GitLab CI/CD setup

One-time configuration for the pipeline in [`.gitlab-ci.yml`](../.gitlab-ci.yml).
Matches the `mm-infrastructure` convention: `test` branch → test env,
`main` branch → prod (manual deploy gate).

## Pipeline overview

| Trigger | Jobs |
|---------|------|
| Merge request | `pytest`, `pyright` |
| Push to `test` | `pytest`, `pyright`, `deploy:mapping-pipeline:test` (automatic) |
| Push to `main` | `pytest`, `pyright`, `deploy:mapping-pipeline:prod` (manual — click Play in GitLab) |

Deploy runs [infra/deploy.sh](../infra/deploy.sh) on the target VM via
`gcloud compute ssh --tunnel-through-iap`.  After syncing code and
refreshing deps, deploy reconciles the VM crontab from
[infra/crontab](../infra/crontab) and starts
[infra/run_pipeline.sh](../infra/run_pipeline.sh) in the background
(same job as the scheduled cron) so mapper changes take effect soon
without blocking the CI job.  Deploy jobs have a **2h** timeout.  Set
`DEPLOY_SKIP_PIPELINE=1` on the VM to skip the post-deploy run.

## VM instances

| Environment | GCP project | Branch | Instance name | Zone |
|-------------|-------------|--------|---------------|------|
| test | `marketmaking-test` | `test` | `market-mapping-test` | `us-east4-c` |
| prod | `rs-marketmaking` | `main` | `market-mapping` | `us-east4-c` |

## 1. GitLab CI/CD variables

In **Settings → CI/CD → Variables**, add these as **protected** (so they
are only available on protected branches):

| Variable | Type | Value | Used by |
|----------|------|-------|---------|
| `GCP_SA_KEY_TEST` | File | JSON key for the test deploy service account | `deploy:mapping-pipeline:test` |
| `GCP_SA_KEY_PROD` | File | JSON key for the prod deploy service account | `deploy:mapping-pipeline:prod` |
| `GCP_DEPLOY_SSH_KEY_TEST` | File | ed25519 **private** key for CI SSH as `gcloudci` (test VM) | `deploy:mapping-pipeline:test` |
| `GCP_DEPLOY_SSH_KEY_PROD` | File | ed25519 **private** key for CI SSH as `gcloudci` (prod VM) | `deploy:mapping-pipeline:prod` |
| `VM_NAME_TEST` | Variable | `market-mapping-test` | `deploy:mapping-pipeline:test` |
| `VM_ZONE_TEST` | Variable | `us-east4-c` | `deploy:mapping-pipeline:test` |
| `VM_NAME_PROD` | Variable | `market-mapping` | `deploy:mapping-pipeline:prod` |
| `VM_ZONE_PROD` | Variable | `us-east4-c` | `deploy:mapping-pipeline:prod` |

The `GCP_SA_KEY_*` variables **must be of type `File`** (not `Variable`).
Paste the full service-account JSON as the value; GitLab writes it to a
temporary file and the variable expands to that file's *path*, which the
pipeline passes straight to `gcloud auth activate-service-account
--key-file=...`. Do not mask them — masking does not support multiline
JSON, and File variables cannot be masked anyway. Leave **Environment
scope** as `*` (All) so the key reaches the `test`/`production`
environment jobs.

### Persistent deploy SSH key (one-time per VM)

CI connects as Linux user `gcloudci` using a fixed ed25519 keypair so
jobs do not append a new ephemeral key to instance metadata every run.

1. Generate a keypair locally (keep the private key secret):
   ```bash
   ssh-keygen -t ed25519 -f gcloudci_ed25519 -N "" -C "mmmapper-ci-gcloudci"
   ```
2. Add the **public** key to the VM's `ssh-keys` metadata (keep existing
   human keys such as `gtod`):
   ```bash
   # file contains one "username:publickey" line per row, e.g.:
   # gtod:ssh-ed25519 AAAA... gtod@gtod.net
   # gcloudci:ssh-ed25519 AAAA... mmmapper-ci-gcloudci
   gcloud compute instances add-metadata market-mapping-test \
     --zone=us-east4-c --project=marketmaking-test \
     --metadata-from-file ssh-keys=ssh-keys.txt
   ```
3. In GitLab CI/CD variables, add `GCP_DEPLOY_SSH_KEY_TEST` as type
   **File**, paste the **private** key (`gcloudci_ed25519`, not `.pub`).
   Protected, environment scope `*`.

Repeat step 2 on the prod VM when `deploy:mapping-pipeline:prod` is enabled (can reuse the
same keypair or generate a separate one for `GCP_DEPLOY_SSH_KEY_PROD`).

## 2. Deploy service accounts (GCP)

Create one service account per environment, e.g.
`mmmapper-deploy@test` and `mmmapper-deploy@prod`.

Each needs these **project-level** roles:

- **`roles/compute.viewer`** — `compute.instances.get` for `gcloud compute ssh`.
- **`roles/compute.instanceAdmin.v1`** — only needed if CI injects ephemeral
  SSH keys; with a persistent `gcloudci` key pre-installed in metadata,
  jobs reuse it via `--ssh-key-file` and need not update metadata.
- **`roles/iap.tunnelResourceAccessor`** — `--tunnel-through-iap`.

Also grant **`roles/iam.serviceAccountUser`** on the VM's attached
compute service account (e.g. `201519232184-compute@developer.gserviceaccount.com`)
so the deploy SA can update instance metadata.

`gcloud compute ssh` connects as a passwordless-sudo Linux user; deploy
runs as `gtod` at `/home/gtod/mmmapper`.

Generate a JSON key per SA and store in the GitLab variables above.

### Optional hardening (later)

Replace long-lived SA keys with GitLab→GCP workload identity
federation (OIDC). Not required for the initial rollout.

## 3. VM git access

**Not required for CI.** The pipeline tars the GitLab checkout and
`gcloud compute scp`s it to the VM (`deploy.sh --from-archive`), so the
VM never needs a deploy token or deploy key.

Manual `deploy.sh <branch>` on the VM still uses `git fetch` and needs
GitLab SSH or HTTPS credentials configured for `gtod`.

## 4. Protected branches

In **Settings → Repository → Protected branches**:

- Protect `test` and `main`.
- Allow maintainers to push/merge (adjust to your team policy).

Protected status is required so the masked CI variables above are
exposed only on deploy pipelines.

## 5. Verify

1. Open a merge request — confirm `pytest` and `pyright` pass.
2. Merge to `test` — confirm `deploy:mapping-pipeline:test` runs and the VM shows the
   new commit:
   ```bash
   gcloud compute ssh market-mapping-test --zone=us-east4-c \
     --project=marketmaking-test --tunnel-through-iap \
     --command "cd /home/gtod/mmmapper && git log -1 --oneline"
   ```
3. Merge to `main`, manually trigger `deploy:mapping-pipeline:prod`, repeat for prod:
   ```bash
   gcloud compute ssh market-mapping --zone=us-east4-c \
     --project=rs-marketmaking --tunnel-through-iap \
     --command "cd /home/gtod/mmmapper && git log -1 --oneline"
   ```

## Troubleshooting

- **SSH permission denied**: check OS Login binding for the deploy SA
  and that IAP TCP forwarding is enabled on the VM's VPC.
- **git fetch fails on VM**: deploy token/key not configured or expired.
- **pip install fails on VM**: ensure `.venv` exists (`mise install &&
  pip install -r requirements.txt` from initial bootstrap).
