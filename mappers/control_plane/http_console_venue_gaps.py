"""Console HTTP routes for Explore → Venue gaps."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel, Field

from mappers.control_plane.console_venue_gaps_sql import clear_venue_gap_cache
from mappers.control_plane.service import ProposalService

# ruff: noqa: B008


class VenueGapLegRow(BaseModel):
    """One catalogue selection the page sends back for Why / stage."""

    key: str
    description: str | None = None
    league: str | None = None
    fixture: str | None = None
    sport: str | None = None
    contract_type: str | None = None
    market_group: str | None = None


class VenueGapWhyBody(BaseModel):
    """Why request: the node's sampled selections."""

    platform: str = "crypto"
    rows: list[VenueGapLegRow] = Field(default_factory=list)


class VenueGapStageBody(VenueGapWhyBody):
    """Stage request: sampled selections plus the chosen item ids."""

    item_ids: list[str] = Field(default_factory=list)


def _rows(body: VenueGapWhyBody) -> list[dict[str, Any]]:
    """Pydantic rows → plain dicts for the service layer."""
    return [row.model_dump() for row in body.rows]


def register_venue_gap_routes(
    app: FastAPI,
    *,
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    """Attach /console/venue-gaps* routes."""
    _register_reads(app, service=service, call=call)
    _register_actions(app, service=service, call=call)


def _register_reads(
    app: FastAPI,
    *,
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    """GET rollup and fixture drill-down."""

    @app.get("/console/venue-gaps", tags=["console"])
    def console_venue_gaps(
        platform: str = "crypto",
        phase: str = "live",
        q: str | None = None,
        kickoff_from: str | None = None,
        kickoff_to: str | None = None,
        market: list[str] | None = Query(default=None),
        refresh: bool = False,
        control: ProposalService = Depends(service),
    ) -> Any:
        """Venue catalogue vs market_mapping: league x fixture rollup."""
        if refresh:
            clear_venue_gap_cache()
        return call(
            lambda: control.console_venue_gaps(
                platform=platform,
                phase=phase,
                q=q,
                kickoff_from=kickoff_from,
                kickoff_to=kickoff_to,
                markets=market,
            )
        )

    @app.get("/console/venue-gaps/fixture", tags=["console"])
    def console_venue_gap_fixture(
        fixture_key: str,
        platform: str = "crypto",
        control: ProposalService = Depends(service),
    ) -> Any:
        """Markets and selections for one catalogue fixture."""
        return call(lambda: control.console_venue_gap_fixture(platform=platform, fixture_key=fixture_key))


def _register_actions(
    app: FastAPI,
    *,
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    """POST Why and stage for one node."""

    @app.post("/console/venue-gaps/why", tags=["console"])
    def console_venue_gap_why(
        body: VenueGapWhyBody,
        control: ProposalService = Depends(service),
    ) -> Any:
        """Rules that would map a node, drafted from its sampled selections."""
        return call(lambda: control.console_venue_gap_why(rows=_rows(body)))

    @app.post("/console/venue-gaps/stage", tags=["console"])
    def console_venue_gap_stage(
        body: VenueGapStageBody,
        control: ProposalService = Depends(service),
    ) -> Any:
        """Cart items for the selected rules of one node."""
        return call(lambda: control.console_venue_gap_stage(rows=_rows(body), item_ids=body.item_ids))
