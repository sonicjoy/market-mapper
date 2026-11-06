"""M3b trader console ops: entry submit, review queue, human rules."""
from __future__ import annotations

from typing import Any

from mappers.control_plane.change_view import (
    headline_from_mapping_rows,
    payload_change_groups,
    refresh_alias_lines,
    totals_from_groups,
)
from mappers.control_plane.console_bulk_override_ops import ConsoleBulkOverrideOpsMixin
from mappers.control_plane.console_explore_ops import ConsoleExploreOpsMixin
from mappers.control_plane.console_mapping_rows import mapping_rows_from_proposal, payload_as_batch
from mappers.control_plane.console_mismap_ops import ConsoleMismapOpsMixin
from mappers.control_plane.console_override_ops import ConsoleOverrideOpsMixin
from mappers.control_plane.console_override_pattern_ops import ConsoleOverridePatternOpsMixin
from mappers.control_plane.console_proposed_trim import (
    closed_proposal_trim_error,
    payload_unchanged,
    trim_proposal_payload,
)
from mappers.control_plane.console_proposed_view import proposed_for_ref, proposed_leagues_view, tip_market_rules
from mappers.control_plane.console_review_history import list_review_history
from mappers.control_plane.entry import unsign_preview, verify_entry
from mappers.control_plane.entry_structured import verify_structured_alias
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    AliasPin,
    BatchChangesPayload,
    ConflictError,
    EntityAliasPayload,
    ForbiddenError,
    ProposalRecord,
    ProposeRequest,
    StructuredAliasEntryRequest,
    ValidationFailedError,
)
from mappers.control_plane.preview_token import preview_request_id
from mappers.control_plane.review_cards import build_review_view

