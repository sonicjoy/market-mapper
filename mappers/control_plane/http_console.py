"""Console HTTP routes extracted from app.py for size guard."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from mappers.control_plane.http_console_bulk_override import register_bulk_override_routes
from mappers.control_plane.http_console_gap_leaderboard import register_gap_leaderboard_routes
from mappers.control_plane.http_console_mismap import register_mismap_routes
from mappers.control_plane.http_console_override_patterns import register_override_pattern_routes
from mappers.control_plane.http_console_venue_gaps import register_venue_gap_routes
from mappers.control_plane.models import Actor
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings

# ruff: noqa: B008


class ProposedTrimBody(BaseModel):
    drop: list[dict[str, str]] = Field(default_factory=list)


def register_console_routes(
    app: FastAPI,
    *,
    authenticated_actor: Callable[..., Actor],
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    """Attach console routes onto the FastAPI app.

    M5: /console/parity* and reseed HTTP endpoints are removed. reseed_job
    remains importable for tests (prod still forbidden at the job layer).
    """
    _register_rules(app, service=service, call=call)
    _register_proposed(app, authenticated_actor=authenticated_actor, service=service, call=call)
    _register_coverage(app, service=service, call=call)
    _register_missing(app, service=service, call=call)
    _register_unmapped(app, service=service, call=call)
    _register_unmapped_actions(app, service=service, call=call)
    register_venue_gap_routes(app, service=service, call=call)
    register_gap_leaderboard_routes(app, service=service, call=call)
    register_mismap_routes(app, authenticated_actor=authenticated_actor, service=service, call=call)
    _register_catalog(app, authenticated_actor=authenticated_actor, service=service, call=call)
    register_override_pattern_routes(app, authenticated_actor=authenticated_actor, service=service, call=call)
    register_bulk_override_routes(app, authenticated_actor=authenticated_actor, service=service, call=call)


def _register_rules(
    app: FastAPI,
    *,
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    """Attach rules explorer and history routes."""
    _register_rules_search(app, service=service, call=call)
    _register_rules_history(app, service=service, call=call)


def _register_rules_search(
    app: FastAPI,
    *,
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    @app.get("/console/rules", tags=["console"])
    def console_rules(
        q: str | None = None,
        kind: str = "entities",
        limit: int = 100,
        offset: int = 0,
        at: str | None = None,
        league: list[str] | None = Query(default=None),
        sportsbook: list[str] | None = Query(default=None),
        canonical: list[str] | None = Query(default=None),
        action: list[str] | None = Query(default=None),
        sort: str | None = None,
        sort_dir: str = Query(default="asc", alias="dir"),
        control: ProposalService = Depends(service),
    ) -> Any:
        """Human-readable rules explorer with optional field filters and sort."""
        return call(
            lambda: control.human_rules(
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
        )


def _register_rules_history(
    app: FastAPI,
    *,
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    @app.get("/console/rules/history", tags=["console"])
    def console_rules_history(
        kind: str = "entity",
        natural_key: str | None = None,
        league: str | None = None,
        entity_type: str | None = None,
        canonical_key: str | None = None,
        sportsbook: str | None = None,
        source_key_type: str | None = None,
        source_key: str | None = None,
        control: ProposalService = Depends(service),
    ) -> Any:
        """Per-rule on/off windows (effective_from / effective_to)."""
        return call(
            lambda: control.rule_history(
                kind=kind,
                natural_key=natural_key,
                league=league,
                entity_type=entity_type,
                canonical_key=canonical_key,
                sportsbook=sportsbook,
                source_key_type=source_key_type,
                source_key=source_key,
            )
        )


def _register_proposed(
    app: FastAPI,
    *,
    authenticated_actor: Callable[..., Actor],
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    @app.get("/console/proposed/leagues", tags=["console"])
    def console_proposed_leagues(
        ref: str | None = None,
        control: ProposalService = Depends(service),
    ) -> Any:
        """Unique mapping rows + fixture rail projection for open proposals."""
        return call(lambda: control.console_proposed_leagues(ref=ref))

    @app.post("/console/proposed/{ref}/items", tags=["console"])
    def console_proposed_trim(
        ref: str,
        body: ProposedTrimBody,
        control: ProposalService = Depends(service),
        actor: Actor = Depends(authenticated_actor),
    ) -> Any:
        """Drop items from a batch proposal and re-validate."""
        return call(lambda: control.console_trim_proposed(ref, body.drop, actor))


def _register_coverage(
    app: FastAPI,
    *,
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    @app.get("/console/coverage/fixtures", tags=["console"])
    def console_coverage_fixtures(
        league: str | None = None,
        sport: str | None = None,
        q: str | None = None,
        phase: str = "live",
        limit: int = 10,
        offset: int = 0,
        control: ProposalService = Depends(service),
    ) -> Any:
        """Optic fixtures with published market_mapping coverage."""
        return call(
            lambda: control.console_coverage_fixtures(
                league=league,
                sport=sport,
                q=q,
                phase=phase,
                limit=limit,
                offset=offset,
            )
        )

    @app.get("/console/coverage/fixtures/{fixture_id}", tags=["console"])
    def console_coverage_fixture(
        fixture_id: str,
        league: str | None = None,
        control: ProposalService = Depends(service),
    ) -> Any:
        """Single fixture coverage detail."""
        return call(lambda: control.console_coverage_fixture(fixture_id, league=league))


def _register_missing(
    app: FastAPI,
    *,
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    @app.get("/console/missing-symbols", tags=["console"])
    def console_missing_symbols(
        platform: str | None = None,
        league: str | None = None,
        sport: str | None = None,
        scope: str = "all",
        market_group: str | None = None,
        contract_type: list[str] | None = Query(default=None),
        q: str | None = None,
        kickoff_from: str | None = None,
        kickoff_to: str | None = None,
        sort: str = "kickoff",
        sort_dir: str = Query(default="asc", alias="dir"),
        limit: int = 100,
        offset: int = 0,
        refresh: bool = False,
        control: ProposalService = Depends(service),
    ) -> Any:
        """Catalogue symbols absent from market_mapping (crypto.com first)."""
        return call(
            lambda: control.console_missing_symbols(
                platform=platform,
                league=league,
                sport=sport,
                scope=scope,
                market_group=market_group,
                contract_type=contract_type,
                q=q,
                kickoff_from=kickoff_from,
                kickoff_to=kickoff_to,
                sort=sort,
                sort_dir=sort_dir,
                limit=limit,
                offset=offset,
                refresh=refresh,
            )
        )


def _register_unmapped(
    app: FastAPI,
    *,
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    @app.get("/console/unmapped-legs", tags=["console"])
    def console_unmapped_legs(
        platform: str | None = None,
        league: str | None = None,
        sport: str | None = None,
        q: str | None = None,
        phase: str = "live",
        sort: str = "start",
        sort_dir: str = Query(default="asc", alias="dir"),
        limit: int = 100,
        offset: int = 0,
        control: ProposalService = Depends(service),
    ) -> Any:
        """RFQ unmapped-leg inventory with platform descriptions."""
        return call(
            lambda: control.console_unmapped_legs(
                platform=platform,
                league=league,
                sport=sport,
                q=q,
                phase=phase,
                sort=sort,
                sort_dir=sort_dir,
                limit=limit,
                offset=offset,
            )
        )


def _register_unmapped_actions(
    app: FastAPI,
    *,
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    _register_unmapped_why(app, service=service, call=call)

    @app.post("/console/unmapped-legs/stage", tags=["console"])
    def console_unmapped_stage(
        body: dict[str, Any],
        control: ProposalService = Depends(service),
    ) -> Any:
        """Draft cart items for selected mappable badges on one unmapped leg."""
        return call(
            lambda: control.console_unmapped_stage(
                platform=str(body.get("platform") or ""),
                key=str(body.get("key") or ""),
                item_ids=[str(item_id) for item_id in (body.get("item_ids") or [])],
                description=str(
                    body.get("description") or body.get("platform_leg_description") or ""
                )
                or None,
                league=str(body.get("league") or "") or None,
                fixture=str(body.get("fixture") or "") or None,
                sport=str(body.get("sport") or "") or None,
                market_group=str(body.get("market_group") or "") or None,
                contract_type=str(body.get("contract_type") or "") or None,
                crypto_ids=[
                    str(value)
                    for value in (body.get("crypto_ids") or [])
                    if str(value).strip()
                ]
                or None,
            )
        )


class CatalogOverrideBody(BaseModel):
    sportsbook: str
    game_id: str
    market_id: str
    selection: str
    source_market_id: str
    source_selection_id: str = ""
    selection_line: str = ""
    points: float = 0.0
    selection_points: float = 0.0
    grouping_key: str = "default"
    reason: str
    active: bool = True


def _require_catalog(settings: Settings = Depends(get_settings)) -> Settings:
    if not settings.catalog_enabled:
        raise HTTPException(
            status_code=404,
            detail={"reason_code": "catalog_disabled"},
        )
    return settings


def _register_catalog(
    app: FastAPI,
    *,
    authenticated_actor: Callable[..., Actor],
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    @app.get("/console/catalog/lookup", tags=["console"])
    def console_catalog_lookup(
        sportsbook: str,
        source_market_id: str,
        source_selection_id: str = "",
        control: ProposalService = Depends(service),
        _: Settings = Depends(_require_catalog),
    ) -> Any:
        """Look up opticodds_mapping winner + candidates for one RFQ key."""
        return call(
            lambda: control.console_catalog_lookup(
                sportsbook=sportsbook,
                source_market_id=source_market_id,
                source_selection_id=source_selection_id,
            )
        )

    @app.post("/console/catalog/override", tags=["console"])
    def console_catalog_override(
        body: CatalogOverrideBody,
        control: ProposalService = Depends(service),
        actor: Actor = Depends(authenticated_actor),
        _: Settings = Depends(_require_catalog),
    ) -> Any:
        """Publish mapping_override and start async merge + rank propagation."""
        return call(lambda: control.console_catalog_override(body.model_dump(), actor))

    @app.get("/console/catalog/override/jobs/{job_id}", tags=["console"])
    def console_catalog_override_job(
        job_id: str,
        control: ProposalService = Depends(service),
        _: Settings = Depends(_require_catalog),
    ) -> Any:
        """Poll async override propagation status."""
        return call(lambda: control.console_catalog_override_job(job_id))


def _register_unmapped_why(
    app: FastAPI,
    *,
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    @app.get("/console/unmapped-legs/why", tags=["console"])
    def console_unmapped_why(
        platform: str,
        key: str,
        description: str | None = None,
        league: str | None = None,
        fixture: str | None = None,
        sport: str | None = None,
        market_group: str | None = None,
        contract_type: str | None = None,
        crypto_ids: str | None = None,
        control: ProposalService = Depends(service),
    ) -> Any:
        """Mapping breakdown and residual reasons for one unmapped leg."""
        ids = [part.strip() for part in (crypto_ids or "").split(",") if part.strip()]
        return call(
            lambda: control.console_unmapped_why(
                platform=platform,
                key=key,
                description=description,
                league=league,
                fixture=fixture,
                sport=sport,
                market_group=market_group,
                contract_type=contract_type,
                crypto_ids=ids or None,
            ),
        )
