"""Merge pipeline-gap-fix Review cards into one alias + league batch."""

from __future__ import annotations

from typing import Any, Protocol

from mappers.control_plane.models import (
    BatchChangesPayload,
    EntityAliasPayload,
    MappingLeaguePayload,
    MappingMarketRulesPayload,
    ProposalRecord,
)

OPEN_REVIEW_STATUSES = frozenset({"proposed", "validated"})
PIPELINE_SUBJECT = "pipeline-gap-fix"
SUPERSEDE_INTO = "superseded: combined into "


def supersede_comment(new_ref: str) -> str:
    """Reject comment written onto pipeline cards folded into ``new_ref``."""
    return f"{SUPERSEDE_INTO}{new_ref}"


def superseded_by_ref(note: str | None) -> str:
    """New proposal id from a supersede reject comment, or empty."""
    text = (note or "").strip()
    if not text.startswith(SUPERSEDE_INTO):
        return ""
    return text[len(SUPERSEDE_INTO) :].strip()


class _ProposalLister(Protocol):
    """Store/service surface used to find open pipeline cards."""

    def list_proposals(self) -> list[ProposalRecord]: ...


def alert_name_skips(
    publisher: Any,
    skipped: list[dict[str, str]],
    folded: dict[str, Any],
    publish: Any,
) -> None:
    """Publish harvest name_mismatch skips and blocked live-name evidence."""
    miss = [
        str(row.get("symbol") or row.get("event_ticker") or "")
        for row in skipped
        if str(row.get("reason") or "") == "name_mismatch"
    ]
    live: list[str] = []
    if folded.get("action") != "proposed":
        live = [
            str(item)
            for item in list(folded.get("blockers") or [])
            if "is live as" in str(item)
        ]
    if not miss and not live:
        return
    lines = [
        f"Pipeline gap-fix name mismatch: {len(miss)} Optic skip(s), "
        f"{len(live)} live-name blocker(s)",
    ]
    lines.extend(f"name_mismatch {sym}" for sym in miss[:10] if sym)
    lines.extend(live[:10])
    publish(publisher, "warning", "\n".join(lines))


def alert_needs_code_skips(
    publisher: Any,
    skipped: list[dict[str, str]],
    publish: Any | None = None,
) -> None:
    """Publish parser-not-ready skips once per harvest card."""
    if publish is None:
        from mappers.control_plane.pipeline_gap_propose import _publish as publish
    hits = [
        row for row in skipped
        if str(row.get("reason") or "") == "needs_code"
    ]
    if not hits:
        return
    lines = [f"Pipeline gap-fix needs_code: {len(hits)} parser gap(s)"]
    for row in hits[:8]:
        book = str(row.get("book") or "")
        key = str(row.get("key") or row.get("event_ticker") or row.get("symbol") or "")
        lines.append(f"needs_code {book}:{key[:80]}")
    publish(publisher, "warning", "\n".join(lines))


def alias_keys_from_pin(pin: dict[str, Any]) -> frozenset[tuple[str, str, str]]:
    """Fingerprint one harvest pin as (league, canonical_key, alias_value)."""
    league = str(pin.get("league") or "")
    canon = str(pin.get("canonical_key") or "")
    keys: set[tuple[str, str, str]] = set()
    for alias in pin.get("aliases") or []:
        value = str(alias.get("alias_value") or "").strip()
        if value:
            keys.add((league, canon, value))
    return frozenset(keys)


def alias_keys_from_payload(payload: Any) -> frozenset[tuple[str, str, str]]:
    """Fingerprint aliases already on a proposal payload."""
    keys: set[tuple[str, str, str]] = set()
    if isinstance(payload, EntityAliasPayload):
        _add_entity_keys(keys, payload)
    elif isinstance(payload, BatchChangesPayload):
        for entity in payload.entity_aliases:
            _add_entity_keys(keys, entity)
    return frozenset(keys)


def alias_keys_from_pins(pins: list[dict[str, Any]]) -> frozenset[tuple[str, str, str]]:
    """Union of harvest-pin fingerprints."""
    keys: set[tuple[str, str, str]] = set()
    for pin in pins:
        keys.update(alias_keys_from_pin(pin))
    return frozenset(keys)


