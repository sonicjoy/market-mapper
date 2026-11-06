"""Trader-safe review card builders."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.artifact_apply import payload_league
from mappers.control_plane.batch_apply import batch_summary
from mappers.control_plane.change_view import change_headline
from mappers.control_plane.entry import league_label
from mappers.control_plane.evidence_format import cluster_alias_refs, optic_refs_from_pins
from mappers.control_plane.league_review import BOOK_LABELS, payload_league_refs
from mappers.control_plane.models import (
    BatchChangesPayload,
    CombatEntityRetagPayload,
    EntityAliasPayload,
    ProposalRecord,
)

_BOOK = BOOK_LABELS


def _batch_lines(payload: BatchChangesPayload) -> list[str]:
    """One-liner rows for batch evidence."""
    lines: list[str] = []
    for ea in payload.entity_aliases:
        pin = ea.aliases[0] if ea.aliases else None
        code = pin.alias_value if pin else ea.canonical_key
        lines.append(f"alias {code} -> {ea.canonical_name or ea.canonical_key}")
    for lg in payload.leagues:
        lines.append(f"league {lg.league}")
    for mr in payload.market_rules:
        lines.append(f"{len(mr.rules)} market rule(s) for {mr.league}")
    return lines


def _evidence(proposal: ProposalRecord, change_groups: dict[str, Any] | None) -> list[str]:
    """Paste/note refs, league pin refs, plus payload inventory when no diff."""
    skip = {proposal.summary, ""}
    lines = [
        ref
        for ref in proposal.evidence_refs
        if ref.strip() not in skip and not ref.startswith("Batch:")
    ]
    payload = proposal.payload
    lines.extend(payload_league_refs(payload))
    lines.extend(_optic_from_payload(payload))
    if change_groups is None and isinstance(payload, BatchChangesPayload):
        lines.extend(_batch_lines(payload))
    return cluster_alias_refs(_alias_owners(payload), _uniq(lines))


def _alias_owners(payload: object) -> list[tuple[set[str], str]]:
    """Pin values and display names used to cluster evidence onto aliases."""
    eas: list[EntityAliasPayload] = []
    if isinstance(payload, EntityAliasPayload):
        eas = [payload]
    elif isinstance(payload, BatchChangesPayload):
        eas = list(payload.entity_aliases)
    return [
        (
            {pin.alias_value.strip().lower() for pin in ea.aliases if pin.alias_value.strip()},
            str(ea.canonical_name or ea.canonical_key or "").strip(),
        )
        for ea in eas
    ]


def _optic_from_payload(payload: object) -> list[str]:
    """Named Optic competitor refs from submitted pins (from and to)."""
    eas: list[EntityAliasPayload] = []
    if isinstance(payload, EntityAliasPayload):
        eas = [payload]
    elif isinstance(payload, BatchChangesPayload):
        eas = list(payload.entity_aliases)
    pins = [
        (pin.sportsbook, pin.alias_value, str(ea.canonical_name or ea.canonical_key or ""))
        for ea in eas
        for pin in ea.aliases
    ]
    return optic_refs_from_pins(pins)


def _uniq(refs: list[str]) -> list[str]:
    """First-seen evidence refs."""
    out: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        key = ref.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _payload_slugs(payload: BatchChangesPayload) -> list[str]:
    """Unique league keys in a batch, first-seen order."""
    slugs: list[str] = []
    seen: set[str] = set()
    for slug in (
        [lg.league for lg in payload.leagues]
        + [ea.league for ea in payload.entity_aliases]
        + [mr.league for mr in payload.market_rules]
    ):
        if slug and slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return slugs


def _batch_league_label(payload: BatchChangesPayload) -> str:
    """Human league list for a batch card."""
    slugs = _payload_slugs(payload)
    if not slugs:
        return "Several leagues"
    labels = [league_label(s) for s in slugs]
    if len(labels) <= 3:
        return ", ".join(labels)
    return f"{labels[0]} + {len(labels) - 1} more"


def _n(count: int, one: str, many: str) -> str:
    """Count plus singular/plural noun."""
    return f"{count} {one if count == 1 else many}"


def _payload_headline(payload: object) -> str | None:
    """Queue-card sentence from the submitted payload (no snapshot)."""
    if not isinstance(payload, BatchChangesPayload):
        return None
    n_add = 0
    n_remove = 0
    for entity in payload.entity_aliases:
        pins = [pin for pin in entity.aliases if pin.alias_value.strip()]
        if pins and all(pin.remove for pin in pins):
            n_remove += 1
        else:
            n_add += 1
    n_lg = len(payload.leagues)
    rules = [rule for group in payload.market_rules for rule in group.rules]
    parts: list[str] = []
    if n_add:
        parts.append(f"add {_n(n_add, 'alias', 'aliases')}")
    if n_remove:
        parts.append(f"remove {_n(n_remove, 'alias', 'aliases')}")
    if n_lg:
        parts.append(f"add {_n(n_lg, 'league', 'leagues')}")
    if rules:
        actions = [rule.action for rule in rules]
        alias_rows = n_add + n_remove
        if all(a == "map" for a in actions) and not alias_rows and not n_lg:
            parts.append(
                f"enable {_n(len(rules), 'market rule', 'market rules')} so they start mapping"
            )
        elif all(a == "ignore" for a in actions) and not alias_rows and not n_lg:
            parts.append(f"ignore {_n(len(rules), 'market rule', 'market rules')}")
        else:
            parts.append(f"change {_n(len(rules), 'market rule', 'market rules')}")
    if not parts:
        return None
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + "."


def _alias_remove_only(payload: object) -> bool:
    """True when every submitted alias pin is a removal (no leagues/rules)."""
    if isinstance(payload, EntityAliasPayload):
        return bool(payload.aliases) and all(pin.remove for pin in payload.aliases)
    if not isinstance(payload, BatchChangesPayload):
        return False
    if payload.leagues or payload.market_rules or not payload.entity_aliases:
        return False
    return all(
        bool(ea.aliases) and all(pin.remove for pin in ea.aliases)
        for ea in payload.entity_aliases
    )


def _card_headline(payload: object, change_groups: dict[str, Any] | None) -> str | None:
    """Prefer live snapshot headline; alias deletions use the payload sentence."""
    if isinstance(payload, CombatEntityRetagPayload):
        return _combat_retag_headline(payload, change_groups)
    if _alias_remove_only(payload):
        return _payload_headline(payload)
    if change_groups is not None:
        return change_headline(change_groups)
    return _payload_headline(payload)


def _combat_retag_headline(
    payload: CombatEntityRetagPayload,
    change_groups: dict[str, Any] | None,
) -> str:
    """Tombstoned team keys are identity COW, not deleted fighters."""
    slugs = ", ".join(payload.leagues) or "combat"
    aliases = (change_groups or {}).get("aliases") or {}
    added = int(aliases.get("added_count") or 0)
    removed = int(aliases.get("removed_count") or 0)
    if added or removed:
        return (
            f"Retag {slugs} team → fighter: add {added} fighter rows, "
            f"tombstone {removed} team rows (aliases move with the key)."
        )
    return f"Retag {slugs} match-side entities from team to fighter."


def proposal_brief(proposal: ProposalRecord) -> str:
    """One-line summary for proposal history (headline or stored summary)."""
    headline = _card_headline(proposal.payload, proposal.change_groups)
    if headline:
        return headline
    return proposal.summary


def build_review_view(
    proposal: ProposalRecord,
    *,
    status: str,
    changes: dict[str, Any] | None,
    change_groups: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Strip internal ids from a proposal for the console."""
    payload = proposal.payload
    return {
        "ref": proposal.proposal_id,
        "status": status,
        "summary": proposal.summary,
        "proposer": proposal.proposer_subject,
        "changes": changes,
        "change_groups": change_groups,
        "headline": _card_headline(payload, change_groups),
        "evidence": _evidence(proposal, change_groups),
        "note": proposal.review_note,
        **_artifact_fields(payload),
    }


