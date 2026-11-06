"""Drain wave planning and one league card: seated keys, every book, ledger after propose."""

from __future__ import annotations

import logging
import time
from typing import Any

from BigQuery.alerts import AlertPublisher
from mappers.control_plane.gap_fix import harvest_gap_pins
from mappers.control_plane.gap_fix_slots import DRAIN_CARD_SLOTS
from mappers.control_plane.gap_inventory import RfqGapItem, fetch_rfq_inventory
from mappers.control_plane.gap_inventory_league import attach_league_tokens
from mappers.control_plane.gap_ledger import GapLedgerQueryError
from mappers.control_plane.gap_optic_cache import clear_optic_cache
from mappers.control_plane.models import Actor, ProposalRecord
from mappers.control_plane.pipeline_gap_batch import plan_league_cards
from mappers.control_plane.pipeline_gap_merge import (
    OPEN_REVIEW_STATUSES,
    alert_name_skips,
    alert_needs_code_skips,
    alias_keys_from_payload,
    gap_keys_on_open_review,
    league_keys_from_payload,
    pins_from_payload,
)
from mappers.control_plane.pipeline_gap_propose import (
    PIPELINE_ACTOR,
    ProposeFn,
    _combine_league_group,
    _harvest_pins,
    _pipeline_groups,
    _pipeline_open_proposals,
    _publish,
    _record_gap_ledger,
    filter_new_pins,
    propose_gap_pins,
    record_unknown_platforms,
)
from mappers.control_plane.service import ProposalService

logger = logging.getLogger(__name__)

CARD_PIN_CAP = DRAIN_CARD_SLOTS


def plan_wave(service: ProposalService) -> list[dict[str, Any]]:
    """One inventory fetch → every league card on the page, seated and hottest first.

    Raises ``GapLedgerQueryError`` when the ledger cursor cannot be read.
    """
    items = fetch_rfq_inventory(
        service.store,
        exclude_keys=gap_keys_on_open_review(service),
        fail_closed_ledger=True,
    )
    record_unknown_platforms(getattr(service.store, "current_rule_set_id", None))
    cards = plan_league_cards(service.store, attach_league_tokens(items))
    logger.info(
        "pipeline gap-drain plan keys=%d leagues=%d seated=%d",
        len(items),
        len(cards),
        sum(len(seated) for _league, seated in cards),
    )
    return [
        {"league": league, "items": [_item_json(item) for item in seated]}
        for league, seated in cards
    ]


def run_league_card(
    service: ProposalService,
    card: dict[str, Any],
    *,
    actor: Actor = PIPELINE_ACTOR,
    publisher: AlertPublisher | None = None,
    environment: str = "prod",
    console_base: str | None = None,
    propose_fn: ProposeFn = propose_gap_pins,
) -> dict[str, Any]:
    """Harvest one league's seated keys (every book in parallel), then one Review card."""
    clear_optic_cache()
    league = str(card.get("league") or "")
    items = [_item_from_json(row) for row in card.get("items") or []]
    harvested, err = _drain_harvest(service, league, items)
    if err is not None:
        return {
            "ok": False, "action": "harvest_failed", "progress": False,
            "league": league, "error": str(err),
        }
    result = _drain_propose(
        service,
        harvested,
        actor=actor,
        publisher=publisher,
        propose_fn=propose_fn,
        environment=environment,
        console_base=console_base,
    )
    return {**result, "league": league}


def _item_json(item: RfqGapItem) -> dict[str, Any]:
    return {"book": item.book, "key": item.key, "demand": item.demand, "meta": dict(item.meta or {})}


def _item_from_json(row: dict[str, Any]) -> RfqGapItem:
    meta = row.get("meta") or {}
    return RfqGapItem(
        book=str(row.get("book") or ""),
        key=str(row.get("key") or ""),
        demand=int(row.get("demand") or 0),
        meta={str(k): str(v) for k, v in meta.items()} if isinstance(meta, dict) else {},
    )


def _drain_harvest(
    service: ProposalService,
    league: str,
    items: list[RfqGapItem],
) -> tuple[dict[str, Any], Exception | None]:
    harvest_kw = {
        "drain": True,
        "walked_out": set(),
        "inventory_fn": lambda: list(items),
        "card_league": league,
    }
    t0 = time.monotonic()
    try:
        _, harvested, err = _harvest_pins(service, harvest_gap_pins, harvest_kw)
    except GapLedgerQueryError as exc:
        return {}, exc
    if err is not None:
        return {}, err
    pins = list(harvested.get("pins") or [])
    skipped = list(harvested.get("skipped") or [])
    walked = harvested.get("walked_keys") or []
    logger.info(
        "pipeline gap-drain stage=harvest league=%s sec=%.1f pins=%d skipped=%d walked=%d",
        league,
        time.monotonic() - t0,
        len(pins),
        len(skipped),
        len(walked),
    )
    harvested["progress"] = bool(walked) or bool(pins) or bool(skipped)
    return harvested, None


