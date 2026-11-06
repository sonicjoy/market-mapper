"""GKE CronJob harvest → Review proposal (never approve).

Inventories RFQ true gaps (crypto.com + Polymarket + listed books), probes
crypto in parallel, tries Polymarket US aliases and league pins (skip only
after evidence failure), and keeps **one** open pipeline Review card.
Human Approve only.

Usage:
    python -m mappers.control_plane.pipeline_gap_propose
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections.abc import Callable
from typing import Any, Protocol

from BigQuery.alerts import (
    AlertPublisher,
    Severity,
    bool_env,
    build_gap_propose_publisher,
    format_critical_alert,
)
from BigQuery.client import ro_client
from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.chat_live import build_chat_live_lookup
from mappers.control_plane.dry_run_already import NOOP_BLOCKER
from mappers.control_plane.gap_fix import harvest_gap_pins, propose_gap_pins
from mappers.control_plane.gap_inventory import MAX_EVENTS, RfqGapItem
from mappers.control_plane.gap_ledger import (
    GapOutcome,
    build_outcomes,
    gap_ledger_enabled,
    summarize_outcomes,
    write_league_reopen,
    write_ledger,
)
from mappers.control_plane.gap_optic_cache import clear_optic_cache
from mappers.control_plane.live_evidence import probe_pin_evidence
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    CombatEntityRetagPayload,
    MappingMarketRulesPayload,
    ProposalRecord,
)
from mappers.control_plane.pipeline_gap_batch import UNKNOWN_LEAGUE, league_resolver
from mappers.control_plane.pipeline_gap_deadline import arm_deadline_watch
from mappers.control_plane.pipeline_gap_memory import (
    arm_memory_pressure_watch,
    cgroup_memory_ratio,
)
from mappers.control_plane.pipeline_gap_merge import (
    OPEN_REVIEW_STATUSES,
    PIPELINE_SUBJECT,
    alert_name_skips,
    alias_keys_from_payload,
    alias_keys_from_pin,
    already_single_pipeline_card,
    league_keys_from_payload,
    league_keys_from_pin,
    merge_pins,
    pins_from_payload,
    supersede_comment,
)
from mappers.control_plane.rfq_platforms import fetch_unknown_mapping_failure_platforms
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import get_settings

logger = logging.getLogger(__name__)

OUTAGE_SEVERITY: Severity = "critical"

PIPELINE_NOTE = "pipeline gap-fix"
PIPELINE_NOTE_SEP = " · "
PIPELINE_ACTOR = Actor(subject="pipeline-gap-fix", role=ActorRole.PROPOSER)
PIPELINE_SUPERSEDE_ACTOR = Actor(subject="pipeline-gap-merge", role=ActorRole.SERVICE)
_PROD_CONSOLE = "https://mapping.mm.whiteswandata.com"
_TEST_CONSOLE = "https://mapping.mm-test.whiteswandata.com"

HarvestFn = Callable[..., dict[str, Any]]
ProposeFn = Callable[..., dict[str, Any]]


class _ProposalLister(Protocol):
    """Store/service surface used for open-card fingerprinting and supersede."""

    def list_proposals(self) -> list[ProposalRecord]: ...

    def reject(self, proposal_id: str, actor: Actor, comment: str = "") -> dict[str, Any]: ...


def pipeline_gap_propose_enabled() -> bool:
    """Kill switch; default on so the CronJob can feed Review."""
    return bool_env("MAPPING_PIPELINE_GAP_PROPOSE", default=True)


def filter_new_pins(
    pins: list[dict[str, Any]],
    open_keys: frozenset[tuple[str, str, str]],
    open_leagues: frozenset[tuple[str, str]] = frozenset(),
) -> list[dict[str, Any]]:
    """Drop pins whose aliases or league rows are already on an open Review card."""
    new_pins: list[dict[str, Any]] = []
    for pin in pins:
        league_keys = league_keys_from_pin(pin)
        if league_keys and league_keys <= open_leagues:
            continue
        keys = alias_keys_from_pin(pin)
        if keys and keys <= open_keys:
            continue
        new_pins.append(pin)
    return new_pins


def pipeline_note_for_league(league: str) -> str:
    """Review note for one drain league card (legacy cards keep plain ``PIPELINE_NOTE``)."""
    slug = str(league or "").strip()
    if not slug:
        return PIPELINE_NOTE
    return f"{PIPELINE_NOTE}{PIPELINE_NOTE_SEP}{slug}"


def pipeline_league_group(note: str | None) -> str:
    """League bucket for combine: suffix after `` · ``, else legacy empty bucket."""
    text = str(note or "").strip()
    if not text.startswith(PIPELINE_NOTE):
        return ""
    if PIPELINE_NOTE_SEP in text:
        return text.split(PIPELINE_NOTE_SEP, 1)[1].strip()
    return ""


def _pipeline_league_bucket(proposal: ProposalRecord) -> str:
    """League from the harvest note; a sole payload league when the note has none."""
    noted = _noted_pipeline_league(proposal)
    if noted:
        return noted
    leagues = _payload_league_slugs(proposal)
    if len(leagues) == 1:
        return next(iter(leagues))
    return ""


def _noted_pipeline_league(proposal: ProposalRecord) -> str:
    """League suffix on the harvest note, skipping earlier pin notes."""
    for note in _proposal_notes(proposal):
        if note.startswith(PIPELINE_NOTE) and PIPELINE_NOTE_SEP in note:
            return pipeline_league_group(note)
    return ""


def _proposal_notes(proposal: ProposalRecord) -> list[str]:
    """Pin notes and the harvest note, in evidence order, then the review comment."""
    notes = [
        str(ref).removeprefix("note:").strip()
        for ref in (proposal.evidence_refs or [])
        if str(ref).strip().startswith("note:")
    ]
    review = str(proposal.review_note or "").strip()
    if review:
        notes.append(review)
    return notes


def _payload_league_slugs(proposal: ProposalRecord) -> set[str]:
    """Leagues named on the proposal payload."""
    payload = proposal.payload
    slugs = {slug for slug, _optic in league_keys_from_payload(payload) if slug}
    slugs.update(str(pin.get("league") or "").strip() for pin in pins_from_payload(payload))
    if isinstance(payload, MappingMarketRulesPayload):
        slugs.add(payload.league)
    if isinstance(payload, CombatEntityRetagPayload):
        slugs.update(payload.leagues)
    slugs.discard("")
    return slugs


def pipeline_league_from_pins(pins: list[dict[str, Any]]) -> str:
    """Infer drain league from harvest pins when note is not set yet."""
    leagues = {str(pin.get("league") or "").strip() for pin in pins if pin.get("league")}
    if len(leagues) == 1:
        return next(iter(leagues))
    return ""


def reopen_leagues_from_proposal(proposal: ProposalRecord) -> set[str]:
    """Leagues whose ignored ledger keys come back once this change activates.

    A league row change also reopens ``unknown``: keys the tip had no rule for may resolve now.
    """
    out = _payload_league_slugs(proposal)
    out.add(_pipeline_league_bucket(proposal))
    if any(slug for slug, _ in league_keys_from_payload(proposal.payload)):
        out.add(UNKNOWN_LEAGUE)
    out.discard("")
    return out


def record_league_reopen(tip_rule_set_id: str | None, proposal: ProposalRecord) -> None:
    """After activate, reopen every league this change touched, whoever proposed it."""
    write_league_reopen(tip_rule_set_id, reopen_leagues_from_proposal(proposal))


def console_review_url(ref: str, *, environment: str, base: str | None = None) -> str:
    """Absolute Review card URL for Slack (test vs prod host)."""
    default = _TEST_CONSOLE if environment == "test" else _PROD_CONSOLE
    root = (base or os.environ.get("MAPPING_CONSOLE_URL") or default).rstrip("/")
    return f"{root}/review/{ref}"


def combine_open_pipeline_cards(
    service: ProposalService,
    extra_pins: list[dict[str, Any]] | None = None,
    *,
    actor: Actor = PIPELINE_ACTOR,
    propose_fn: ProposeFn = propose_gap_pins,
    publisher: AlertPublisher | None = None,
    publish_blocked: bool = True,
    environment: str = "prod",
    console_base: str | None = None,
) -> dict[str, Any]:
    """Union open pipeline cards per league bucket (drain cards do not cross leagues)."""
    pins = extra_pins or []
    target_league = pipeline_league_from_pins(pins) if pins else None
    pipeline_open = _pipeline_open_proposals(service)
    groups = _pipeline_groups(pipeline_open)
    if not groups and not pins:
        return _skip_no_new_pins(pins, 0)
    league_keys = [target_league] if target_league is not None else sorted(groups.keys())
    if pins and target_league is None:
        league_keys = [""]
    last: dict[str, Any] | None = None
    for league_key in league_keys:
        group = groups.get(league_key, [])
        slice_pins = pins if (target_league is None or league_key == target_league) else []
        if not group and not slice_pins:
            continue
        merged = _combine_league_group(
            service,
            group,
            slice_pins,
            actor=actor,
            propose_fn=propose_fn,
            publisher=publisher,
            publish_blocked=publish_blocked,
            environment=environment,
            console_base=console_base,
            league_key=league_key,
        )
        last = merged
    return last or _skip_no_new_pins(pins, 0)


def _pipeline_open_proposals(service: ProposalService) -> list[ProposalRecord]:
    open_props = [
        proposal
        for proposal in service.list_proposals()
        if proposal.status in OPEN_REVIEW_STATUSES
    ]
    return [proposal for proposal in open_props if proposal.proposer_subject == PIPELINE_SUBJECT]


def _pipeline_groups(pipeline_open: list[ProposalRecord]) -> dict[str, list[ProposalRecord]]:
    groups: dict[str, list[ProposalRecord]] = {}
    for proposal in pipeline_open:
        key = _pipeline_league_bucket(proposal)
        groups.setdefault(key, []).append(proposal)
    return groups


def _combine_league_group(
    service: ProposalService,
    pipeline_open: list[ProposalRecord],
    harvest: list[dict[str, Any]],
    *,
    actor: Actor,
    propose_fn: ProposeFn,
    publisher: AlertPublisher | None,
    publish_blocked: bool,
    environment: str,
    console_base: str | None,
    league_key: str,
) -> dict[str, Any]:
    combined, already = _combined_review_pins_for_group(service, pipeline_open, harvest)
    if not combined or already_single_pipeline_card(pipeline_open, combined):
        return _skip_no_new_pins(harvest, already)
    note = pipeline_note_for_league(league_key) if league_key else PIPELINE_NOTE
    logger.info(
        "pipeline gap-fix combining league=%r cards=%d pins=%d",
        league_key or "(legacy)",
        len(pipeline_open),
        len(combined),
    )
    proposed = propose_fn(
        service,
        actor,
        combined,
        acknowledge_shadow=True,
        note=note,
        existing_proposal_id=pipeline_open[0].proposal_id if pipeline_open else None,
    )
    if proposed.get("noop"):
        return {**_skip_no_new_pins(harvest, already), "noop": True}
    if not proposed.get("ok"):
        return _blocked_propose(
            publisher, harvest, combined, proposed, publish=publish_blocked,
        )
    new_ref = str((proposed.get("review") or {}).get("ref") or "")
    _supersede_pipeline_cards(service, PIPELINE_SUPERSEDE_ACTOR, pipeline_open, new_ref)
    return _proposed_review(publisher, harvest, already, combined, proposed, environment, console_base)


def run_pipeline_gap_propose(
    *,
    service: ProposalService,
    actor: Actor = PIPELINE_ACTOR,
    harvest_fn: HarvestFn = harvest_gap_pins,
    propose_fn: ProposeFn = propose_gap_pins,
    publisher: AlertPublisher | None = None,
    environment: str = "prod",
    console_base: str | None = None,
    harvest_kw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge sibling pipeline cards first, then harvest → one Review card."""
    clear_optic_cache()
    return _run_harvest_stages(
        service,
        actor,
        harvest_fn,
        propose_fn,
        publisher,
        environment,
        console_base,
        harvest_kw,
    )