def league_keys_from_pin(pin: dict[str, Any]) -> frozenset[tuple[str, str]]:
    """Fingerprint one mapping_league harvest pin as (league, optic_id)."""
    if str(pin.get("kind") or "") != "mapping_league":
        return frozenset()
    slug = str(pin.get("league") or "").strip()
    if not slug:
        return frozenset()
    return frozenset({(slug, str(pin.get("optic_league_id") or ""))})


def league_keys_from_payload(payload: Any) -> frozenset[tuple[str, str]]:
    """Fingerprint mapping_league rows already on a proposal payload."""
    if isinstance(payload, MappingLeaguePayload):
        return frozenset({(payload.league, payload.optic_league_id)})
    if isinstance(payload, BatchChangesPayload):
        return frozenset(
            (row.league, row.optic_league_id) for row in payload.leagues if row.league
        )
    return frozenset()


def league_keys_from_pins(pins: list[dict[str, Any]]) -> frozenset[tuple[str, str]]:
    """Union of mapping_league harvest-pin fingerprints."""
    keys: set[tuple[str, str]] = set()
    for pin in pins:
        keys.update(league_keys_from_pin(pin))
    return frozenset(keys)


def market_keys_from_pin(pin: dict[str, Any]) -> frozenset[tuple[str, str, str, str]]:
    """Fingerprint one market-rule harvest pin."""
    if str(pin.get("kind") or "") != "mapping_market_rules":
        return frozenset()
    league = str(pin.get("league") or "")
    keys: set[tuple[str, str, str, str]] = set()
    for rule in pin.get("rules") or []:
        if str(rule.get("sportsbook") or "") == "optic":
            continue
        source_key = str(rule.get("source_key") or "").strip()
        if source_key:
            keys.add((
                league,
                str(rule.get("sportsbook") or ""),
                str(rule.get("source_key_type") or ""),
                source_key,
            ))
    return frozenset(keys)


def market_keys_from_payload(payload: Any) -> frozenset[tuple[str, str, str, str]]:
    """Fingerprint market rules already on a proposal payload."""
    keys: set[tuple[str, str, str, str]] = set()
    if isinstance(payload, MappingMarketRulesPayload):
        _add_market_keys(keys, payload)
    elif isinstance(payload, BatchChangesPayload):
        for row in payload.market_rules:
            _add_market_keys(keys, row)
    return frozenset(keys)


