"""Extended console ops: league/market-rule entry, rules explorer, batch."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.batch_apply import batch_summary, dry_run_batch
from mappers.control_plane.console_history import build_rule_history
from mappers.control_plane.console_rules_query import parse_rules_query, search_human_rules
from mappers.control_plane.dry_run_already import (
    resolved_enabled,
    resolved_extra_optic_ids,
    resolved_fixture_horizon,
    resolved_output_order,
)
from mappers.control_plane.dry_run_league import thin_dry_run_league
from mappers.control_plane.dry_run_market_rules import thin_dry_run_market_rules
from mappers.control_plane.entry import ACK_RULES_WRITE, league_label
from mappers.control_plane.evidence_format import cluster_alias_refs
from mappers.control_plane.league_review import (
    league_pin_refs,
    payload_alias_refs,
    payload_league_refs,
)
from mappers.control_plane.live_evidence import collect_pins_evidence
from mappers.control_plane.market_rule_preview import batch_rule_cards, rule_cards
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    BatchChangesPayload,
    BatchEntryRequest,
    ConflictError,
    ForbiddenError,
    LeagueEntryRequest,
    MappingLeaguePayload,
    MappingMarketRulesPayload,
    MarketRuleEntryRequest,
    ProposeRequest,
    ValidationFailedError,
)
from mappers.control_plane.official_citation import (
    absence_warnings,
    batch_absence_warnings,
    stamp_batch_official,
    stamp_market_payload,
)
from mappers.control_plane.parity_lines import latest_mismatch_rows
from mappers.control_plane.pipeline_gap_merge import OPEN_REVIEW_STATUSES
from mappers.control_plane.preview_token import (
    preview_request_id,
    sign_preview,
    unsign_preview,
)
from mappers.control_plane.rows import LeagueRow
from mappers.control_plane.store import new_id

_WRITE_ROLES = {
    ActorRole.PROPOSER,
    ActorRole.APPROVER,
    ActorRole.ADMIN,
    ActorRole.SERVICE,
}


def _batch_evidence(
    store: Any,
    payload: BatchChangesPayload,
    note: str | None,
    probe: Any,
) -> tuple[list[str], list[str]]:
    """Harvest alias refs, then live pin probes, then league pins."""
    refs = list(payload_alias_refs(payload))
    live, blockers = collect_pins_evidence(
        store,
        payload.entity_aliases,
        probe=probe,
    )
    seen = set(refs)
    for ref in [*live, *payload_league_refs(payload)]:
        if ref and ref not in seen:
            seen.add(ref)
            refs.append(ref)
    if note:
        tagged = f"note:{note}"
        if tagged not in seen:
            refs.append(tagged)
    owners = [
        (
            {pin.alias_value.strip().lower() for pin in ea.aliases if pin.alias_value.strip()},
            str(ea.canonical_name or ea.canonical_key or "").strip(),
        )
        for ea in payload.entity_aliases
    ]
    return cluster_alias_refs(owners, refs), blockers


class ExtendedOpsMixin:
    """Additional trader-facing control-plane methods."""

    store: Any
    require_maker_checker: bool

    def entry_league_verify(self, body: LeagueEntryRequest) -> dict[str, Any]:
        """Validate a league form before submit (live-activate ack required)."""
        current = self.store.current_rule_set_id  # type: ignore[attr-defined]
        leagues = self.store.leagues_for(current) if current else []  # type: ignore[attr-defined]
        existing = next((row for row in leagues if row.league == body.league.strip()), None)
        payload = MappingLeaguePayload(
            league=body.league.strip(),
            sport=body.sport.strip(),
            optic_league_id=body.optic_league_id.strip(),
            extra_optic_league_ids=resolved_extra_optic_ids(None, existing),
            fixture_source=body.fixture_source,
            fixture_horizon_hours=resolved_fixture_horizon(
                body.fixture_horizon_hours, existing
            ),
            enabled=resolved_enabled(None, existing),
            output_order=resolved_output_order(None, existing),
            entity_type=body.entity_type,
            alias_enforcement=body.alias_enforcement,
            runshop_enabled=body.runshop_enabled,
            exchanges=body.exchanges,
            clone_market_rules_from=body.clone_market_rules_from,
            notes=body.note,
        )
        dry = thin_dry_run_league(leagues, payload)
        blockers = list(dry["blockers"])
        if not body.acknowledge_shadow:
            blockers.append(ACK_RULES_WRITE)
        verb = "Update" if dry.get("updating") else "Add"
        return {
            "ok": not blockers,
            "blockers": blockers,
            "warnings": dry["warnings"],
            "preview": {
                "summary": f"{verb} league **{payload.league}** ({payload.sport})",
                "league_label": league_label(payload.league),
                "optic_league_id": payload.optic_league_id,
                "exchange_count": len(payload.exchanges),
            },
            "payload": payload.model_dump(mode="json"),
        }

    def entry_league_submit(
        self,
        body: LeagueEntryRequest,
        actor: Actor,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Propose + validate a mapping_league from the trader form."""
        verified = self.entry_league_verify(body)
        if not verified["ok"]:
            raise ValidationFailedError(
                "league entry blocked",
                reason_code="entry_blocked",
                dry_run=verified,
            )
        current = self.store.current_rule_set_id  # type: ignore[attr-defined]
        if current is None:
            raise ConflictError("no current rule set", reason_code="no_rule_set")
        payload = MappingLeaguePayload.model_validate(verified["payload"])
        if body.note and not payload.notes:
            payload = payload.model_copy(update={"notes": body.note})
        verb = (
            "Update"
            if verified.get("warnings") and any("Updating existing" in w for w in verified.get("warnings", []))
            else "Add"
        )
        req = ProposeRequest(
            request_id=request_id or new_id("req"),
            expected_rule_set_id=current,
            artifact_type="mapping_league",
            summary=f"{verb} league {payload.league}",
            evidence_refs=league_pin_refs(payload),
            payload=payload,
        )
        prop = self.propose(req, actor)  # type: ignore[attr-defined]
        self.validate(prop.proposal_id, actor)  # type: ignore[attr-defined]
        return self._review_view(self._get(prop.proposal_id))  # type: ignore[attr-defined]

    def entry_market_rule_verify(self, body: MarketRuleEntryRequest) -> dict[str, Any]:
        """Validate market-rule form before submit."""
        current = self.store.current_rule_set_id  # type: ignore[attr-defined]
        tip_leagues = self.store.leagues_for(current) if current else []  # type: ignore[attr-defined]
        tip_slugs = {row.league for row in tip_leagues}
        pending = {s.strip() for s in body.pending_league_slugs if s and s.strip()}
        league = body.league.strip()
        leagues = list(tip_leagues)
        pending_only = league in pending and league not in tip_slugs
        if pending_only:
            # Stub so thin_dry_run_market_rules accepts the league for cart staging.
            leagues.append(
                LeagueRow(
                    league=league,
                    sport="",
                    optic_league_id="",
                    extra_optic_league_ids=[],
                    fixture_source="api",
                    fixture_horizon_hours=96.0,
                    enabled=True,
                    output_order=[],
                    exchanges=[],
                )
            )
        rules = self.store.market_rules_for(current) if current else []  # type: ignore[attr-defined]
        payload = stamp_market_payload(league, body.rules)
        dry = thin_dry_run_market_rules(leagues, rules, payload)
        blockers = list(dry["blockers"])
        warnings = [*dry["warnings"], *absence_warnings(payload.rules)]
        if pending_only:
            warnings.append(
                f"League {league!r} is only in the staging cart — "
                "Add to cart and submit the batch (Submit alone requires tip league)."
            )
        if not body.acknowledge_shadow:
            blockers.append(ACK_RULES_WRITE)
        return {
            "ok": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "pending_league": pending_only,
            "preview": {
                "summary": f"Add {len(payload.rules)} market rule(s) to {payload.league}",
                "league_label": league_label(payload.league),
                "rule_count": len(payload.rules),
                "cards": rule_cards(payload.league, payload.rules),
            },
            "payload": payload.model_dump(mode="json"),
        }

    def entry_market_rule_submit(
        self,
        body: MarketRuleEntryRequest,
        actor: Actor,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Propose + validate mapping_market_rules from the trader form."""
        # Submit alone never trusts pending cart leagues — tip only.
        tip_body = body.model_copy(update={"pending_league_slugs": []})
        verified = self.entry_market_rule_verify(tip_body)
        if not verified["ok"]:
            current = self.store.current_rule_set_id  # type: ignore[attr-defined]
            tip_slugs = (
                {row.league for row in self.store.leagues_for(current)}  # type: ignore[attr-defined]
                if current
                else set()
            )
            if body.league.strip() not in tip_slugs:
                raise ValidationFailedError(
                    "league not on tip — add to cart with the league and submit batch",
                    reason_code="league_not_on_tip",
                    dry_run=verified,
                )
            raise ValidationFailedError(
                "market rule entry blocked",
                reason_code="entry_blocked",
                dry_run=verified,
            )
        current = self.store.current_rule_set_id  # type: ignore[attr-defined]
        if current is None:
            raise ConflictError("no current rule set", reason_code="no_rule_set")
        payload = MappingMarketRulesPayload.model_validate(verified["payload"])
        req = ProposeRequest(
            request_id=request_id or new_id("req"),
            expected_rule_set_id=current,
            artifact_type="mapping_market_rules",
            summary=f"Market rules for {payload.league}",
            evidence_refs=[f"note:{body.note}"] if body.note else [],
            payload=payload,
        )
        prop = self.propose(req, actor)  # type: ignore[attr-defined]
        self.validate(prop.proposal_id, actor)  # type: ignore[attr-defined]
        return self._review_view(self._get(prop.proposal_id))  # type: ignore[attr-defined]

    def human_rules(
        self,
        *,
        q: str | None = None,
        kind: str = "entities",
        limit: int = 100,
        offset: int = 0,
        at: str | None = None,
        league: list[str] | None = None,
        sportsbook: list[str] | None = None,
        canonical: list[str] | None = None,
        action: list[str] | None = None,
        sort: str | None = None,
        sort_dir: str = "asc",
    ) -> dict[str, Any]:
        """Searchable rules explorer without exposing rule_set_id."""
        query = parse_rules_query(
            q=q,
            kind=kind,
            limit=limit,
            offset=offset,
            at=at,
            league=league,
            sportsbook=sportsbook,
            canonical=canonical,
            action=action,
            sort=sort,
            sort_dir=sort_dir,
        )
        return search_human_rules(self.store, query)

    def rule_history(
        self,
        *,
        kind: str,
        natural_key: str | None = None,
        league: str | None = None,
        entity_type: str | None = None,
        canonical_key: str | None = None,
        sportsbook: str | None = None,
        source_key_type: str | None = None,
        source_key: str | None = None,
    ) -> dict[str, Any]:
        """On/off windows for one rule natural key (no internal ids required)."""
        return build_rule_history(
            self.store,  # type: ignore[attr-defined]
            kind=kind,
            natural_key=natural_key,
            league=league,
            entity_type=entity_type,
            canonical_key=canonical_key,
            sportsbook=sportsbook,
            source_key_type=source_key_type,
            source_key=source_key,
        )

    def list_parity(self, *, limit: int = 50) -> dict[str, Any]:
        """Recent dual-read parity audits (OK heartbeats and mismatches)."""
        events = self.store.list_parity_events(limit=limit)  # type: ignore[attr-defined]
        return {
            "count": len(events),
            "events": events,
            "latest_mismatches": latest_mismatch_rows(events),
        }

    def entry_batch_verify(self, body: BatchEntryRequest) -> dict[str, Any]:
        """Dry-run a staging cart; return signed preview_token on success."""
        current = self.store.current_rule_set_id  # type: ignore[attr-defined]
        if current is None:
            raise ConflictError("no current rule set", reason_code="no_rule_set")
        try:
            payload = stamp_batch_official(BatchChangesPayload(
                entity_aliases=body.entity_aliases,
                leagues=body.leagues,
                market_rules=body.market_rules,
            ))
        except Exception as exc:  # noqa: BLE001 — pydantic ValidationError
            raise ValidationFailedError(
                str(exc),
                reason_code="empty_batch",
                dry_run={"blockers": [str(exc)]},
            ) from exc
        dry = dry_run_batch(self.store, current, payload)  # type: ignore[arg-type]
        blockers = list(dry["blockers"])
        if not body.acknowledge_shadow:
            blockers.append(ACK_RULES_WRITE)
        refs, live_block = _batch_evidence(
            self.store,
            payload,
            body.note,
            getattr(self, "evidence_fn", None),
        )
        blockers.extend(live_block)
        summary = batch_summary(payload)
        extraction = {
            "kind": "batch_changes",
            "payload": payload.model_dump(mode="json"),
            "summary": summary,
            "note": body.note,
            "evidence_refs": refs,
        }
        ok = not blockers
        return {
            "ok": ok,
            "blockers": blockers,
            "warnings": [*dry["warnings"], *batch_absence_warnings(payload)],
            "preview": {
                "summary": summary,
                "evidence": refs,
                "cards": batch_rule_cards(payload),
            } if ok else None,
            "preview_token": sign_preview(extraction) if ok else None,
            "payload": payload.model_dump(mode="json") if ok else None,
        }

    def entry_batch_submit(self, preview_token: str, actor: Actor) -> dict[str, Any]:
        """Confirm batch preview → one compound proposal + validate."""
        if actor.role not in _WRITE_ROLES:
            raise ForbiddenError("role cannot submit")
        try:
            extraction = unsign_preview(preview_token)
        except ValueError as exc:
            raise ValidationFailedError(
                "invalid or expired preview",
                reason_code="bad_preview",
                dry_run={},
            ) from exc
        if extraction.get("kind") != "batch_changes":
            raise ValidationFailedError(
                "preview is not a batch",
                reason_code="bad_preview",
                dry_run={},
            )
        current = self.store.current_rule_set_id  # type: ignore[attr-defined]
        if current is None:
            raise ConflictError("no current rule set", reason_code="no_rule_set")
        payload = BatchChangesPayload.model_validate(extraction["payload"])
        evidence = [str(r) for r in (extraction.get("evidence_refs") or []) if r]
        if extraction.get("note"):
            evidence.append(f"note:{extraction['note']}")
        if not evidence:
            evidence = [extraction["summary"]]
        req = ProposeRequest(
            request_id=preview_request_id(preview_token),
            expected_rule_set_id=current,
            artifact_type="batch_changes",
            summary=extraction["summary"],
            evidence_refs=evidence,
            payload=payload,
        )
        prop = self.propose(req, actor)  # type: ignore[attr-defined]
        self.validate(prop.proposal_id, actor)  # type: ignore[attr-defined]
        return self._review_view(self._get(prop.proposal_id))  # type: ignore[attr-defined]

    def replace_batch_proposal(
        self,
        proposal_id: str,
        preview_token: str,
        actor: Actor,
    ) -> dict[str, Any]:
        """Write a verified batch onto an open harvest card (same ref)."""
        if actor.role not in _WRITE_ROLES:
            raise ForbiddenError("role cannot submit")
        proposal = self._get(proposal_id)  # type: ignore[attr-defined]
        if proposal.status not in OPEN_REVIEW_STATUSES:
            return self.entry_batch_submit(preview_token, actor)
        extraction = _unsigned_batch(preview_token)
        current = self.store.current_rule_set_id
        if current is None:
            raise ConflictError("no current rule set", reason_code="no_rule_set")
        self._apply_batch_amend(proposal, extraction, current, actor)
        self.validate(proposal.proposal_id, actor)  # type: ignore[attr-defined]
        return self._review_view(self._get(proposal.proposal_id))  # type: ignore[attr-defined]

    def _apply_batch_amend(
        self,
        proposal: Any,
        extraction: dict[str, Any],
        current: str,
        actor: Actor,
    ) -> None:
        payload = BatchChangesPayload.model_validate(extraction["payload"])
        evidence = [str(r) for r in (extraction.get("evidence_refs") or []) if r]
        if extraction.get("note"):
            evidence.append(f"note:{extraction['note']}")
        if not evidence:
            evidence = [str(extraction["summary"])]
        proposal.payload = payload
        proposal.summary = str(extraction["summary"])
        proposal.evidence_refs = evidence
        proposal.status = "proposed"
        proposal.candidate_rule_set_id = None
        proposal.validated_at = None
        proposal.change_groups = None
        proposal.expected_rule_set_id = current
        self.store.put_proposal(proposal)
        req = ProposeRequest(
            request_id=proposal.request_id,
            expected_rule_set_id=current,
            artifact_type="batch_changes",
            summary=proposal.summary,
            evidence_refs=evidence,
            payload=payload,
        )
        self._audit_proposed(proposal, actor, req, event_type="rule_amended")  # type: ignore[attr-defined]


def _unsigned_batch(preview_token: str) -> dict[str, Any]:
    """Decode a batch preview token or raise ValidationFailedError."""
    try:
        extraction = unsign_preview(preview_token)
    except ValueError as exc:
        raise ValidationFailedError(
            "invalid or expired preview",
            reason_code="bad_preview",
            dry_run={},
        ) from exc
    if extraction.get("kind") != "batch_changes":
        raise ValidationFailedError(
            "preview is not a batch",
            reason_code="bad_preview",
            dry_run={},
        )
    return extraction