def _run_harvest_stages(
    service: ProposalService,
    actor: Actor,
    harvest_fn: HarvestFn,
    propose_fn: ProposeFn,
    publisher: AlertPublisher | None,
    environment: str,
    console_base: str | None,
    harvest_kw: dict[str, Any] | None,
) -> dict[str, Any]:
    """Sibling merge, harvest, fold — each timed for CronJob logs."""
    t0 = time.monotonic()
    sibling = combine_open_pipeline_cards(
        service,
        [],
        actor=actor,
        propose_fn=propose_fn,
        publisher=publisher,
        publish_blocked=False,
        environment=environment,
        console_base=console_base,
    )
    _log_stage("sibling", t0, action=sibling.get("action"))
    t1 = time.monotonic()
    _tip_at_harvest, harvested, err = _harvest_pins(service, harvest_fn, harvest_kw)
    pins = list(harvested.get("pins") or [])
    skipped = list(harvested.get("skipped") or [])
    _log_stage("harvest", t1, pins=len(pins), skipped=len(skipped), error=bool(err))
    if err is not None:
        return _harvest_failed(publisher, sibling, err)
    _record_gap_ledger(_tip_at_harvest, harvested, pins, skipped, store=service.store)
    t2 = time.monotonic()
    folded = _fold_harvest(
        service,
        sibling,
        pins,
        actor=actor,
        propose_fn=propose_fn,
        publisher=publisher,
        environment=environment,
        console_base=console_base,
    )
    alert_name_skips(publisher, skipped, folded, _publish)
    _log_stage("propose", t2, action=folded.get("action"))
    return folded


