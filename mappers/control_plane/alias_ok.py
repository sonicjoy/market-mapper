"""Build successful alias verify responses (paste + structured)."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.alias_payload import entity_alias_dict
from mappers.control_plane.preview_token import sign_preview

_BOOK = {"crypto.com": "crypto.com", "optic": "Optic"}


def _extraction(**fields: Any) -> dict[str, Any]:
    """Signed-token body for an alias pin."""
    return {
        "sportsbook": fields["sportsbook"],
        "league": fields["league"],
        "alias_value": fields["alias_value"],
        "alias_kind": fields["alias_kind"],
        "entity_type": fields["entity_type"],
        "canonical_key": fields["canonical_key"],
        "canonical_name": fields["canonical_name"],
        "raw_paste": fields["raw_paste"],
        "note": fields["note"],
        "summary": fields["summary"],
        "disambiguation_label": fields.get("disambiguation_label"),
        "reassign": fields["reassign"],
        "remove": bool(fields.get("remove")),
        "evidence_refs": list(fields.get("evidence_refs") or []),
    }


def signed_alias_ok(**kw: Any) -> dict[str, Any]:
    """Signed preview + cart payload for a successful alias verify."""
    sportsbook = kw["sportsbook"]
    alias_value = kw["alias_value"]
    return {
        "ok": True,
        "blockers": [],
        "warnings": kw["warnings"],
        "preview": {
            "summary": kw["summary"],
            "sportsbook_label": _BOOK.get(sportsbook, sportsbook),
            "code": alias_value,
            "entity_name": kw["canonical_name"],
            "league_label": kw["league_label_text"],
            "paste": kw["raw_paste"],
            "evidence": list(kw.get("evidence_refs") or []),
        },
        "preview_token": sign_preview(_extraction(**kw)),
        "payload": entity_alias_dict(
            league=kw["league"],
            sportsbook=sportsbook,
            alias_kind=kw["alias_kind"],
            alias_value=alias_value,
            entity_type=kw["entity_type"],
            canonical_key=kw["canonical_key"],
            canonical_name=kw["canonical_name"],
            reassign=kw["reassign"],
            disambiguation_name=kw.get("disambiguation_label"),
            remove=bool(kw.get("remove")),
        ),
        "needs_name": False,
        "needs_live_ack": False,
        "needs_league": False,
        "disambiguation_choices": [],
    }
