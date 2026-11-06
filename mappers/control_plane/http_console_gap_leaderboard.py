"""Console HTTP route for Explore -> Gap leaderboard."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, Query

from mappers.control_plane.console_gap_leaderboard import list_gap_leaderboard
from mappers.control_plane.console_gap_leaderboard_sql import DEFAULT_WINDOW_HOURS, clear_leaderboard_cache
from mappers.control_plane.service import ProposalService

# ruff: noqa: B008


def register_gap_leaderboard_routes(
    app: FastAPI,
    *,
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    """Attach GET /console/gap-leaderboard."""

    @app.get("/console/gap-leaderboard", tags=["console"])
    def console_gap_leaderboard(
        hours: int = DEFAULT_WINDOW_HOURS,
        platform: list[str] | None = Query(default=None),
        market: list[str] | None = Query(default=None),
        kickoff_from: str | None = None,
        kickoff_to: str | None = None,
        sort: str = "demand",
        refresh: bool = False,
        control: ProposalService = Depends(service),
    ) -> Any:
        """Every venue's mapping gaps: platform -> league -> fixture -> market, ranked."""
        if refresh:
            clear_leaderboard_cache()
        return call(
            lambda: list_gap_leaderboard(
                hours=hours,
                platforms=platform,
                markets=market,
                kickoff_from=kickoff_from,
                kickoff_to=kickoff_to,
                sort=sort,
                store=getattr(control, "store", None),
            )
        )