def _artifact_fields(payload: object) -> dict[str, Any]:
    """Artifact-specific review card fields."""
    if isinstance(payload, EntityAliasPayload):
        pin = payload.aliases[0] if payload.aliases else None
        book = pin.sportsbook if pin else ""
        return {
            "artifact": "entity_alias",
            "sportsbook_label": _BOOK.get(book, book),
            "code": pin.alias_value if pin else None,
            "entity_name": payload.canonical_name or payload.canonical_key,
            "league_label": league_label(payload.league),
        }
    if isinstance(payload, BatchChangesPayload):
        return {
            "artifact": "batch_changes",
            "sportsbook_label": "",
            "code": None,
            "entity_name": batch_summary(payload),
            "league_label": _batch_league_label(payload),
        }
    if isinstance(payload, CombatEntityRetagPayload):
        return {
            "artifact": "combat_entity_retag",
            "sportsbook_label": "",
            "code": None,
            "entity_name": "Retag match-side team → fighter (tombstone team keys)",
            "league_label": ", ".join(payload.leagues) or "combat",
        }
    return {
        "artifact": getattr(payload, "kind", "unknown"),
        "sportsbook_label": "",
        "code": None,
        "entity_name": payload_league(payload),
        "league_label": league_label(payload_league(payload)),
    }
