"""mapping_entities_current must be refreshed against the Terraform-managed schema.

WRITE_TRUNCATE with no schema makes the BigQuery client turn autodetect on, which
rewrites the table schema from the JSON rows (every mode NULLABLE, INT64 aliases
inferred as STRING). Terraform then plans a destroy/recreate of the table on the
next unrelated apply.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from google.cloud import bigquery

from mappers.control_plane.bq_tip import materialize_entities_current
from mappers.control_plane.rows import EntityRow

TABLE_SCHEMA = [
    bigquery.SchemaField("rule_set_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("league", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("entity_type", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("canonical_key", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("canonical_name", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("enabled", "BOOL", mode="REQUIRED"),
    bigquery.SchemaField("aliases", "RECORD", mode="REPEATED"),
    bigquery.SchemaField("notes", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("materialized_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("ordinal", "INT64", mode="NULLABLE"),
]


def _store() -> SimpleNamespace:
    job = MagicMock()
    job.errors = None
    client = MagicMock()
    client.get_table.return_value = SimpleNamespace(schema=TABLE_SCHEMA)
    client.load_table_from_json.return_value = job
    return SimpleNamespace(client=client)


def _entities() -> list[EntityRow]:
    return [
        EntityRow(
            league="ucl",
            entity_type="team",
            canonical_key="VIK",
            canonical_name="Viking FK",
            aliases=[{"sportsbook": "optic", "alias_kind": "optic_id", "priority": None}],
        )
    ]


def test_materialize_pins_destination_schema_and_disables_autodetect() -> None:
    store = _store()

    materialize_entities_current(store, "P_abc123", _entities())

    job_config = store.client.load_table_from_json.call_args.kwargs["job_config"]
    assert job_config.autodetect is False
    assert job_config.schema == TABLE_SCHEMA
    assert job_config.write_disposition == "WRITE_TRUNCATE"


def test_materialize_reads_schema_from_the_destination_table() -> None:
    store = _store()

    materialize_entities_current(store, "P_abc123", _entities())

    store.client.get_table.assert_called_once_with("markets_us.mapping_entities_current")


def test_materialize_sheds_columns_the_deployed_table_lacks() -> None:
    """Rolling out ahead of Terraform must degrade, not break activation."""
    store = _store()
    store.client.get_table.return_value = SimpleNamespace(
        schema=[f for f in TABLE_SCHEMA if f.name != "ordinal"]
    )

    materialize_entities_current(store, "P_abc123", _entities())

    rows = store.client.load_table_from_json.call_args[0][0]
    assert all("ordinal" not in row for row in rows)
    assert rows[0]["canonical_key"] == "VIK"


def test_materialize_writes_ordinal_when_the_table_has_it() -> None:
    store = _store()

    materialize_entities_current(store, "P_abc123", _entities())

    rows = store.client.load_table_from_json.call_args[0][0]
    assert [row["ordinal"] for row in rows] == list(range(len(rows)))


def test_materialize_raises_when_the_load_reports_errors() -> None:
    store = _store()
    store.client.load_table_from_json.return_value.errors = [{"reason": "invalid"}]

    try:
        materialize_entities_current(store, "P_abc123", _entities())
    except RuntimeError as exc:
        assert "entities_current materialize failed" in str(exc)
    else:  # pragma: no cover - guard against a silent regression
        raise AssertionError("expected RuntimeError")