def _log_stage(name: str, started: float, **fields: Any) -> None:
    """One INFO line: stage name, seconds, cgroup %, and compact key=value fields."""
    ratio = cgroup_memory_ratio()
    if ratio is not None:
        fields = {**fields, "mem_pct": f"{ratio * 100:.0f}"}
    extra = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info(
        "pipeline gap-fix stage=%s sec=%.1f %s",
        name,
        time.monotonic() - started,
        extra,
    )


def _harvest_pins(
    service: ProposalService,
    harvest_fn: HarvestFn,
    harvest_kw: dict[str, Any] | None,
) -> tuple[str | None, dict[str, Any], Exception | None]:
    """Run harvest; return (tip, harvest payload, error)."""
    tip = getattr(service.store, "current_rule_set_id", None)
    try:
        harvested = harvest_fn(service.store, **(harvest_kw or {}))
        tip = harvested.get("tip_at_harvest") or tip
        return (str(tip) if tip else None), dict(harvested), None
    except MemoryError:
        raise
    except Exception as exc:
        logger.exception("pipeline gap-fix harvest failed; sibling merge kept")
        return None, {}, exc


def _record_gap_ledger(
    tip_rule_set_id: str | None,
    harvested: dict[str, Any],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    store: Any | None = None,
) -> None:
    """Optional BQ ledger + log line for this tick's RFQ inventory outcomes."""
    inv_raw = list(harvested.get("inventory") or [])
    inventory = [
        RfqGapItem(str(row.get("book") or ""), str(row.get("key") or ""), int(row.get("demand") or 0))
        for row in inv_raw
        if row.get("book") and row.get("key")
    ]
    walked_raw = harvested.get("walked_keys") or []
    walked: set[tuple[str, str]] = {
        (str(book), str(key))
        for book, key in walked_raw
        if book and key
    }
    card_league = str(harvested.get("card_league") or "").strip()
    if card_league:
        league_for: Callable[[RfqGapItem], str] | None = lambda _item: card_league  # noqa: E731
    elif store is not None and inventory:
        league_for = league_resolver(store)
    else:
        league_for = None
    outcomes = build_outcomes(inventory, pins, skipped, walked_keys=walked, league_for=league_for)
    if not card_league:
        outcomes.extend(_unknown_platform_outcomes())
    if outcomes:
        logger.info("pipeline gap-fix ledger %s", summarize_outcomes(outcomes))
    if gap_ledger_enabled() and outcomes:
        write_ledger(outcomes, tip_rule_set_id=tip_rule_set_id)


