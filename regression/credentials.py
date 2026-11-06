"""Read-only GCP identity for the live gate, by impersonation.

The CI runner's own identity (``gitlab-ci@<project>``, GKE Workload
Identity) has no BigQuery access and must not get any — every job in
every repo shares it.  Like the mapper deploy (``mmmapper-deploy``), the
gate impersonates a dedicated service account that can only READ what
the gate needs (mm-infrastructure ``mmmapper_regression_gate.tf``), and
GCP mints a short-lived token per job.  Nothing downloadable.

``MM_REGRESSION_SA`` names that account.  Unset (a developer's laptop),
the ambient Application Default Credentials are used unchanged.

Python client libraries do not honour gcloud's
``--impersonate-service-account``, and google-auth's impersonated ADC
file cannot take the GKE metadata server as its source, so the
impersonation is built here in code.  Only three gate steps touch GCP
(materialize, the live-SHA read, the rules-tip export); the engine
replay itself is hermetic — verified 2026-09-30 by replaying UFC with
credentials disabled and getting byte-identical output.

``python -m regression.credentials SCRIPT [ARGS...]`` runs a script with
``google.auth.default`` patched to the impersonated identity, for the
one step that is engine code (``scripts/build_sot_fixture.py``).  It is
an explicit wrapper around one subprocess — never a sitecustomize.
"""

from __future__ import annotations

import os
import runpy
import sys

ENV = "MM_REGRESSION_SA"
SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


def credentials():
    """Impersonated credentials when ``MM_REGRESSION_SA`` is set, else None."""
    target = os.environ.get(ENV, "").strip()
    if not target:
        return None
    import google.auth
    from google.auth import impersonated_credentials

    source, _ = google.auth.default(scopes=SCOPES)
    return impersonated_credentials.Credentials(
        source_credentials=source, target_principal=target, target_scopes=list(SCOPES), lifetime=3600
    )


def bq_client(project: str):
    """A BigQuery client under the gate identity."""
    from google.cloud import bigquery

    return bigquery.Client(project=project, credentials=credentials())


def _patch_default() -> None:
    creds = credentials()
    if creds is None:
        return
    import google.auth

    def default(scopes=None, request=None, quota_project_id=None, default_scopes=None):
        return creds, os.environ.get("GCP_PROJECT")

    google.auth.default = default


def main(argv: list[str] | None = None) -> int:
    """Run SCRIPT under the gate identity."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(f"usage: python -m {__spec__.name} SCRIPT [ARGS...]", file=sys.stderr)
        return 2
    _patch_default()
    sys.argv = argv
    runpy.run_path(argv[0], run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
