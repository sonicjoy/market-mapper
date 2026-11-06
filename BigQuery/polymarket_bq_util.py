"""Shared BigQuery stage→MERGE upsert helpers for the Polymarket loaders.

Both ``load_polymarket_position_bridge`` and ``load_polymarket_leg_resolutions``
upsert into tables in ``raw_ingestion_us``. That dataset is intentionally NOT in
``BigQuery.client.WRITABLE_DATASETS`` (the sandbox guard is scoped to
``greg_sandbox``/``markets_us``), so these dedicated loaders own their tables and
run the MERGE via a direct ``bigquery.Client.query`` — the same "bypass the
interactive guard for a purpose-built raw-dataset loader" pattern as
``load_kalshi_raw.py``.

The BQ tables are declared authoritatively in Terraform
(mm-infrastructure/modules/exchanges/polymarket/). ``ensure_table`` is an
idempotent create-if-absent so a loader is runnable standalone (dry-runs,
pre-apply); once Terraform owns the table it is a no-op.
"""

import io
import json
import os

from google.cloud import bigquery


def bq_client() -> bigquery.Client:
    """Return a BigQuery client bound to ``GCP_PROJECT`` (no explicit location)."""
    return bigquery.Client(project=os.environ["GCP_PROJECT"])


def qualify(client: bigquery.Client, dataset_table: str) -> str:
    """Expand ``dataset.table`` to ``project.dataset.table`` using the client project."""
    return f"{client.project}.{dataset_table}"


def ensure_table(
    client: bigquery.Client,
    table_ref: str,
    schema: list[bigquery.SchemaField],
    partition_field: str,
    clustering: list[str],
) -> None:
    """Create ``table_ref`` if it does not already exist (DAY-partitioned + clustered).

    Idempotent: a no-op when the table exists, so it never fights the Terraform
    definition. ``table_ref`` is a fully-qualified ``project.dataset.table``.
    """
    table = bigquery.Table(table_ref, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field=partition_field)
    table.clustering_fields = clustering
    client.create_table(table, exists_ok=True)


def stage_and_merge(
    client: bigquery.Client,
    target_ref: str,
    stage_ref: str,
    schema: list[bigquery.SchemaField],
    rows: list[dict],
    key_col: str,
) -> int:
    """Bulk-load ``rows`` into ``stage_ref`` (WRITE_TRUNCATE) then MERGE into ``target_ref``.

    Upsert is keyed on ``key_col``: matched rows update every non-key column,
    unmatched rows insert. Returns the number of rows staged. Stage/target refs are
    fully-qualified ``project.dataset.table``.
    """
    buf = io.BytesIO()
    for row in rows:
        buf.write(json.dumps(row).encode("utf-8"))
        buf.write(b"\n")
    buf.seek(0)

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_file(buf, stage_ref, job_config=job_config)
    job.result()
    if job.errors:
        raise RuntimeError(f"stage load into {stage_ref} failed: {job.errors}")

    all_cols = [f.name for f in schema]
    value_cols = [c for c in all_cols if c != key_col]
    update_set = ", ".join(f"{c} = S.{c}" for c in value_cols)
    insert_cols = ", ".join(all_cols)
    insert_vals = ", ".join(f"S.{c}" for c in all_cols)
    merge_sql = f"""
        MERGE `{target_ref}` AS T
        USING `{stage_ref}` AS S
        ON T.{key_col} = S.{key_col}
        WHEN MATCHED THEN UPDATE SET {update_set}
        WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
    """  # nosec B608 — all identifiers are code-derived (caller-provided refs + schema field names), no user input
    client.query(merge_sql).result()
    return int(job.output_rows or 0)