def record_unknown_platforms(tip_rule_set_id: str | None) -> None:
    """Ledger RFQ platforms outside the harvest list. The drain calls this once per wave."""
    outcomes = _unknown_platform_outcomes()
    if gap_ledger_enabled() and outcomes:
        write_ledger(outcomes, tip_rule_set_id=tip_rule_set_id)


def _unknown_platform_outcomes() -> list[GapOutcome]:
    try:
        unknown = fetch_unknown_mapping_failure_platforms()
    except Exception:
        logger.exception("pipeline gap-fix unknown RFQ platform query failed")
        return []
    if unknown:
        head = "; ".join(f"{plat}({dem})" for plat, dem in unknown[:5])
        logger.warning("pipeline gap-fix unknown RFQ platforms: %s", head)
    return [
        GapOutcome("rfq", platform, demand, "unknown_platform", reason=platform)
        for platform, demand in unknown
    ]


def _fold_harvest(
    service: ProposalService,
    sibling: dict[str, Any],
    pins: list[dict[str, Any]],
    *,
    actor: Actor,
    propose_fn: ProposeFn,
    publisher: AlertPublisher | None,
    environment: str,
    console_base: str | None,
) -> dict[str, Any]:
    """Combine harvest pins into one Review card."""
    folded = combine_open_pipeline_cards(
        service,
        pins,
        actor=actor,
        propose_fn=propose_fn,
        publisher=publisher,
        environment=environment,
        console_base=console_base,
    )
    if folded.get("action") == "skip" and sibling.get("action") == "proposed":
        return sibling
    return folded


