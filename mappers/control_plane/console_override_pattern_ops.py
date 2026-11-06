"""ProposalService methods for Explore -> Override patterns."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.models import Actor, ForbiddenError
from mappers.control_plane.override_clusters import DEFAULT_MIN_GAMES
from mappers.control_plane.override_clusters_draft import (
    RowsFn,
    list_override_patterns,
    stage_override_pattern,
)
from mappers.control_plane.override_clusters_sql import fetch_latest_overrides

_WRITE_ROLES = frozenset({"proposer", "approver", "admin", "service"})


class ConsoleOverridePatternOpsMixin:
    """Repeated overrides -> rule proposals (list + stage)."""

    override_rows_fn: RowsFn | None = None

    def _override_rows(self) -> RowsFn:
        return self.override_rows_fn or fetch_latest_overrides

    def console_override_patterns(
        self,
        *,
        min_games: int = DEFAULT_MIN_GAMES,
        include_inactive: bool = False,
        kind: str | None = None,
    ) -> dict[str, Any]:
        """Override clusters over ``min_games`` fixtures, each with a kernel draft verdict."""
        return list_override_patterns(
            self,
            self._override_rows(),
            min_games=max(1, min_games),
            include_inactive=include_inactive,
            kind=kind or None,
        )

    def console_override_pattern_stage(
        self, cluster_id: str, actor: Actor, *, acknowledge_shadow: bool = False
    ) -> dict[str, Any]:
        """Draft one cluster's rule and submit it to Proposed (no approve)."""
        if actor.role.value not in _WRITE_ROLES:
            raise ForbiddenError("role cannot propose rules")
        return stage_override_pattern(
            self, actor, cluster_id, self._override_rows(), acknowledge_shadow=acknowledge_shadow
        )
