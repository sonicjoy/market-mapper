# Mapping Console (legacy)

The console SPA and its control-plane API (`mappers/control_plane/`,
including Mapper Chat) are legacy. They are **not** a way to ship mapping.
Mapping rules are code: edit the Python under `mappers/`, add a test, open
an MR and let the `regression:mapping-gate` job show the row delta. Policy:
[`CLAUDE.md`](../CLAUDE.md).

Do not stage pins, approve Proposed cards, run Re-seed or activate a rule
set from here, and do not extend the console or Mapper Chat.

## What is still deployed

- Test: https://mapping.mm-test.whiteswandata.com — prod:
  https://mapping.mm.whiteswandata.com (IAP).
- Manifests: `deploy/k8s/mapping-console/` (console Deployment plus the
  `gap-propose` CronJob). CI jobs `build:` / `deploy:mapping-console:*`.
  Cluster notes: [`docs/mapping-rules/console-deploy.md`](../docs/mapping-rules/console-deploy.md).

Read-only pages (Rules, Coverage, Unmapped) can still help look at the
legacy tip and at RFQ leftovers. Treat anything they suggest as a code
change to make.

## Local start

From repo root (API `:8001`, Vite `:5173`):

```powershell
powershell -File scripts/start-console-local.ps1 -OperatorEmail "you@whiteswandata.com"
```

Or by hand:

```powershell
$env:PYTHONPATH = (Get-Location).Path
$env:GCP_PROJECT = "marketmaking-test"
.\.venv\Scripts\python.exe -m uvicorn mappers.control_plane.app:app --host 127.0.0.1 --port 8001 --reload
# second terminal
cd console; npm install; npx vite --host 127.0.0.1 --port 5173
```

The API uses Application Default Credentials. If pages return
`503 bq_forbidden`, run `gcloud auth application-default login` as an
account that can run BigQuery jobs in `marketmaking-test`.