def build_pipeline_service() -> tuple[ProposalService, str]:
    """BigQuery-backed control plane (propose/validate only; no activate)."""
    settings = get_settings()
    store = BigQueryStore(
        ro_client(),
        environment=settings.environment,
        allow_activate=False,
        cow_enabled=settings.cow_enabled,
        # This job runs for minutes in its own process, so it must never serve a
        # tip the console activated in the meantime; only the console can set_tip.
        tip_ttl_sec=0.0,
    )
    service = ProposalService(
        store,  # type: ignore[arg-type]
        live=build_chat_live_lookup(settings),
        evidence_fn=probe_pin_evidence,
        require_maker_checker=settings.require_maker_checker,
    )
    return service, settings.environment


def run_once() -> dict[str, Any]:
    """CLI path: build service, run one propose pass."""
    service, environment = build_pipeline_service()
    publisher = build_gap_propose_publisher()
    deadline_watch = arm_deadline_watch(publisher, _publish)
    memory_watch = arm_memory_pressure_watch(publisher, _publish)
    try:
        result = run_pipeline_gap_propose(
            service=service,
            publisher=publisher,
            environment=environment,
        )
        deadline_watch.disarm()
        memory_watch.disarm()
        return result
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        logger.exception("pipeline gap-fix crashed")
        _publish(
            publisher,
            OUTAGE_SEVERITY,
            f"Pipeline gap-fix: crashed before finish.\n{detail}",
        )
        raise
    finally:
        deadline_watch.disarm()
        memory_watch.disarm()
        publisher.close()


