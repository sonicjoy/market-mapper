"""ProposalService mixin: bulk override (mmmapper#21) - legs, Optic lookups, draft, publish, poll."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from google.cloud import bigquery

from mappers.canonical_codes import person_league
from mappers.control_plane.console_bulk_override_batch import batch_view, publish_override_batch
from mappers.control_plane.console_bulk_override_pairing import (
    draft_pairs,
    status_counts,
)
from mappers.control_plane.console_bulk_override_sql import (
    QueryFn,
    console_project,
    kalshi_event_legs,
    optic_selections,
    search_optic_fixtures,
)
from mappers.control_plane.console_bulk_override_venues import venue_block_reason
from mappers.control_plane.console_oom_catalog import preflight_fixture_materialisation
from mappers.control_plane.console_unmapped import build_unmapped_tip_index, enrich_unmapped_row
from mappers.control_plane.models import Actor, ValidationFailedError


def _leg_view(raw: dict[str, Any]) -> dict[str, Any]:
    """BQ leg row -> the leg shape the draft endpoint takes back."""
    ticker = str(raw.get("market_ticker") or "")
    return {
        "source_market_id": ticker,
        "source_selection_id": str(raw.get("side") or "yes"),
        "name": str(raw.get("yes_sub_title") or ""),
        "line": raw.get("line"),
        "demand": int(raw.get("demand") or 0),
    }


def _markets(rows: list[dict[str, Any]], game_id: str) -> list[dict[str, Any]]:
    """Group a game's Optic selections by market, most-quoted markets first."""
    grouped: dict[str, dict[str, Any]] = {}
    for raw in rows:
        mid = str(raw.get("market_id") or "")
        market = grouped.setdefault(mid, {"market_id": mid, "market": raw.get("market") or mid, "selections": []})
        market["selections"].append({**raw, "game_id": game_id})
    return sorted(grouped.values(), key=lambda m: (-len(m["selections"]), m["market_id"]))


def _bad(message: str) -> ValidationFailedError:
    """400-shaped validation error."""
    return ValidationFailedError(message, reason_code="bad_request", dry_run={})


class ConsoleBulkOverrideOpsMixin:
    """Bulk override endpoints for ProposalService (reads are BQ; publish reuses Catalog's path)."""

    bulk_override_query_fn: QueryFn | None = None
    bulk_override_preflight_fn: Callable[[str], str | None] | None = None

    def console_bulk_override_legs(self, *, sportsbook: str, event: str) -> dict[str, Any]:
        """Unmapped selections for one Kalshi event, with a kickoff day hint."""
        if sportsbook.strip().lower() != "kalshi":
            raise _bad("bulk override legs are read for Kalshi events only today")
        index = build_unmapped_tip_index(self.store)  # type: ignore[attr-defined]
        hit = enrich_unmapped_row({"platform": "kalshi", "key": event}, index)
        rows = kalshi_event_legs(event, query_fn=self.bulk_override_query_fn)
        league = hit.get("league") or None
        return {
            "sportsbook": "Kalshi",
            "event": event,
            "league": league,
            "sport": hit.get("sport") or None,
            "player": person_league(str(league or "")),
            "day": hit.get("kickoff_day") or "",
            "legs": [_leg_view(r) for r in rows],
            "block_reason": venue_block_reason("kalshi"),
        }

    def console_bulk_override_fixtures(self, *, q: str = "", day: str = "") -> dict[str, Any]:
        """Optic fixtures in the override rank window, by team name and/or day."""
        rows = search_optic_fixtures(q, day, query_fn=self.bulk_override_query_fn)
        return {"fixtures": [{**r, "start_date": str(r.get("start_date") or "")} for r in rows]}

    def console_bulk_override_markets(self, *, game_id: str) -> dict[str, Any]:
        """Every Optic market + selection currently priced for one game."""
        rows = optic_selections(game_id, query_fn=self.bulk_override_query_fn)
        return {"game_id": game_id, "markets": _markets(rows, game_id)}

    def console_bulk_override_draft(self, body: dict[str, Any]) -> dict[str, Any]:
        """Pair venue selections to Optic selections in the chosen market(s); nothing is written."""
        game_id = str(body.get("game_id") or "").strip()
        market_id = str(body.get("market_id") or "").strip()
        if not game_id or not market_id:
            raise _bad("game_id and market_id are required")
        no_market_id = str(body.get("no_market_id") or "").strip() or market_id
        view = self.console_bulk_override_markets(game_id=game_id)
        markets = {m["market_id"]: m["selections"] for m in view["markets"]}
        if market_id not in markets:
            raise _bad(f"Optic has no priced {market_id!r} market for {game_id}")
        league = str(body.get("league") or "") or None
        pairs = draft_pairs(
            list(body.get("legs") or []),
            markets[market_id],
            no_selections=markets.get(no_market_id, []),
            player=person_league(league or ""),
        )
        return {"pairs": pairs, "counts": status_counts(pairs)}

    def console_bulk_override_publish(self, body: dict[str, Any], actor: Actor) -> dict[str, Any]:
        """Publish every confirmed pair as a mapping_override and propagate them together."""
        project = console_project()
        preflight = self.bulk_override_preflight_fn or (
            lambda gid: preflight_fixture_materialisation(bigquery.Client(project=project), project, gid)
        )
        return publish_override_batch(body, actor, project=project, preflight=preflight)

    def console_bulk_override_batch(self, batch_id: str) -> dict[str, Any]:
        """Batch header + per-pair job status."""
        return batch_view(batch_id)
