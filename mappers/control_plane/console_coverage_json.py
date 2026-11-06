"""JSON-safe coercion for Coverage BigQuery rows."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any


def json_safe(value: Any) -> Any:
    """Coerce BigQuery row values into JSON-serializable forms."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def json_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): json_safe(value) for key, value in row.items()}