def main(argv: list[str] | None = None) -> int:
    """0 on skip/proposed/blocked; non-zero only on harvest crash (backoffLimit: 0)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not pipeline_gap_propose_enabled():
        logger.info("pipeline gap-fix disabled (MAPPING_PIPELINE_GAP_PROPOSE=0)")
        return 0
    argparse.ArgumentParser(
        prog="pipeline_gap_propose",
        description="RFQ true-gap harvest → one Review card (never Approve).",
    ).parse_args(argv)
    try:
        result = run_once()
        logger.info("pipeline gap-fix done action=%s", result.get("action"))
    except Exception:
        logger.exception("pipeline gap-fix failed")
        return 1
    return _exit_code(result)


def _exit_code(result: dict[str, Any]) -> int:
    """Blocked propose already alerted; do not re-harvest under Forbid."""
    if result.get("harvest_error"):
        return 1
    action = str(result.get("action") or "")
    if action in {"skip", "proposed", "blocked"}:
        return 0
    if not result.get("ok", False):
        return 1
    return 0


def _harvest_failed(
    publisher: AlertPublisher | None,
    sibling: dict[str, Any],
    err: Exception,
) -> dict[str, Any]:
    """Keep a successful sibling merge; otherwise surface the harvest error."""
    detail = f"{type(err).__name__}: {err}"
    logger.error("pipeline gap-fix harvest failed: %s", detail)
    _publish(publisher, OUTAGE_SEVERITY, _harvest_failed_alert_text(detail, sibling))
    if sibling.get("action") == "proposed":
        return {**sibling, "harvest_error": detail}
    return {"ok": False, "action": "harvest_failed", "error": detail}


def _harvest_failed_alert_text(detail: str, sibling: dict[str, Any]) -> str:
    """Outage body when harvest raises after sibling merge may have proposed."""
    if sibling.get("action") == "proposed":
        return (
            "Pipeline gap-fix: harvest failed after sibling merge — "
            "open Review card may be stale; new pins not harvested.\n"
            + detail
        )
    return "Pipeline gap-fix: harvest failed — no Review card this tick.\n" + detail


def _skip_no_new_pins(pins: list[dict[str, Any]], already: int) -> dict[str, Any]:
    """Log and return when harvest is empty or already in Review."""
    logger.info(
        "pipeline gap-fix skip: no new pins (harvested=%d already_in_review=%d)",
        len(pins),
        already,
    )
    return {
        "ok": True,
        "action": "skip",
        "reason": "no_new_pins",
        "harvested": len(pins),
        "already_in_review": already,
    }


def _blocked_propose(
    publisher: AlertPublisher | None,
    pins: list[dict[str, Any]],
    new_pins: list[dict[str, Any]],
    proposed: dict[str, Any],
    *,
    publish: bool = True,
) -> dict[str, Any]:
    """Log, alert, and return a blocked propose result."""
    blockers = list(proposed.get("blockers") or [])
    if blockers and all(blocker == NOOP_BLOCKER for blocker in blockers):
        return _skip_no_new_pins(pins, len(new_pins))
    logger.warning("pipeline gap-fix blocked: %s", blockers)
    if publish:
        _publish(
            publisher,
            "warning",
            "Pipeline gap-fix blocked (no Review card; human Approve unchanged)\n"
            + "; ".join(str(b) for b in blockers[:5]),
        )
    return {
        "ok": False,
        "action": "blocked",
        "harvested": len(pins),
        "count": len(new_pins),
        **proposed,
    }


def _proposed_review(
    publisher: AlertPublisher | None,
    pins: list[dict[str, Any]],
    already: int,
    new_pins: list[dict[str, Any]],
    proposed: dict[str, Any],
    environment: str,
    console_base: str | None,
) -> dict[str, Any]:
    """Alert and return a successful Review proposal."""
    review = proposed.get("review") or {}
    ref = str(review.get("ref") or "")
    url = console_review_url(ref, environment=environment, base=console_base) if ref else ""
    skipped = list(proposed.get("skipped_blockers") or [])
    count = int(proposed.get("count") or len(new_pins))
    logger.info(
        "pipeline gap-fix proposed ref=%s pins=%d skipped=%d (human Approve)",
        ref,
        count,
        len(skipped),
    )
    _publish(publisher, "warning", _alert_text(count, url, skipped))
    return {
        "ok": True,
        "action": "proposed",
        # The drain stall counter treats a missing flag as no progress.
        "progress": True,
        "harvested": len(pins),
        "already_in_review": already,
        "count": count,
        "skipped_blockers": skipped,
        "review": review,
        "url": url,
    }


def _combined_review_pins(
    service: _ProposalLister,
    harvest: list[dict[str, Any]],
) -> tuple[list[ProposalRecord], list[dict[str, Any]], int]:
    """Union all open pipeline pins with harvest pins (legacy helper)."""
    pipeline_open = [
        proposal
        for proposal in service.list_proposals()
        if proposal.status in OPEN_REVIEW_STATUSES
        and proposal.proposer_subject == PIPELINE_SUBJECT
    ]
    combined, already = _combined_review_pins_for_group(service, pipeline_open, harvest)
    return pipeline_open, combined, already


def _combined_review_pins_for_group(
    service: _ProposalLister,
    pipeline_open: list[ProposalRecord],
    harvest: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Merge one league group's open cards with new harvest pins."""
    open_props = [
        proposal
        for proposal in service.list_proposals()
        if proposal.status in OPEN_REVIEW_STATUSES
    ]
    open_keys: set[tuple[str, str, str]] = set()
    open_leagues: set[tuple[str, str]] = set()
    for proposal in open_props:
        open_keys.update(alias_keys_from_payload(proposal.payload))
        open_leagues.update(league_keys_from_payload(proposal.payload))
    new_pins = filter_new_pins(harvest, frozenset(open_keys), frozenset(open_leagues))
    already = len(harvest) - len(new_pins)
    combined = merge_pins(
        *[pins_from_payload(proposal.payload) for proposal in pipeline_open],
        new_pins,
    )
    return combined, already


