"""Console HTTP routes for bulk override (mmmapper#21). Gated like Catalog (``catalog_enabled``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from mappers.control_plane.models import Actor
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings

# ruff: noqa: B008


class BulkLeg(BaseModel):
    """One venue selection the page sends back for drafting."""

    source_market_id: str
    source_selection_id: str = ""
    code: str = ""
    name: str = ""
    line: float | None = None


class BulkDraftBody(BaseModel):
    """Draft request: the event's legs and the Optic market(s) to pair them with."""

    sportsbook: str = "Kalshi"
    league: str | None = None
    game_id: str
    market_id: str
    no_market_id: str | None = None
    legs: list[BulkLeg] = Field(default_factory=list)


class BulkPair(BaseModel):
    """One confirmed venue selection -> Optic selection."""

    source_market_id: str
    source_selection_id: str = ""
    game_id: str
    market_id: str
    selection: str
    selection_line: str = ""
    points: float = 0.0
    selection_points: float = 0.0
    grouping_key: str = "default"


class BulkPublishBody(BaseModel):
    """Publish request: confirmed pairs plus one reason for the whole batch."""

    sportsbook: str
    reason: str
    pairs: list[BulkPair] = Field(default_factory=list)


def _require_catalog(settings: Settings = Depends(get_settings)) -> Settings:
    """404 when the Catalog / override surface is switched off."""
    if not settings.catalog_enabled:
        raise HTTPException(status_code=404, detail={"reason_code": "catalog_disabled"})
    return settings


def register_bulk_override_routes(
    app: FastAPI,
    *,
    authenticated_actor: Callable[..., Actor],
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    """Attach /console/bulk-override/* routes."""
    _register_reads(app, service=service, call=call)
    _register_writes(app, authenticated_actor=authenticated_actor, service=service, call=call)


def _register_reads(app: FastAPI, *, service: Callable[..., ProposalService], call: Callable[..., Any]) -> None:
    """GET legs, Optic fixtures, Optic markets, batch status."""

    @app.get("/console/bulk-override/legs", tags=["console"])
    def bulk_override_legs(
        event: str,
        sportsbook: str = "kalshi",
        control: ProposalService = Depends(service),
        _: Settings = Depends(_require_catalog),
    ) -> Any:
        """Unmapped selections of one venue event."""
        return call(lambda: control.console_bulk_override_legs(sportsbook=sportsbook, event=event))

    @app.get("/console/bulk-override/optic-fixtures", tags=["console"])
    def bulk_override_fixtures(
        q: str = "",
        day: str = "",
        control: ProposalService = Depends(service),
        _: Settings = Depends(_require_catalog),
    ) -> Any:
        """Optic fixtures in the rank window by team name / day."""
        return call(lambda: control.console_bulk_override_fixtures(q=q, day=day))

    @app.get("/console/bulk-override/optic-markets", tags=["console"])
    def bulk_override_markets(
        game_id: str,
        control: ProposalService = Depends(service),
        _: Settings = Depends(_require_catalog),
    ) -> Any:
        """Priced Optic markets and selections for one game."""
        return call(lambda: control.console_bulk_override_markets(game_id=game_id))

    @app.get("/console/bulk-override/batches/{batch_id}", tags=["console"])
    def bulk_override_batch(
        batch_id: str,
        control: ProposalService = Depends(service),
        _: Settings = Depends(_require_catalog),
    ) -> Any:
        """Batch header and per-pair override job status."""
        return call(lambda: control.console_bulk_override_batch(batch_id))


def _register_writes(
    app: FastAPI,
    *,
    authenticated_actor: Callable[..., Actor],
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    """POST draft (no writes) and publish."""

    @app.post("/console/bulk-override/draft", tags=["console"])
    def bulk_override_draft(
        body: BulkDraftBody,
        control: ProposalService = Depends(service),
        _: Settings = Depends(_require_catalog),
    ) -> Any:
        """Propose venue -> Optic pairs; nothing is published."""
        return call(lambda: control.console_bulk_override_draft(body.model_dump()))

    @app.post("/console/bulk-override/publish", tags=["console"])
    def bulk_override_publish(
        body: BulkPublishBody,
        control: ProposalService = Depends(service),
        actor: Actor = Depends(authenticated_actor),
        _: Settings = Depends(_require_catalog),
    ) -> Any:
        """Publish confirmed pairs as mapping_override rows and propagate them as one batch."""
        return call(lambda: control.console_bulk_override_publish(body.model_dump(), actor))
