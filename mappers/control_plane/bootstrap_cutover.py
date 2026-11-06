"""Bootstrap cutover: emit control-plane proposals instead of TOML writes."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.models import (
    Actor,
    ActorRole,
    AliasPin,
    EntityAliasPayload,
    ProposeRequest,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import new_id


def propose_alias_pin(
    service: ProposalService,
    *,
    league: str,
    canonical_key: str,
    canonical_name: str | None,
    sportsbook: str,
    alias_kind: str,
    alias_value: str,
    evidence: str,
    actor_subject: str = "bootstrap-service",
) -> dict[str, Any]:
    """Propose+validate an entity_alias when bootstrap cutover is on."""
    current = service.store.current_rule_set_id
    if current is None:
        return {"ok": False, "reason": "no_rule_set"}
    actor = Actor(subject=actor_subject, role=ActorRole.SERVICE)
    req = ProposeRequest(
        request_id=new_id("req"),
        expected_rule_set_id=current,
        artifact_type="entity_alias",
        summary=f"Bootstrap pin {sportsbook} {alias_value} → {canonical_key}",
        evidence_refs=[evidence],
        payload=EntityAliasPayload(
            league=league,
            canonical_key=canonical_key,
            canonical_name=canonical_name,
            aliases=[
                AliasPin(
                    sportsbook=sportsbook,
                    alias_kind=alias_kind,
                    alias_value=alias_value,
                )
            ],
        ),
    )
    prop = service.propose(req, actor)
    service.validate(prop.proposal_id, actor)
    return {"ok": True, "proposal_id": prop.proposal_id}
