"""Console HTTP routes for Explore -> Mapping risk (mmmapper#23)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from mappers.control_plane.console_mismap import clear_mismap_cache
from mappers.control_plane.models import Actor
from mappers.control_plane.service import ProposalService

# ruff: noqa: B008


class MismapFlagBody(BaseModel):
    """Flag request: the scored row as the page shows it, plus why."""

    row: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


class MismapResolveBody(BaseModel):
    """Resolve request: which mapping, and how it was settled."""

    fingerprint: str
    note: str = ""


def register_mismap_routes(
    app: FastAPI,
    *,
    authenticated_actor: Callable[..., Actor],
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    """Attach /console/mapping-risk* routes."""
    _register_list(app, service=service, call=call)
    _register_flags(app, authenticated_actor=authenticated_actor, service=service, call=call)


def _register_list(app: FastAPI, *, service: Callable[..., ProposalService], call: Callable[..., Any]) -> None:
    """GET the scored list."""

    @app.get("/console/mapping-risk", tags=["console"])
    def console_mapping_risk(
        platform: str | None = None,
        tier: str | None = None,
        reason: str | None = None,
        q: str | None = None,
        kickoff_from: str | None = None,
        kickoff_to: str | None = None,
        flagged: bool = False,
        limit: int = 100,
        offset: int = 0,
        refresh: bool = False,
        control: ProposalService = Depends(service),
    ) -> Any:
        """Live mappings scored for mismapping risk, riskiest first."""
        if refresh:
            clear_mismap_cache()
        filters = {
            "platform": platform,
            "tier": tier,
            "reason": reason,
            "q": q,
            "kickoff_from": kickoff_from,
            "kickoff_to": kickoff_to,
            "flagged": flagged,
            "limit": limit,
            "offset": offset,
        }
        return call(lambda: control.console_mapping_risk(**filters))


def _register_flags(
    app: FastAPI,
    *,
    authenticated_actor: Callable[..., Actor],
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    """POST flag and resolve (writers only; enforced in console_mismap)."""

    @app.post("/console/mapping-risk/flag", tags=["console"])
    def console_mapping_risk_flag(
        body: MismapFlagBody,
        control: ProposalService = Depends(service),
        actor: Actor = Depends(authenticated_actor),
    ) -> Any:
        """Flag one mapping as an error (who / why / when); does not un-map it."""
        return call(lambda: control.console_mapping_risk_flag(body.row, body.note, actor))

    @app.post("/console/mapping-risk/resolve", tags=["console"])
    def console_mapping_risk_resolve(
        body: MismapResolveBody,
        control: ProposalService = Depends(service),
        actor: Actor = Depends(authenticated_actor),
    ) -> Any:
        """Close a mapping flag with its resolution."""
        return call(lambda: control.console_mapping_risk_resolve(body.fingerprint, body.note, actor))
