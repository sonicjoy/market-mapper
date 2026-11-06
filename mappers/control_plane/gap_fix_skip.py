"""Harvest skip rows for crypto probes (AI suggest + pipeline logs).

Split out of gap_fix_draft so pin drafting stays under the file size gate.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mappers.control_plane.crypto_optic_match import name_sides

logger = logging.getLogger(__name__)


def log_harvest_skips(skipped: list[dict[str, str]]) -> None:
    """One INFO line of harvest skip reasons (name_mismatch must not be silent)."""
    counts: dict[str, int] = {}
    for row in skipped:
        reason = str(row.get("reason") or "skip")
        counts[reason] = counts.get(reason, 0) + 1
    if not counts:
        return
    extra = " ".join(f"{key}={counts[key]}" for key in sorted(counts))
    logger.info("pipeline gap-fix harvest skips %s", extra)


def probe_skip(row: dict[str, Any], reason: str) -> dict[str, str]:
    """Skip row plus Optic/title fields the AI suggest layer may consume."""
    raw = row.get("optic")
    optic: dict[str, Any] = raw if isinstance(raw, dict) else {}
    _alias_book, needle, alias = skip_alias(row)
    key = str(row.get("symbol") or "")
    book = "crypto" if key else ""
    out = {
        "reason": reason,
        "book": book,
        "key": key,
        "symbol": str(row.get("symbol") or ""),
        "league": str(row.get("league") or ""),
        "title": str(row.get("title") or row.get("meta_name") or ""),
        "needle": needle,
        "alias_book": book,
        "alias_value": alias,
        "home": str(optic.get("home") or ""),
        "home_id": str(optic.get("home_id") or ""),
        "away": str(optic.get("away") or ""),
        "away_id": str(optic.get("away_id") or ""),
        "leave": "1" if skip_leave(row) else "",
        "candidates": skip_candidates(optic),
    }
    return {key: value for key, value in out.items() if value}


def crypto_id_labels(row: dict[str, Any], ids: list[str]) -> list[str]:
    """Catalogue participant names aligned with crypto_ids (home then away)."""
    home = str(row.get("home_name") or "").strip()
    away = str(row.get("away_name") or "").strip()
    if not home or not away:
        sides = name_sides(str(row.get("meta_name") or ""))
        if sides is not None:
            home, away = sides[0], sides[1]
    if len(ids) == 2:
        return [home, away]
    if len(ids) == 1:
        return [home or away]
    return [""] * len(ids)


def partner_catalogue_label(labels: list[str], label: str) -> str:
    """The other participant name in a two-side catalogue row."""
    want = label.strip()
    cleaned = [part.strip() for part in labels if str(part).strip()]
    if len(cleaned) != 2 or not want:
        return ""
    return cleaned[1] if cleaned[0].casefold() == want.casefold() else cleaned[0]


def skip_leave(row: dict[str, Any]) -> bool:
    """True when a tip row is a documented leave-list collision."""
    return any(bool(item.get("leave")) for item in (row.get("tip") or []) if isinstance(item, dict))


def skip_alias(row: dict[str, Any]) -> tuple[str, str, str]:
    """Book, needle display, and alias value for an AI closed-list pick."""
    title = str(row.get("title") or row.get("meta_name") or "")
    ids = [str(c) for c in (row.get("crypto_ids") or []) if c]
    if ids:
        labels = crypto_id_labels(row, ids)
        return "crypto.com", (labels[0] if labels else title), ids[0]
    return "", title, ""


def skip_candidates(optic: dict[str, Any]) -> str:
    """JSON list of Optic {id, name} sides, or empty."""
    rows = []
    for oid_key, name_key in (("home_id", "home"), ("away_id", "away")):
        oid = str(optic.get(oid_key) or "").strip()
        name = str(optic.get(name_key) or "").strip()
        if oid and name:
            rows.append({"id": oid, "name": name})
    if not rows:
        return ""
    return json.dumps(rows, separators=(",", ":"))
