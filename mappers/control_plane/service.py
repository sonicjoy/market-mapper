"""Propose → validate → approve → (test) activate for entity_alias."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from mappers.control_plane.artifact_apply import (
    build_candidate_slices,
    dry_run_proposal,
    payload_league,
    payload_sportsbook,
)
from mappers.control_plane.change_view import snapshot_change_groups
from mappers.control_plane.console_ops import ConsoleOpsMixin
from mappers.control_plane.dry_run import failed_dry_run_message
from mappers.control_plane.entry import LiveLookup, NullLiveLookup
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    ApproveResponse,
    ConflictError,
    ForbiddenError,
    ProposalRecord,
    ProposeRequest,
    ValidateResponse,
    ValidationFailedError,
)
from mappers.control_plane.ops_extended import ExtendedOpsMixin
from mappers.control_plane.ops_suggest import SuggestOpsMixin
from mappers.control_plane.store import ProposalStore, new_id

logger = logging.getLogger(__name__)

_WRITE_ROLES = {
    ActorRole.PROPOSER,
    ActorRole.APPROVER,
    ActorRole.ADMIN,
    ActorRole.SERVICE,
}
_APPROVE_ROLES = {ActorRole.APPROVER, ActorRole.ADMIN, ActorRole.SERVICE}


def _slice_count(
    applied: list[Any] | None,
    from_receipt: int | None,
    load: Callable[[str], list[Any]],
    rule_set_id: str,
) -> int:
    """Prefer the applied slice, then the receipt count, then a coalesce."""
    if applied is not None:
        return len(applied)
    if from_receipt is not None:
        return from_receipt
    return len(load(rule_set_id))


def _candidate_groups(
    store: ProposalStore,
    current: str,
    entities: list[Any] | None,
    leagues: list[Any] | None,
    market_rules: list[Any] | None,
) -> dict[str, Any]:
    """Tip vs candidate change groups (parent already coalesced at insert)."""
    parent_ent = store.entities_for(current)
    parent_lg = store.leagues_for(current)
    parent_mr = store.market_rules_for(current)
    return snapshot_change_groups(
        parent_ent,
        entities if entities is not None else parent_ent,
        parent_lg,
        leagues if leagues is not None else parent_lg,
        parent_mr,
        market_rules if market_rules is not None else parent_mr,
    )


class ProposalService(ExtendedOpsMixin, SuggestOpsMixin, ConsoleOpsMixin):
    """M3a/M3b control-plane service (in-memory / testable)."""

    def __init__(
        self,
        store: ProposalStore,
        live: LiveLookup | None = None,
        evidence_fn: Any = None,
        *,
        require_maker_checker: bool = False,
    ) -> None:
        """Bind to a store; maker/checker off by default for solo operators."""
        self.store = store
        self.live = live or NullLiveLookup()
        self.evidence_fn = evidence_fn
        self.require_maker_checker = require_maker_checker

    def _current_tip(self) -> str:
        """Return the live tip or raise when none is activated/seeded."""
        current = self.store.current_rule_set_id
        if current is None:
            raise ConflictError("no current rule set", reason_code="no_rule_set")
        return current

    def _require_current(self, expected: str) -> str:
        """Raise ConflictError when expected_rule_set_id is stale."""
        current = self._current_tip()
        if expected != current:
            raise ConflictError(
                f"expected_rule_set_id {expected!r} != current {current!r}",
                reason_code="stale_rule_set",
            )
        return current

    def _rebase_if_stale(self, proposal: ProposalRecord, actor: Actor) -> ProposalRecord:
        """Rebuild the candidate on the live tip when expected_rule_set_id is stale."""
        current = self._current_tip()
        if proposal.expected_rule_set_id == current:
            return proposal
        dry = dry_run_proposal(self.store, current, proposal)
        if not dry["ok"]:
            self._audit_validated(proposal, actor, current, None, dry, failed=True)
            raise ValidationFailedError(
                failed_dry_run_message(dry), reason_code="dry_run_failed", dry_run=dry
            )
        proposal.expected_rule_set_id = current
        self._commit_validation(proposal, actor, current, dry)
        return proposal

    def propose(self, req: ProposeRequest, actor: Actor) -> ProposalRecord:
        """Create (or idempotently return) an entity_alias proposal."""
        if actor.role not in _WRITE_ROLES:
            raise ForbiddenError("role cannot propose")
        existing = self.store.get_proposal_by_request(req.request_id)
        if existing is not None:
            if self._proposal_request(existing) != req:
                raise ConflictError(
                    "request_id already used with different payload",
                    reason_code="idempotency_mismatch",
                )
            return existing
        self._require_current(req.expected_rule_set_id)
        if req.artifact_type != req.payload.kind:
            raise ValidationFailedError(
                "artifact_type must match payload.kind",
                reason_code="artifact_mismatch",
                dry_run={},
            )
        proposal = ProposalRecord(
            proposal_id=new_id("prop"),
            request_id=req.request_id,
            status="proposed",
            expected_rule_set_id=req.expected_rule_set_id,
            artifact_type=req.artifact_type,
            summary=req.summary,
            evidence_refs=list(req.evidence_refs),
            work_item_id=req.work_item_id,
            payload=req.payload,
            proposer_subject=actor.subject,
        )
        self.store.put_proposal(proposal)
        self._audit_proposed(proposal, actor, req)
        return proposal

    @staticmethod
    def _proposal_request(proposal: ProposalRecord) -> ProposeRequest:
        """Rebuild the idempotent request represented by a proposal."""
        return ProposeRequest(
            request_id=proposal.request_id,
            expected_rule_set_id=proposal.expected_rule_set_id,
            artifact_type=proposal.payload.kind,  # type: ignore[arg-type]
            summary=proposal.summary,
            evidence_refs=proposal.evidence_refs,
            work_item_id=proposal.work_item_id,
            payload=proposal.payload,
        )

    def _audit_proposed(
        self,
        proposal: ProposalRecord,
        actor: Actor,
        req: ProposeRequest,
        *,
        event_type: str = "rule_proposed",
    ) -> None:
        """Emit rule_proposed (or rule_amended) audit event."""
        self.store.append_audit(
            {
                "request_id": req.request_id,
                "event_type": event_type,
                "proposal_id": proposal.proposal_id,
                "expected_rule_set_id": req.expected_rule_set_id,
                "artifact_type": req.artifact_type,
                "actor_subject": actor.subject,
                "actor_role": actor.role.value,
                "status": "proposed",
                "league": payload_league(req.payload),
                "sportsbook": payload_sportsbook(req.payload),
                "payload": req.model_dump(mode="json"),
            }
        )

    def validate(self, proposal_id: str, actor: Actor) -> ValidateResponse:
        """Build candidate rule set + thin dry-run; fail closed on dry-run."""
        if actor.role == ActorRole.VIEWER:
            raise ForbiddenError("viewer cannot validate")
        proposal = self._get(proposal_id)
        current = self._require_current(proposal.expected_rule_set_id)
        dry = dry_run_proposal(self.store, current, proposal)
        if not dry["ok"]:
            self._audit_validated(proposal, actor, current, None, dry, failed=True)
            raise ValidationFailedError(
                failed_dry_run_message(dry), reason_code="dry_run_failed", dry_run=dry,
            )
        return self._commit_validation(proposal, actor, current, dry)

    def _commit_validation(
        self,
        proposal: ProposalRecord,
        actor: Actor,
        current: str,
        dry: dict[str, Any],
    ) -> ValidateResponse:
        """Persist candidate snapshot after a successful dry-run."""
        entities, leagues, market_rules = build_candidate_slices(self.store, current, proposal)
        receipt = self.store.insert_candidate(
            parent_rule_set_id=current,
            proposal_id=proposal.proposal_id,
            entities=entities,
            leagues=leagues,
            market_rules=market_rules,
        )
        groups = _candidate_groups(self.store, current, entities, leagues, market_rules)
        self._stamp_validated(proposal, actor, current, dry, receipt, groups)
        return self._validate_ok(receipt, dry, entities, leagues, market_rules)

    def _stamp_validated(
        self,
        proposal: ProposalRecord,
        actor: Actor,
        current: str,
        dry: dict[str, Any],
        receipt: Any,
        groups: dict[str, Any],
    ) -> None:
        """Write validated proposal + audit after a candidate insert."""
        proposal.status = "validated"
        proposal.candidate_rule_set_id = receipt.rule_set_id
        proposal.validated_at = receipt.snapshot_sha256
        proposal.change_summary = receipt.change_summary
        proposal.change_groups = groups
        self.store.put_proposal(proposal)
        self._audit_validated(
            proposal,
            actor,
            current,
            receipt.rule_set_id,
            dry,
            changes=receipt.change_summary,
            change_groups=groups,
        )

    def _validate_ok(
        self,
        receipt: Any,
        dry: dict[str, Any],
        entities: list[Any] | None,
        leagues: list[Any] | None,
        market_rules: list[Any] | None,
    ) -> ValidateResponse:
        """Build the validate response from the candidate receipt."""
        rid = receipt.rule_set_id
        return ValidateResponse(
            status="validated",
            candidate_rule_set_id=rid,
            snapshot_sha256=receipt.snapshot_sha256,
            integrity={
                "entity_count": _slice_count(
                    entities, receipt.entity_count, self.store.entities_for, rid
                ),
                "league_count": _slice_count(
                    leagues, receipt.league_count, self.store.leagues_for, rid
                ),
                "market_rule_count": _slice_count(
                    market_rules, receipt.market_rule_count, self.store.market_rules_for, rid
                ),
            },
            dry_run=dry,
        )

    def _audit_validated(
        self,
        proposal: ProposalRecord,
        actor: Actor,
        current: str,
        candidate_id: str | None,
        dry: dict[str, Any],
        *,
        failed: bool = False,
        changes: dict[str, int] | None = None,
        change_groups: dict[str, Any] | None = None,
    ) -> None:
        """Emit rule_validated audit (success or failure)."""
        self.store.append_audit(
            {
                "request_id": proposal.request_id,
                "event_type": "rule_validated",
                "proposal_id": proposal.proposal_id,
                "rule_set_id": candidate_id,
                "previous_rule_set_id": current,
                "expected_rule_set_id": proposal.expected_rule_set_id,
                "actor_subject": actor.subject,
                "actor_role": actor.role.value,
                "artifact_type": proposal.artifact_type,
                "league": payload_league(proposal.payload),
                "status": "failed" if failed else "validated",
                "reason_code": "dry_run_failed" if failed else None,
                "payload": {
                    "dry_run": dry,
                    "changes": changes,
                    "change_groups": change_groups,
                },
            }
        )

    def approve(self, proposal_id: str, actor: Actor) -> ApproveResponse:
        """Maker/checker approve; auto-activates when allow_activate is set."""
        proposal = self._require_validated(proposal_id, actor)
        proposal = self._rebase_if_stale(proposal, actor)
        self._require_current(proposal.expected_rule_set_id)
        proposal.status = "approved"
        self.store.put_proposal(proposal)
        self.store.append_audit(
            {
                "request_id": proposal.request_id,
                "event_type": "rule_approved",
                "proposal_id": proposal.proposal_id,
                "rule_set_id": proposal.candidate_rule_set_id,
                "expected_rule_set_id": proposal.expected_rule_set_id,
                "actor_subject": actor.subject,
                "actor_role": actor.role.value,
                "artifact_type": proposal.artifact_type,
                "league": payload_league(proposal.payload),
                "status": "approved",
            }
        )
        if actor.role == ActorRole.SERVICE:
            return self._activate(proposal, actor)
        if self.store.allow_activate:
            service = Actor(subject="control-plane-service", role=ActorRole.SERVICE)
            return self._activate(proposal, service)
        return ApproveResponse(status="approved", proposal_id=proposal.proposal_id)

    def _require_validated(self, proposal_id: str, actor: Actor) -> ProposalRecord:
        """Load proposal and enforce approve preconditions."""
        proposal = self._get(proposal_id)
        if proposal.status != "validated":
            raise ValidationFailedError(
                "proposal must be validated before approve",
                reason_code="not_validated",
                dry_run={},
            )
        if self.require_maker_checker and actor.subject == proposal.proposer_subject:
            raise ForbiddenError(
                "maker/checker: approver must differ from proposer",
                reason_code="maker_checker",
            )
        allowed = _APPROVE_ROLES | ({ActorRole.PROPOSER} if not self.require_maker_checker else set())
        if actor.role not in allowed:
            raise ForbiddenError("role cannot approve")
        if proposal.candidate_rule_set_id is None:
            raise ValidationFailedError(
                "missing candidate_rule_set_id",
                reason_code="not_validated",
                dry_run={},
            )
        return proposal

    def _activate(self, proposal: ProposalRecord, actor: Actor) -> ApproveResponse:
        """Append rule_set_activated (service-only, when allow_activate)."""
        if actor.role != ActorRole.SERVICE:
            raise ForbiddenError(
                "only service may append rule_set_activated",
                reason_code="service_only_activate",
            )
        if not self.store.allow_activate:
            raise ForbiddenError(
                "activation disabled",
                reason_code="activate_disabled",
            )
        candidate = proposal.candidate_rule_set_id
        if candidate is None:
            raise ValidationFailedError(
                "missing candidate_rule_set_id",
                reason_code="not_validated",
                dry_run={},
            )
        previous = self.store.current_rule_set_id
        self.store.activate(candidate)
        proposal.status = "activated"
        proposal.activated_rule_set_id = candidate
        self.store.put_proposal(proposal)
        try:
            from mappers.control_plane.pipeline_gap_propose import record_league_reopen

            record_league_reopen(candidate, proposal)
        except Exception:
            logger.exception("gap ledger league reopen failed tip=%s", candidate)
        self.store.append_audit(
            {
                "request_id": proposal.request_id,
                "event_type": "rule_set_activated",
                "proposal_id": proposal.proposal_id,
                "rule_set_id": candidate,
                "previous_rule_set_id": previous,
                "expected_rule_set_id": proposal.expected_rule_set_id,
                "actor_subject": actor.subject,
                "actor_role": actor.role.value,
                "artifact_type": proposal.artifact_type,
                "league": payload_league(proposal.payload),
                "status": "activated",
            }
        )
        return ApproveResponse(
            status="activated",
            proposal_id=proposal.proposal_id,
            activated_rule_set_id=candidate,
        )

    def _get(self, proposal_id: str) -> ProposalRecord:
        """Fetch proposal or raise KeyError."""
        proposal = self.store.get_proposal(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        return proposal

    def get_proposal(self, proposal_id: str) -> ProposalRecord:
        """GET /proposals/{id}."""
        return self._get(proposal_id)

    def list_proposals(self) -> list[ProposalRecord]:
        """GET /proposals."""
        return self.store.list_proposals()

    def list_rules(self, *, at: str | None = None) -> dict[str, Any]:
        """GET /rules — latest shadow/activated entities (optional as-of)."""
        rid = (
            self.store.rule_set_as_of(at)  # type: ignore[attr-defined]
            if at
            else self.store.current_rule_set_id
        )
        if rid is None:
            return {"rule_set_id": None, "entities": []}
        return {
            "rule_set_id": rid,
            "entities": [e.__dict__ for e in self.store.entities_for(rid)],
        }

    def diff_rule_set(self, rule_set_id: str) -> dict[str, Any]:
        """GET /rule-sets/{id}/diff vs parent."""
        receipt = self.store.get_receipt(rule_set_id)
        if receipt is None:
            raise KeyError(rule_set_id)
        parent_id = receipt.parent_rule_set_id
        parent = self.store.entities_for(parent_id) if parent_id else []
        child = self.store.entities_for(rule_set_id)
        parent_by_key = {(e.league, e.entity_type, e.canonical_key): e for e in parent}
        child_by_key = {(e.league, e.entity_type, e.canonical_key): e for e in child}
        parent_keys = {(e.league, e.entity_type, e.canonical_key) for e in parent}
        child_keys = {(e.league, e.entity_type, e.canonical_key) for e in child}
        modified_keys = [key for key in parent_keys & child_keys if parent_by_key[key] != child_by_key[key]]
        return {
            "rule_set_id": rule_set_id,
            "parent_rule_set_id": parent_id,
            "added": [e.__dict__ for e in child if (e.league, e.entity_type, e.canonical_key) not in parent_keys],
            "removed": [e.__dict__ for e in parent if (e.league, e.entity_type, e.canonical_key) not in child_keys],
            "modified": [
                {
                    "before": parent_by_key[key].__dict__,
                    "after": child_by_key[key].__dict__,
                }
                for key in sorted(modified_keys)
            ],
            "child_entity_count": len(child),
            "parent_entity_count": len(parent),
        }
