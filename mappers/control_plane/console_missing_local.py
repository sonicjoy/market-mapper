"""Local JSONL snapshot for Missing catalogue dev (MAPPING_MISSING_BQ_PROJECT=local)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOCAL_MISSING_PROJECT = "local"
_DEFAULT_REL = Path("scratch") / "missing_catalogue_dev.jsonl"


def repo_root() -> Path:
    """Repository root (parent of ``mappers/``)."""
    return Path(__file__).resolve().parents[2]


def missing_local_path() -> Path:
    """Path to the gitignored Missing catalogue JSONL snapshot."""
    raw = (os.environ.get("MAPPING_MISSING_LOCAL_PATH") or "").strip()
    if raw:
        return Path(raw)
    return repo_root() / _DEFAULT_REL


def is_local_missing_project(project: str) -> bool:
    """True when ``MAPPING_MISSING_BQ_PROJECT=local``."""
    return (project or "").strip().lower() == LOCAL_MISSING_PROJECT


def _parse_kickoff(value: Any) -> datetime | None:
    """Parse kickoff from BQ datetime or ISO string."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def kickoff_to_json(value: Any) -> str | None:
    """Kickoff as UTC ISO for JSONL export."""
    dt = _parse_kickoff(value)
    return dt.isoformat() if dt is not None else None


def serialize_bq_row(row: dict[str, Any]) -> dict[str, Any]:
    """One JSONL record (BQ column names, kickoff as ISO string)."""
    return {
        "symbol": row.get("symbol"),
        "symbol_base": row.get("symbol_base"),
        "fixture_prefix": row.get("fixture_prefix"),
        "crypto_prefix": row.get("crypto_prefix"),
        "market_group": row.get("market_group"),
        "contract_type": row.get("contract_type"),
        "period_type": row.get("period_type"),
        "meta_name": row.get("meta_name"),
        "meta_league": row.get("meta_league"),
        "kickoff": kickoff_to_json(row.get("kickoff")),
        "scope": row.get("scope"),
    }


def load_missing_local_jsonl(path: Path | None = None) -> list[dict[str, Any]]:
    """Load catalogue rows from the dev JSONL file."""
    file_path = path or missing_local_path()
    if not file_path.is_file():
        raise FileNotFoundError(
            f"Missing local catalogue not found: {file_path}. Run: python scripts/export_missing_catalogue_dev.py"
        )
    rows: list[dict[str, Any]] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        raw = json.loads(text)
        kick = _parse_kickoff(raw.get("kickoff"))
        if kick is not None:
            raw["kickoff"] = kick
        rows.append(raw)
    return rows


def write_missing_local_jsonl(rows: list[dict[str, Any]], path: Path | None = None) -> Path:
    """Write BQ-shaped rows to JSONL (gitignored scratch/)."""
    file_path = path or missing_local_path()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(serialize_bq_row(row), ensure_ascii=False) for row in rows]
    file_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return file_path
