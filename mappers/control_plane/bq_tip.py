"""Activate tip change: materialize current + validity opens."""

from __future__ import annotations

from typing import Any

from google.cloud import bigquery

from BigQuery.mapping_rule_rows import ENTITIES_CURRENT_TABLE, VALIDITY_TABLE
from mappers.control_plane.bq_cow import entity_current_rows, validity_json_rows
from mappers.control_plane.cow_validity import opens_for_activation
from mappers.control_plane.rows import EntityRow


def apply_tip_change(store: Any, rule_set_id: str) -> None:
    """Refresh entities_current and append validity opens for tip change."""
    previous = store.current_rule_set_id
    prev_ent = store.entities_for(previous) if previous else []
    prev_lg = store.leagues_for(previous) if previous else []
    prev_mr = store.market_rules_for(previous) if previous else []
    next_ent = store.entities_for(rule_set_id)
    next_lg = store.leagues_for(rule_set_id)
    next_mr = store.market_rules_for(rule_set_id)
    materialize_entities_current(store, rule_set_id, next_ent)
    store.note_entity_base(rule_set_id, next_ent)
    opens = opens_for_activation(
        environment=store.environment,
        introduced_in_rule_set_id=rule_set_id,
        previous_entities=prev_ent,
        next_entities=next_ent,
        previous_leagues=prev_lg,
        next_leagues=next_lg,
        previous_market_rules=prev_mr,
        next_market_rules=next_mr,
    )
    append_validity(store, opens)


def materialize_entities_current(
    store: Any,
    rule_set_id: str,
    entities: list[EntityRow],
) -> None:
    """WRITE_TRUNCATE mapping_entities_current from coalesced tip."""
    # Load the destination schema explicitly. WRITE_TRUNCATE with no schema makes
    # the client enable autodetect, which rewrites the table schema from the rows
    # and leaves Terraform planning a destroy/recreate of this table.
    destination = store.client.get_table(ENTITIES_CURRENT_TABLE)
    fields = {field.name for field in destination.schema}
    # Drop columns the deployed table does not have yet. A load naming an unknown
    # field fails outright, which would take activation down for as long as this
    # image ran ahead of the Terraform apply. Readers already treat anything
    # missing here as a reason to fall back, so shedding it degrades instead.
    rows = [
        {key: value for key, value in row.items() if key in fields}
        for row in entity_current_rows(rule_set_id, entities)
    ]
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
        schema=destination.schema,
        autodetect=False,
    )
    job = store.client.load_table_from_json(
        rows,
        destination,
        job_config=job_config,
    )
    job.result()
    if job.errors:
        raise RuntimeError(f"entities_current materialize failed: {job.errors}")


def append_validity(store: Any, opens: list[Any]) -> None:
    """Append validity-open events."""
    rows = validity_json_rows(opens)
    if not rows:
        return
    errors = store.client.insert_rows_json(VALIDITY_TABLE, rows)
    if errors:
        raise RuntimeError(f"mapping_rule_validity insert failed: {errors}")