def market_keys_from_pins(pins: list[dict[str, Any]]) -> frozenset[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    for pin in pins:
        keys.update(market_keys_from_pin(pin))
    return frozenset(keys)


def pins_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Harvest-shaped pin dicts from an open proposal."""
    out: list[dict[str, Any]] = []
    if isinstance(payload, MappingLeaguePayload):
        out.append(payload.model_dump(mode="json"))
    elif isinstance(payload, EntityAliasPayload):
        if payload.aliases:
            out.append(_pin_dict(payload))
    elif isinstance(payload, BatchChangesPayload):
        out.extend(row.model_dump(mode="json") for row in payload.leagues)
        out.extend(_pin_dict(row) for row in payload.entity_aliases if row.aliases)
        out.extend(row.model_dump(mode="json") for row in payload.market_rules)
    return out


def merge_pins(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe alias pins by league + canonical; keep one mapping_league per slug."""
    league_order: list[str] = []
    leagues: dict[str, dict[str, Any]] = {}
    market_order: list[tuple[str, str, str, str]] = []
    markets: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    ordered: list[tuple[str, str]] = []
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    seen: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for pin in (item for group in groups for item in group):
        if str(pin.get("kind") or "") == "mapping_league":
            slug = str(pin.get("league") or "")
            if not slug:
                continue
            if slug not in leagues:
                league_order.append(slug)
            leagues[slug] = pin
            continue
        if str(pin.get("kind") or "") == "mapping_market_rules":
            key = _market_pin_key(pin)
            if key is None:
                continue
            if key not in markets:
                market_order.append(key)
            markets[key] = pin
            continue
        key = (str(pin.get("league") or ""), str(pin.get("canonical_key") or ""))
        if not key[1]:
            continue
        if key not in merged:
            merged[key] = {**pin, "aliases": []}
            seen[key] = set()
            ordered.append(key)
        _merge_aliases(merged[key], seen[key], list(pin.get("aliases") or []))
        if pin.get("reassign"):
            merged[key]["reassign"] = True
    alias_pins = [merged[key] for key in ordered if merged[key]["aliases"]]
    market_pins = [markets[key] for key in market_order]
    return [leagues[slug] for slug in league_order] + market_pins + alias_pins


def open_pipeline_proposals(lister: _ProposalLister) -> list[ProposalRecord]:
    """Open Review cards proposed by the pipeline actor."""
    return [
        proposal
        for proposal in lister.list_proposals()
        if proposal.status in OPEN_REVIEW_STATUSES
        and proposal.proposer_subject == PIPELINE_SUBJECT
    ]


def gap_keys_on_open_review(service: Any) -> set[tuple[str, str]]:
    """RFQ book/key pairs already on an open Review card (treated as checked)."""
    keys: set[tuple[str, str]] = set()
    for proposal in service.list_proposals():
        if proposal.status not in OPEN_REVIEW_STATUSES:
            continue
        for pin in pins_from_payload(proposal.payload):
            book = str(pin.get("harvest_book") or pin.get("book") or "").strip()
            gap_key = str(pin.get("harvest_key") or pin.get("gap_key") or "").strip()
            if book and gap_key:
                keys.add((book, gap_key))
    return keys


def already_single_pipeline_card(
    pipeline_open: list[ProposalRecord],
    combined: list[dict[str, Any]],
) -> bool:
    """True when one open pipeline card already holds the combined pin set."""
    if len(pipeline_open) != 1:
        return False
    payload = pipeline_open[0].payload
    return (
        alias_keys_from_payload(payload) == alias_keys_from_pins(combined)
        and league_keys_from_payload(payload) == league_keys_from_pins(combined)
        and market_keys_from_payload(payload) == market_keys_from_pins(combined)
    )


def _add_market_keys(
    keys: set[tuple[str, str, str, str]],
    payload: MappingMarketRulesPayload,
) -> None:
    for pin in payload.rules:
        if str(pin.sportsbook or "") == "optic":
            continue
        value = str(pin.source_key or "").strip()
        if value:
            keys.add((
                payload.league,
                str(pin.sportsbook or ""),
                str(pin.source_key_type or ""),
                value,
            ))


def _market_pin_key(pin: dict[str, Any]) -> tuple[str, str, str, str] | None:
    league = str(pin.get("league") or "")
    book_rule = next(
        (r for r in (pin.get("rules") or []) if str(r.get("sportsbook") or "") != "optic"),
        None,
    )
    if book_rule is None:
        return None
    source_key = str(book_rule.get("source_key") or "").strip()
    if not source_key:
        return None
    return (
        league,
        str(book_rule.get("sportsbook") or ""),
        str(book_rule.get("source_key_type") or ""),
        source_key,
    )


def _add_entity_keys(keys: set[tuple[str, str, str]], entity: EntityAliasPayload) -> None:
    """Accumulate alias triples from one entity_alias payload."""
    for pin in entity.aliases:
        value = str(pin.alias_value or "").strip()
        if value:
            keys.add((entity.league, entity.canonical_key, value))


def _pin_dict(row: EntityAliasPayload) -> dict[str, Any]:
    """Serialize one entity_alias payload as a harvest pin."""
    return {
        "kind": "entity_alias",
        "league": row.league,
        "canonical_key": row.canonical_key,
        "entity_type": row.entity_type,
        "canonical_name": row.canonical_name or row.canonical_key,
        "aliases": [alias.model_dump(mode="json") for alias in row.aliases],
        "reassign": row.reassign,
        "evidence_refs": list(row.evidence_refs or []),
    }


def _merge_aliases(
    dest: dict[str, Any],
    seen: set[tuple[str, str]],
    aliases: list[Any],
) -> None:
    """Append unseen alias dicts onto a merged pin."""
    for alias in aliases:
        sportsbook = str(alias.get("sportsbook") or "")
        value = str(alias.get("alias_value") or "").strip()
        fingerprint = (sportsbook, value)
        if not value or fingerprint in seen:
            continue
        seen.add(fingerprint)
        dest["aliases"].append(alias)