_WRITE_ROLES = {
    ActorRole.PROPOSER,
    ActorRole.APPROVER,
    ActorRole.ADMIN,
    ActorRole.SERVICE,
}
_REVIEW_ROLES = {ActorRole.APPROVER, ActorRole.ADMIN, ActorRole.SERVICE}
_OPEN_REVIEW_STATUSES = frozenset({"proposed", "validated"})
class ConsoleOpsMixin(
    ConsoleExploreOpsMixin,
    ConsoleMismapOpsMixin,
    ConsoleOverrideOpsMixin,
    ConsoleOverridePatternOpsMixin,
    ConsoleBulkOverrideOpsMixin,
):
    """Trader-facing methods mixed into ProposalService."""

    require_maker_checker: bool

    def reject(self, proposal_id: str, actor: Actor, comment: str = "") -> dict[str, Any]:
        """Checker declines a validated proposal."""
        proposal = self._get(proposal_id)  # type: ignore[attr-defined]
        if proposal.status not in {"validated", "proposed"}:
            raise ValidationFailedError(
                "proposal cannot be rejected in this status",
                reason_code="bad_status",
                dry_run={},
            )
        service_reject = actor.role == ActorRole.SERVICE
        if (
            not service_reject
            and self.require_maker_checker
            and actor.subject == proposal.proposer_subject
        ):
            raise ForbiddenError("maker/checker: rejector must differ", reason_code="maker_checker")
        allowed = _REVIEW_ROLES | ({ActorRole.PROPOSER} if not self.require_maker_checker else set())
        if actor.role not in allowed:
            raise ForbiddenError("role cannot reject")
        proposal.status = "rejected"
        proposal.review_note = comment or None
        self.store.put_proposal(proposal)  # type: ignore[attr-defined]
        self.store.append_audit(  # type: ignore[attr-defined]
            {
                "request_id": proposal.request_id,
                "event_type": "rule_rejected",
                "proposal_id": proposal.proposal_id,
                "actor_subject": actor.subject,
                "actor_role": actor.role.value,
                "status": "rejected",
                "payload": {"comment": comment},
            }
        )
        return {"status": "rejected", "ref": proposal.proposal_id}

    def request_changes(self, proposal_id: str, actor: Actor, comment: str = "") -> dict[str, Any]:
        """Return proposal to proposer; must re-validate before approve."""
        proposal = self._get(proposal_id)  # type: ignore[attr-defined]
        if proposal.status not in {"validated", "proposed"}:
            raise ValidationFailedError(
                "proposal cannot request-changes in this status",
                reason_code="bad_status",
                dry_run={},
            )
        if self.require_maker_checker and actor.subject == proposal.proposer_subject:
            raise ForbiddenError("maker/checker violation", reason_code="maker_checker")
        allowed = _REVIEW_ROLES | ({ActorRole.PROPOSER} if not self.require_maker_checker else set())
        if actor.role not in allowed:
            raise ForbiddenError("role cannot request changes")
        proposal.status = "changes_requested"
        proposal.candidate_rule_set_id = None
        proposal.validated_at = None
        self.store.put_proposal(proposal)  # type: ignore[attr-defined]
        self.store.append_audit(  # type: ignore[attr-defined]
            {
                "request_id": proposal.request_id,
                "event_type": "rule_changes_requested",
                "proposal_id": proposal.proposal_id,
                "actor_subject": actor.subject,
                "actor_role": actor.role.value,
                "status": "changes_requested",
                "payload": {"comment": comment},
            }
        )
        return {"status": "changes_requested", "ref": proposal.proposal_id}

    def entry_verify(
        self,
        *,
        paste: str,
        provided_name: str | None,
        note: str | None,
        acknowledge_live_warning: bool,
        disambiguation_label: str | None,
        league: str | None = None,
    ) -> dict[str, Any]:
        """Trader paste verify — no rule set ids in the response."""
        rid = self.store.current_rule_set_id  # type: ignore[attr-defined]
        entities = self.store.entities_for(rid) if rid else []  # type: ignore[attr-defined]
        result = verify_entry(
            paste=paste,
            provided_name=provided_name,
            note=note,
            acknowledge_live_warning=acknowledge_live_warning,
            disambiguation_label=disambiguation_label,
            entities=entities,
            live=self.live,  # type: ignore[attr-defined]
            league=league,
            store=self.store,  # type: ignore[attr-defined]
            evidence_fn=getattr(self, "evidence_fn", None),
        )
        result.pop("_choices", None)
        return result

    def entry_alias_structured_verify(self, body: StructuredAliasEntryRequest) -> dict[str, Any]:
        """Rules-driven alias pin verify (no paste ticker)."""
        rid = self.store.current_rule_set_id  # type: ignore[attr-defined]
        entities = self.store.entities_for(rid) if rid else []  # type: ignore[attr-defined]
        return verify_structured_alias(
            league=body.league.strip(),
            sportsbook=body.sportsbook.strip(),
            alias_kind=(body.alias_kind or "code").strip(),
            alias_value=body.alias_value.strip(),
            entity_type=body.entity_type,
            canonical_key=body.canonical_key,
            provided_name=body.provided_name,
            note=body.note,
            acknowledge_shadow=body.acknowledge_shadow,
            entities=entities,
            store=self.store,  # type: ignore[attr-defined]
            evidence_fn=getattr(self, "evidence_fn", None),
            remove=bool(body.remove),
        )

    def entry_submit(self, preview_token: str, actor: Actor) -> dict[str, Any]:
        """Confirm preview → propose + validate; return opaque review ref."""
        if actor.role not in _WRITE_ROLES:
            raise ForbiddenError("role cannot submit")
        extraction = self._decode_preview(preview_token)
        current = self.store.current_rule_set_id  # type: ignore[attr-defined]
        if current is None:
            raise ConflictError("no current rule set", reason_code="no_rule_set")
        req = self._propose_from_extraction(
            extraction, current, preview_request_id(preview_token)
        )
        proposal = self.propose(req, actor)  # type: ignore[attr-defined]
        self.validate(proposal.proposal_id, actor)  # type: ignore[attr-defined]
        return self._review_view(self._get(proposal.proposal_id))  # type: ignore[attr-defined]

    @staticmethod
    def _decode_preview(preview_token: str) -> dict[str, Any]:
        """Unsign preview or raise ValidationFailedError."""
        try:
            return unsign_preview(preview_token)
        except ValueError as exc:
            raise ValidationFailedError(
                "invalid or expired preview",
                reason_code="bad_preview",
                dry_run={},
            ) from exc

    @staticmethod
    def _propose_from_extraction(
        extraction: dict[str, Any],
        current: str,
        request_id: str,
    ) -> ProposeRequest:
        """Build ProposeRequest from a verified extraction dict."""
        pin = AliasPin(
            sportsbook=extraction["sportsbook"],
            alias_kind=extraction["alias_kind"],
            alias_value=extraction["alias_value"],
            disambiguation_name=extraction.get("disambiguation_label"),
            remove=bool(extraction.get("remove")),
        )
        evidence = [f"paste:{extraction['raw_paste']}"]
        evidence.extend(str(r) for r in (extraction.get("evidence_refs") or []) if r)
        if extraction.get("note"):
            evidence.append(f"note:{extraction['note']}")
        return ProposeRequest(
            request_id=request_id,
            expected_rule_set_id=current,
            summary=extraction["summary"].replace("**", ""),
            evidence_refs=evidence,
            payload=EntityAliasPayload(
                league=extraction["league"],
                canonical_key=extraction["canonical_key"],
                entity_type=extraction["entity_type"],  # type: ignore[arg-type]
                canonical_name=extraction["canonical_name"],
                aliases=[pin],
                reassign=bool(extraction.get("reassign")),
            ),
        )

    def list_review(self) -> list[dict[str, Any]]:
        """Open review queue only (no rejected / approved / closed cards)."""
        return [
            self._review_view(p, include_changes=False)
            for p in self.store.list_proposals()  # type: ignore[attr-defined]
            if p.status in _OPEN_REVIEW_STATUSES
        ]

    def list_review_history(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Recent proposals for the console history table."""
        return list_review_history(self.store, limit=limit)  # type: ignore[attr-defined]

    def get_review(self, ref: str) -> dict[str, Any]:
        """Trader-safe review detail."""
        return self._review_view(self._get(ref), include_changes=True)  # type: ignore[attr-defined]

    def approve_review(self, ref: str, actor: Actor) -> dict[str, Any]:
        """Approve via opaque review ref."""
        result = self.approve(ref, actor)  # type: ignore[attr-defined]
        view = self._review_view(self._get(ref))  # type: ignore[attr-defined]
        view["status"] = result.status
        return view

    def reject_review(self, ref: str, actor: Actor, comment: str = "") -> dict[str, Any]:
        """Reject via opaque review ref."""
        self.reject(ref, actor, comment)
        return self._review_view(self._get(ref))  # type: ignore[attr-defined]

    def request_changes_review(self, ref: str, actor: Actor, comment: str = "") -> dict[str, Any]:
        """Request changes via opaque review ref."""
        self.request_changes(ref, actor, comment)
        return self._review_view(self._get(ref))  # type: ignore[attr-defined]

    @staticmethod
    def _human_status(status: str) -> str:
        """Map internal status to trader-facing label."""
        return {
            "proposed": "submitted",
            "validated": "waiting_for_checker",
            "approved": "approved",
            "activated": "activated",
            "rejected": "rejected",
            "changes_requested": "needs_changes",
        }.get(status, status)

    def _change_groups(self, proposal: ProposalRecord) -> dict[str, Any]:
        """Stored tip diff after validate; payload+tip fallback otherwise."""
        groups = (
            proposal.change_groups
            if proposal.change_groups
            else payload_change_groups(
                proposal.payload, tip_leagues=self._tip_leagues()
            )
        )
        return refresh_alias_lines(groups, proposal.payload)

    def _tip_leagues(self) -> list[Any]:
        """Current tip league rows for add-vs-update fallback (no entities)."""
        current = self.store.current_rule_set_id  # type: ignore[attr-defined]
        if not current:
            return []
        return list(self.store.leagues_for(current))  # type: ignore[attr-defined]

    def _review_view(
        self,
        proposal: ProposalRecord,
        *,
        include_changes: bool = True,
    ) -> dict[str, Any]:
        """Strip internal ids from a proposal for the console."""
        groups = self._change_groups(proposal)
        view = build_review_view(
            proposal,
            status=self._human_status(proposal.status),
            changes=totals_from_groups(groups),
            change_groups=groups,
        )
        if not include_changes:
            view["changes"] = None
            view["change_groups"] = None
        tip = {row.league: row for row in self._tip_leagues()}
        batch = payload_as_batch(proposal.payload)
        new_leagues = {lg.league for lg in batch.leagues if lg.league not in tip} if batch else set()
        mappings = mapping_rows_from_proposal(
            proposal,
            groups=groups,
            tip_leagues=tip,
            new_leagues=new_leagues,
            tip_market_rules=tip_market_rules(self.store),  # type: ignore[attr-defined]
        ) if batch is not None else []
        if include_changes and batch is not None:
            view["proposed"] = proposed_for_ref(
                self.store,  # type: ignore[attr-defined]
                proposal,
                groups=groups,
            )
            mappings = list(view["proposed"]["rows"])
        view["mappings"] = mappings
        if mappings:
            view["headline"] = headline_from_mapping_rows(mappings)
        return view

    def console_proposed_leagues(self, *, ref: str | None = None) -> dict[str, Any]:
        """Flatten open proposals into unique mapping rows for the rail."""
        if ref:
            proposal = self._get(ref)  # type: ignore[attr-defined]
            return proposed_for_ref(
                self.store,  # type: ignore[attr-defined]
                proposal,
                groups=self._change_groups(proposal),
            )
        open_props = [
            p
            for p in self.store.list_proposals()  # type: ignore[attr-defined]
            if p.status in _OPEN_REVIEW_STATUSES
        ]
        groups_by_id: dict[str, dict[str, Any] | None] = {
            p.proposal_id: self._change_groups(p) for p in open_props
        }
        return proposed_leagues_view(
            self.store,  # type: ignore[attr-defined]
            open_props,
            groups_by_id=groups_by_id,
        )

    def console_trim_proposed(
        self,
        ref: str,
        drops: list[dict[str, str]],
        actor: Actor,
    ) -> dict[str, Any]:
        """Drop items from a batch proposal and re-validate."""
        if actor.role not in _WRITE_ROLES:
            raise ForbiddenError("role cannot trim proposal")
        proposal = self._get(ref)  # type: ignore[attr-defined]
        if proposal.status not in _OPEN_REVIEW_STATUSES:
            raise closed_proposal_trim_error(proposal.status, proposal.review_note)
        if not isinstance(proposal.payload, BatchChangesPayload):
            raise ValidationFailedError(
                "only batch_changes proposals support item trim",
                reason_code="not_batch",
                dry_run={},
            )
        tip_slugs = {row.league for row in self._tip_leagues()}
        try:
            trimmed = trim_proposal_payload(proposal, drops, tip_league_slugs=tip_slugs,
                tip_market_rules=tip_market_rules(self.store))  # type: ignore[attr-defined]
        except ValidationFailedError as exc:
            if exc.reason_code == "empty_batch":
                self.reject(ref, actor, comment="all items dropped")
                view = self._review_view(self._get(ref), include_changes=True)  # type: ignore[attr-defined]
                view["status"] = "rejected"
                return view
            raise
        if payload_unchanged(proposal.payload, trimmed) and proposal.status == "validated":
            return self._review_view(proposal, include_changes=True)  # type: ignore[attr-defined]
        if not payload_unchanged(proposal.payload, trimmed):
            proposal.payload = trimmed
            proposal.candidate_rule_set_id = None
            proposal.validated_at = None
            proposal.status = "proposed"
            proposal.change_groups = None
            self.store.put_proposal(proposal)  # type: ignore[attr-defined]
        self.validate(ref, actor)  # type: ignore[attr-defined]
        return self._review_view(self._get(ref), include_changes=True)  # type: ignore[attr-defined]