def _drain_propose(
    service: ProposalService,
    harvested: dict[str, Any],
    *,
    actor: Actor,
    publisher: AlertPublisher | None,
    propose_fn: ProposeFn,
    environment: str,
    console_base: str | None,
) -> dict[str, Any]:
    """Fold this league's harvest into its open Review card."""
    pins = list(harvested.get("pins") or [])
    skipped = list(harvested.get("skipped") or [])
    progress = bool(harvested.get("progress"))
    alert_needs_code_skips(publisher, skipped, _publish)
    new_pins = _filter_new_harvest_pins(service, pins)
    card_league = str(harvested.get("card_league") or "").strip()
    if not new_pins and not card_league:
        _ledger_card(service, harvested, [], skipped)
        logger.info("pipeline gap-drain card skip: no new pins after Review filter")
        return {"ok": True, "action": "skip", "progress": progress, "harvested": len(pins)}
    folded = fold_league_card(
        service,
        card_league,
        new_pins,
        actor=actor,
        propose_fn=propose_fn,
        publisher=publisher,
        environment=environment,
        console_base=console_base,
    )
    return _finish_drain_fold(
        service, harvested, skipped, new_pins, folded, progress, publisher,
    )


def fold_league_card(
    service: ProposalService,
    league: str,
    new_pins: list[dict[str, Any]],
    *,
    actor: Actor,
    propose_fn: ProposeFn,
    publisher: AlertPublisher | None,
    environment: str,
    console_base: str | None,
) -> dict[str, Any]:
    """Amend the league's open cards with new pins; propose the new pins alone if that blocks."""
    cards = _pipeline_groups(_pipeline_open_proposals(service)).get(league, [])
    fold = cards_within_cap(cards, len(new_pins))

    def propose(group: list[ProposalRecord]) -> dict[str, Any]:
        return _combine_league_group(
            service,
            group,
            new_pins,
            actor=actor,
            propose_fn=propose_fn,
            publisher=publisher,
            publish_blocked=False,
            environment=environment,
            console_base=console_base,
            league_key=league,
        )

    result = propose(fold)
    if result.get("ok") or not fold or not new_pins:
        return result
    logger.warning(
        "pipeline gap-drain fold blocked league=%s cards=%d; proposing %d new pin(s) alone",
        league,
        len(fold),
        len(new_pins),
    )
    return propose([])


def cards_within_cap(cards: list[ProposalRecord], new_count: int) -> list[ProposalRecord]:
    """Smallest open cards first, while their pins plus ``new_count`` fit on one card."""
    chosen: list[ProposalRecord] = []
    total = new_count
    for card in sorted(cards, key=_pin_count):
        size = _pin_count(card)
        if total + size > CARD_PIN_CAP:
            break
        chosen.append(card)
        total += size
    return chosen


def _pin_count(card: ProposalRecord) -> int:
    return len(pins_from_payload(card.payload))


def _finish_drain_fold(
    service: ProposalService,
    harvested: dict[str, Any],
    skipped: list[dict[str, str]],
    new_pins: list[dict[str, Any]],
    folded: dict[str, Any],
    progress: bool,
    publisher: AlertPublisher | None,
) -> dict[str, Any]:
    """Ledger the fold and keep the drain stall flag."""
    alert_name_skips(publisher, skipped, folded, _publish)
    if folded.get("noop"):
        extra = _pin_skip_rows(new_pins, "already_mapped")
        _ledger_card(service, harvested, [], skipped + extra)
        return {**folded, "progress": True}
    if not folded.get("ok"):
        extra = _pin_skip_rows(new_pins, _block_reason(folded))
        _ledger_card(service, harvested, [], skipped + extra)
        return {**folded, "progress": True}
    if folded.get("action") != "proposed":
        _ledger_card(service, harvested, [], skipped)
        return {**folded, "progress": progress}
    _ledger_card(service, harvested, new_pins, skipped)
    ref = str((folded.get("review") or {}).get("ref") or "")
    logger.info("pipeline gap-drain proposed ref=%s pins=%d", ref, len(new_pins))
    return folded


def _ledger_card(
    service: ProposalService,
    harvested: dict[str, Any],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
) -> None:
    tip = harvested.get("tip_at_harvest") or getattr(service.store, "current_rule_set_id", None)
    _record_gap_ledger(str(tip) if tip else None, harvested, pins, skipped, store=service.store)


def _block_reason(proposed: dict[str, Any]) -> str:
    """Gate text for a refused card, kept short enough for the ledger reason."""
    blockers = [str(item).strip() for item in (proposed.get("blockers") or []) if str(item).strip()]
    extra = [
        str(item).strip() for item in (proposed.get("skipped_blockers") or []) if str(item).strip()
    ]
    text = (blockers or extra or ["verify_blocked"])[0]
    text = " ".join(text.split())
    if text in {"", "no pins"}:
        return "verify_blocked"
    return text[:120]


def _pin_skip_rows(pins: list[dict[str, Any]], reason: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for pin in pins:
        book = str(pin.get("harvest_book") or pin.get("book") or "").strip()
        key = str(pin.get("harvest_key") or pin.get("gap_key") or "").strip()
        if book and key:
            rows.append({"book": book, "key": key, "reason": reason})
    return rows


def _filter_new_harvest_pins(
    service: ProposalService,
    pins: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    open_props = [
        p for p in service.list_proposals() if p.status in OPEN_REVIEW_STATUSES
    ]
    open_keys: set[tuple[str, str, str]] = set()
    open_leagues: set[tuple[str, str]] = set()
    for proposal in open_props:
        open_keys.update(alias_keys_from_payload(proposal.payload))
        open_leagues.update(league_keys_from_payload(proposal.payload))
    return filter_new_pins(pins, frozenset(open_keys), frozenset(open_leagues))
