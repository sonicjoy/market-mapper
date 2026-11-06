"""Console HTTP routes for Explore -> Override patterns."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from mappers.control_plane.models import Actor
from mappers.control_plane.override_clusters import DEFAULT_MIN_GAMES
from mappers.control_plane.override_clusters_sql import clear_override_cache
from mappers.control_plane.service import ProposalService

# ruff: noqa: B008


class OverridePatternStageBody(BaseModel):
    """Stage request: the cluster to turn into a rule proposal."""

    cluster_id: str
    acknowledge_shadow: bool = False


def register_override_pattern_routes(
    app: FastAPI,
    *,
    authenticated_actor: Callable[..., Actor],
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    """Attach /console/override-patterns* routes."""

    @app.get("/console/override-patterns", tags=["console"])
    def console_override_patterns(
        min_games: int = DEFAULT_MIN_GAMES,
        include_inactive: bool = False,
        kind: str | None = None,
        refresh: bool = False,
        control: ProposalService = Depends(service),
    ) -> Any:
        """Repeated overrides grouped into market-rule / alias candidates."""
        if refresh:
            clear_override_cache()
        return call(
            lambda: control.console_override_patterns(
                min_games=min_games,
                include_inactive=include_inactive,
                kind=kind,
            )
        )

    @app.post("/console/override-patterns/stage", tags=["console"])
    def console_override_pattern_stage(
        body: OverridePatternStageBody,
        control: ProposalService = Depends(service),
        actor: Actor = Depends(authenticated_actor),
    ) -> Any:
        """Draft one cluster's rule and submit it to Proposed (human Approve)."""
        return call(
            lambda: control.console_override_pattern_stage(
                body.cluster_id, actor, acknowledge_shadow=body.acknowledge_shadow
            )
        )