def _supersede_pipeline_cards(
    service: _ProposalLister,
    actor: Actor,
    old: list[ProposalRecord],
    new_ref: str,
) -> None:
    """Reject sibling pipeline cards after a combined proposal lands."""
    comment = supersede_comment(new_ref)
    for proposal in old:
        if proposal.proposal_id == new_ref:
            continue
        try:
            service.reject(proposal.proposal_id, actor, comment)
        except Exception:
            logger.exception("pipeline gap-fix supersede failed ref=%s", proposal.proposal_id)


def _alert_text(count: int, url: str, skipped: list[str] | None = None) -> str:
    """Slack body: Review URL, human Approve required; skipped mismatches."""
    lines = [
        f"Pipeline gap-fix: {count} pin(s) in Review — human Approve required",
    ]
    if url:
        lines.append(url)
    lines.append(
        "RFQ true-gap harvest (crypto.com + Polymarket + listed books; "
        f"{MAX_EVENTS} pin slots each)"
    )
    if skipped:
        head = skipped[:5]
        line = "Skipped blocker(s): " + "; ".join(head)
        tail = len(skipped) - len(head)
        if tail > 0:
            line += f" (+{tail} more)"
        lines.append(line)
    return "\n".join(lines)


def _publish(publisher: AlertPublisher | None, severity: Severity, text: str) -> None:
    """Best-effort alert; swallow publisher errors."""
    if publisher is None:
        return
    if severity == "critical":
        text = format_critical_alert(text)
    try:
        publisher.publish(severity, text)
    except Exception:
        logger.exception("pipeline gap-fix alert publish failed")


if __name__ == "__main__":
    sys.exit(main())
