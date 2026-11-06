"""ProposalService methods for Explore -> Mapping risk (mmmapper#23)."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.console_mismap import flag_mapping, list_mapping_risk, resolve_flag
from mappers.control_plane.models import Actor


class ConsoleMismapOpsMixin:
    """Mapping-risk list and operator flags; flags persist through ``self.store``."""

    def console_mapping_risk(self, **filters: Any) -> dict[str, Any]:
        """Scored live mappings, riskiest first (filters: see list_mapping_risk)."""
        return list_mapping_risk(store=self.store, **filters)  # type: ignore[attr-defined]

    def console_mapping_risk_flag(self, row: dict[str, Any], note: str, actor: Actor) -> dict[str, Any]:
        """Flag one mapping as wrong; never un-maps it."""
        return flag_mapping(self.store, actor, row=row, note=note)  # type: ignore[attr-defined]

    def console_mapping_risk_resolve(self, fingerprint: str, note: str, actor: Actor) -> dict[str, Any]:
        """Close a mapping flag with its resolution."""
        return resolve_flag(self.store, actor, fingerprint=fingerprint, note=note)  # type: ignore[attr-defined]
