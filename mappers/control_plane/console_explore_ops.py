"""Coverage and Unmapped explorer ops for ProposalService."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.console_coverage import list_coverage_fixtures
from mappers.control_plane.console_coverage_detail import get_coverage_fixture
from mappers.control_plane.console_missing import list_missing_symbols
from mappers.control_plane.console_unmapped import list_unmapped_legs
from mappers.control_plane.console_unmapped_why_api import (
    stage_unmapped_console_leg,
    why_unmapped_console_leg,
)
from mappers.control_plane.console_venue_gaps import get_venue_gap_fixture, list_venue_gaps
from mappers.control_plane.console_venue_gaps_fix import stage_venue_gap_node, why_venue_gap_node
from mappers.control_plane.models import ValidationFailedError


class ConsoleExploreOpsMixin:
    """Explore-page fixture and unmapped-leg inventory."""

    def console_coverage_fixtures(
        self,
        *,
        league: str | None = None,
        sport: str | None = None,
        q: str | None = None,
        phase: str = "live",
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        return list_coverage_fixtures(
            self.store,  # type: ignore[attr-defined]
            league=league,
            sport=sport,
            q=q,
            phase=phase,
            limit=limit,
            offset=offset,
        )

    def console_coverage_fixture(
        self,
        fixture_id: str,
        *,
        league: str | None = None,
    ) -> dict[str, Any]:
        hit = get_coverage_fixture(
            self.store,  # type: ignore[attr-defined]
            fixture_id,
            league=league,
        )
        if hit is None:
            raise ValidationFailedError(
                "fixture not found",
                reason_code="not_found",
                dry_run={},
            )
        return hit

    def console_missing_symbols(
        self,
        *,
        platform: str | None = None,
        league: str | None = None,
        sport: str | None = None,
        scope: str = "all",
        market_group: str | None = None,
        contract_type: str | list[str] | None = None,
        q: str | None = None,
        kickoff_from: str | None = None,
        kickoff_to: str | None = None,
        sort: str = "kickoff",
        sort_dir: str = "asc",
        limit: int = 100,
        offset: int = 0,
        refresh: bool = False,
    ) -> dict[str, Any]:
        return list_missing_symbols(
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
            store=self.store,  # type: ignore[attr-defined]
        )

    def console_unmapped_legs(
        self,
        *,
        platform: str | None = None,
        league: str | None = None,
        sport: str | None = None,
        q: str | None = None,
        phase: str = "live",
        sort: str = "start",
        sort_dir: str = "asc",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        return list_unmapped_legs(
            platform=platform,
            league=league,
            sport=sport,
            q=q,
            phase=phase,
            sort=sort,
            sort_dir=sort_dir,
            limit=limit,
            offset=offset,
            store=self.store,  # type: ignore[attr-defined]
        )

    def console_unmapped_stage(
        self,
        *,
        platform: str,
        key: str,
        item_ids: list[str],
        description: str | None = None,
        league: str | None = None,
        fixture: str | None = None,
        sport: str | None = None,
        market_group: str | None = None,
        contract_type: str | None = None,
        crypto_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return stage_unmapped_console_leg(
            self.store,  # type: ignore[attr-defined]
            platform,
            key,
            item_ids,
            description=description,
            league=league,
            fixture=fixture,
            sport=sport,
            market_group=market_group,
            contract_type=contract_type,
            crypto_ids=crypto_ids,
            evidence_fn=getattr(self, "evidence_fn", None),
        )

    def console_unmapped_why(
        self,
        *,
        platform: str,
        key: str,
        description: str | None = None,
        league: str | None = None,
        fixture: str | None = None,
        sport: str | None = None,
        market_group: str | None = None,
        contract_type: str | None = None,
        crypto_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return why_unmapped_console_leg(
            self.store,  # type: ignore[attr-defined]
            platform,
            key,
            description=description,
            league=league,
            fixture=fixture,
            sport=sport,
            market_group=market_group,
            contract_type=contract_type,
            crypto_ids=crypto_ids,
        )

    def console_venue_gaps(
        self,
        *,
        platform: str = "crypto",
        phase: str = "live",
        q: str | None = None,
        kickoff_from: str | None = None,
        kickoff_to: str | None = None,
        markets: list[str] | None = None,
    ) -> dict[str, Any]:
        """Venue catalogue vs market_mapping, league x fixture rollup."""
        return list_venue_gaps(
            platform=platform,
            phase=phase,
            q=q,
            kickoff_from=kickoff_from,
            kickoff_to=kickoff_to,
            markets=markets,
            store=self.store,  # type: ignore[attr-defined]
        )

    def console_venue_gap_fixture(self, *, platform: str, fixture_key: str) -> dict[str, Any]:
        """Markets and selections for one catalogue fixture."""
        return get_venue_gap_fixture(
            platform=platform,
            fixture_key=fixture_key,
            store=self.store,  # type: ignore[attr-defined]
        )

    def console_venue_gap_why(self, *, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Merged rule badges for a node's sampled unmapped selections."""
        return why_venue_gap_node(self.store, rows)  # type: ignore[attr-defined]

    def console_venue_gap_stage(
        self,
        *,
        rows: list[dict[str, Any]],
        item_ids: list[str],
    ) -> dict[str, Any]:
        """Cart items for the selected merged badges of one node."""
        return stage_venue_gap_node(
            self.store,  # type: ignore[attr-defined]
            rows,
            item_ids,
            evidence_fn=getattr(self, "evidence_fn", None),
        )
