"""Entry HTTP routes extracted from app.py for size guard."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, Header

from mappers.control_plane.models import (
    Actor,
    AliasSuggestRequest,
    BatchEntryRequest,
    EntrySubmitRequest,
    EntryVerifyRequest,
    LeagueEntryRequest,
    LeagueHarvestRequest,
    MarketRuleEntryRequest,
    MarketRuleSuggestRequest,
    StructuredAliasEntryRequest,
)
from mappers.control_plane.service import ProposalService

# ruff: noqa: B008


def register_entry_routes(
    app: FastAPI,
    *,
    authenticated_actor: Callable[..., Actor],
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    """Attach trader entry routes onto the FastAPI app."""
    _register_paste(app, authenticated_actor=authenticated_actor, service=service, call=call)
    _register_forms(app, authenticated_actor=authenticated_actor, service=service, call=call)
    _register_suggest(app, authenticated_actor=authenticated_actor, service=service, call=call)
    _register_batch(app, authenticated_actor=authenticated_actor, service=service, call=call)


def _register_paste(
    app: FastAPI,
    *,
    authenticated_actor: Callable[..., Actor],
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    @app.post("/entry/verify", tags=["entry"])
    def entry_verify(
        body: EntryVerifyRequest,
        actor: Actor = Depends(authenticated_actor),
        control: ProposalService = Depends(service),
    ) -> Any:
        """Parse + verify a trader paste (format hard, live soft)."""
        _ = actor
        return control.entry_verify(
            paste=body.paste,
            provided_name=body.provided_name,
            note=body.note,
            acknowledge_live_warning=body.acknowledge_live_warning,
            disambiguation_label=body.disambiguation_label,
            league=body.league,
        )

    @app.post("/entry/submit", tags=["entry"])
    def entry_submit(
        body: EntrySubmitRequest,
        actor: Actor = Depends(authenticated_actor),
        control: ProposalService = Depends(service),
    ) -> Any:
        """Confirm preview → propose + validate; return review card."""
        return call(lambda: control.entry_submit(body.preview_token, actor))

    @app.post("/entry/alias/verify", tags=["entry"])
    def entry_alias_structured_verify(
        body: StructuredAliasEntryRequest,
        actor: Actor = Depends(authenticated_actor),
        control: ProposalService = Depends(service),
    ) -> Any:
        """Verify a structured alias pin from Rules (no paste)."""
        _ = actor
        return call(lambda: control.entry_alias_structured_verify(body))


def _register_forms(
    app: FastAPI,
    *,
    authenticated_actor: Callable[..., Actor],
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    @app.post("/entry/league/verify", tags=["entry"])
    def entry_league_verify(
        body: LeagueEntryRequest,
        actor: Actor = Depends(authenticated_actor),
        control: ProposalService = Depends(service),
    ) -> Any:
        """Verify add-league form."""
        _ = actor
        return call(lambda: control.entry_league_verify(body))

    @app.post("/entry/league/submit", tags=["entry"])
    def entry_league_submit(
        body: LeagueEntryRequest,
        actor: Actor = Depends(authenticated_actor),
        control: ProposalService = Depends(service),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> Any:
        """Submit add-league proposal; retries with the same key reuse the card."""
        return call(lambda: control.entry_league_submit(body, actor, idempotency_key))

    @app.post("/entry/market-rule/verify", tags=["entry"])
    def entry_market_rule_verify(
        body: MarketRuleEntryRequest,
        actor: Actor = Depends(authenticated_actor),
        control: ProposalService = Depends(service),
    ) -> Any:
        """Verify market-rule form."""
        _ = actor
        return call(lambda: control.entry_market_rule_verify(body))

    @app.post("/entry/market-rule/submit", tags=["entry"])
    def entry_market_rule_submit(
        body: MarketRuleEntryRequest,
        actor: Actor = Depends(authenticated_actor),
        control: ProposalService = Depends(service),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> Any:
        """Submit market-rule proposal; retries with the same key reuse the card."""
        return call(lambda: control.entry_market_rule_submit(body, actor, idempotency_key))


def _register_suggest(
    app: FastAPI,
    *,
    authenticated_actor: Callable[..., Actor],
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    @app.post("/entry/market-rule/suggest", tags=["entry"])
    def entry_market_rule_suggest(
        body: MarketRuleSuggestRequest,
        actor: Actor = Depends(authenticated_actor),
        control: ProposalService = Depends(service),
    ) -> Any:
        """Suggest market rules from optic_spine (no LLM)."""
        _ = actor
        return call(lambda: control.entry_market_rule_suggest(body))

    @app.post("/entry/alias/suggest", tags=["entry"])
    def entry_alias_suggest(
        body: AliasSuggestRequest,
        actor: Actor = Depends(authenticated_actor),
        control: ProposalService = Depends(service),
    ) -> Any:
        """Suggest entity aliases from Optic fixtures (no LLM)."""
        _ = actor
        return call(lambda: control.entry_alias_suggest(body))

    @app.post("/entry/league/harvest-id", tags=["entry"])
    def entry_league_harvest_id(
        body: LeagueHarvestRequest,
        actor: Actor = Depends(authenticated_actor),
        control: ProposalService = Depends(service),
    ) -> Any:
        """Harvest one exchange source_league_id from live inventory."""
        _ = actor
        return call(lambda: control.entry_league_harvest_id(body))


def _register_batch(
    app: FastAPI,
    *,
    authenticated_actor: Callable[..., Actor],
    service: Callable[..., ProposalService],
    call: Callable[..., Any],
) -> None:
    @app.post("/entry/batch/verify", tags=["entry"])
    def entry_batch_verify(
        body: BatchEntryRequest,
        actor: Actor = Depends(authenticated_actor),
        control: ProposalService = Depends(service),
    ) -> Any:
        """Dry-run a staging cart of alias / league / market-rule changes."""
        _ = actor
        return call(lambda: control.entry_batch_verify(body))

    @app.post("/entry/batch/submit", tags=["entry"])
    def entry_batch_submit(
        body: EntrySubmitRequest,
        actor: Actor = Depends(authenticated_actor),
        control: ProposalService = Depends(service),
    ) -> Any:
        """Submit compound batch_changes proposal from a verified preview_token."""
        return call(lambda: control.entry_batch_submit(body.preview_token, actor))
