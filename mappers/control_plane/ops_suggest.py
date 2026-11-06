"""Suggestion endpoints: spine market rules and Optic aliases (no LLM)."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.harvest_league_ids import harvest_league_exchange_for_entry
from mappers.control_plane.suggest_aliases import suggest_aliases_from_optic
from mappers.control_plane.suggest_markets import suggest_market_rules
from mappers.shared import FIXTURE_HORIZON_HOURS


class SuggestOpsMixin:
    """Read-only helpers that propose cart items for the trader to confirm."""

    def entry_market_rule_suggest(self, body: Any) -> dict[str, Any]:
        """Spine-based market rule suggestions for a new/existing league."""
        current = self.store.current_rule_set_id  # type: ignore[attr-defined]
        tip_leagues = self.store.leagues_for(current) if current else []  # type: ignore[attr-defined]
        return suggest_market_rules(
            league=body.league,
            optic_league_id=body.optic_league_id,
            sport=body.sport,
            sportsbooks=list(body.sportsbooks or []),
            tip_leagues=tip_leagues,
            template_league=body.template_league,
            store=self.store,  # type: ignore[attr-defined]
        )

    def entry_alias_suggest(self, body: Any) -> dict[str, Any]:
        """Optic competitor → entity_alias suggestions (no LLM)."""
        return suggest_aliases_from_optic(
            league=body.league,
            sport=body.sport,
            optic_league_id=body.optic_league_id,
            horizon_hours=float(body.fixture_horizon_hours or FIXTURE_HORIZON_HOURS),
            store=self.store,  # type: ignore[attr-defined]
        )

    def entry_league_harvest_id(self, body: Any) -> dict[str, Any]:
        """Live harvest of one exchange source_league_id for the league form."""
        return harvest_league_exchange_for_entry(
            self.store,  # type: ignore[attr-defined]
            league=str(body.league or ""),
            sport=body.sport,
            optic_league_id=body.optic_league_id,
            sportsbook=str(body.sportsbook or ""),
            fixture_horizon_hours=body.fixture_horizon_hours,
        )
