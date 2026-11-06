"""BigQuery client helpers for interactive exploration.

ro_query:       read-only (SELECT/WITH only), any dataset.
sandbox_query:  DDL/DML permitted, but only against greg_sandbox.
"""

import os
import re

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

SANDBOX_DATASET = "greg_sandbox"
CRYPTO_UNDERLYING_SECURITIES_TABLE = (
    "processed_upstream_us.crypto_underlying_securities"
)
CRYPTO_QUOTE_REQUESTS_TABLE = "processed_upstream_us.crypto_quote_requests"
CRYPTO_SECURITY_DEF_TABLE = "processed_upstream_us.crypto_security_def"
# TxODDS Fusion scores feed (mm-external-feeds TxODDS direct listener, mm-infrastructure modules/tx_scores_us).
TXODDS_REFERENCE_TABLE = "tx_scores_us.txodds_reference_raw"
TXODDS_FIXTURE_MAP_VIEW = "tx_scores_us.txodds_optic_fixture_map"


def is_missing_bq_table(exc: BaseException, table: str) -> bool:
    """Return True when exc is a BigQuery NotFound for the given dataset.table."""
    table_id = table.rsplit(".", 1)[-1]
    return isinstance(exc, NotFound) and table_id in str(exc)


# opticodds_us added for the synthetic-fixture job (synthetic/), which upserts
# synthetic `wsdsyn-*` rows into opticodds_us.opticodds_fixtures. The mapper VM's
# default compute SA already holds roles/editor, so no extra IAM grant is needed.
WRITABLE_DATASETS = frozenset({SANDBOX_DATASET, "markets_us", "opticodds_us"})


def ro_client():
    """Return a BigQuery client bound to GCP_PROJECT."""
    project = os.environ["GCP_PROJECT"]
    return bigquery.Client(project=project)


def ro_query(client, sql, **kwargs):
    """Execute a read-only query. Refuses anything that isn't SELECT/WITH.

    This is a client-side guard for interactive exploration. It does not
    protect against DML hidden inside CTEs — for that, rely on IAM roles.
    """
    stripped = sql.strip()
    first_keyword = stripped.split()[0].upper() if stripped else ""
    if first_keyword not in ("SELECT", "WITH"):
        raise ValueError(
            f"Refusing non-SELECT query (starts with {first_keyword!r}). "
            "Only SELECT and WITH statements are allowed in read-only mode."
        )
    return client.query(sql, **kwargs).result()


def _strip_string_literals(sql: str) -> str:
    """Blank out quoted literals so they can't look like dataset refs.

    `WHERE sportsbook = 'crypto.com'` otherwise parses as dataset
    `crypto`, table `com`, and the writable-dataset check refuses a
    perfectly legal DELETE.
    """
    return re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", "''", sql)


def _referenced_datasets(sql: str) -> set[str]:
    """Dataset ids named as dataset.table or project.dataset.table.

    A 1-2 character qualifier is a SQL alias, not a GCP project, so
    `t.source_ids.market_id` is a struct field. Counting that middle
    token as dataset source_ids refused the USA-ticker DELETE and
    stopped the mapper load before MERGE.
    """
    refs = re.findall(
        r"`?([\w-]+)`?\.`?([\w-]+)`?\.`?[\w-]+`?"
        r"|"
        r"`?([\w-]+)`?\.`?[\w-]+`?",
        _strip_string_literals(sql),
    )
    names: set[str] = set()
    for lead, mid, two in refs:
        if mid:
            if len(lead.strip("`")) <= 2:
                continue
            token = mid
        else:
            token = two
        token = token.strip("`")
        if len(token) > 2:
            names.add(token)
    return names


def sandbox_query(client, sql, **kwargs):
    """Execute DDL/DML against a writable dataset only.

    Allows CREATE, DROP, ALTER, INSERT, UPDATE, DELETE, MERGE, and
    SELECT/WITH. For DDL/DML, validates that every dataset reference
    in the statement is writable. SELECT/WITH pass through unchanged
    (they're read-only regardless of dataset).

    Raises ValueError if the query would touch a non-writable dataset.
    """
    stripped = sql.strip()
    first_keyword = stripped.split()[0].upper() if stripped else ""

    # SELECT/WITH are always safe — delegate to ro_query.
    if first_keyword in ("SELECT", "WITH"):
        return ro_query(client, sql, **kwargs)

    allowed_ddl_dml = {"CREATE", "DROP", "ALTER", "INSERT", "UPDATE", "DELETE", "MERGE"}
    if first_keyword not in allowed_ddl_dml:
        raise ValueError(
            f"Refusing query starting with {first_keyword!r}. "
            f"Allowed: SELECT, WITH, {', '.join(sorted(allowed_ddl_dml))}."
        )

    datasets = _referenced_datasets(stripped)

    non_writable = datasets - WRITABLE_DATASETS
    if non_writable:
        raise ValueError(
            f"Refusing DDL/DML that references non-writable datasets: "
            f"{', '.join(sorted(non_writable))}. "
            f"Writable: {', '.join(sorted(WRITABLE_DATASETS))}."
        )

    if not datasets:
        raise ValueError(
            "No dataset reference found in DDL/DML query. "
            "Use fully qualified names: <dataset>.<table>."
        )

    print(f"[write] {first_keyword} -> {', '.join(sorted(datasets))}")
    return client.query(sql, **kwargs).result()
