"""Verify/submit retry loop for harvest batch pins."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mappers.control_plane.dry_run_already import NOOP_BLOCKER

_MAX_VERIFY_ROUNDS = 3
_MAX_PEEL_ROUNDS = 10
_UNCHANGED = object()


@dataclass
class _LoopCtx:
    """Mutable verify-loop state shared across mitigate/peel rounds."""

    skipped: list[str]
    extra: list[str] = field(default_factory=list)
    seen_extra: set[str] = field(default_factory=set)
    last_verified: dict[str, Any] = field(default_factory=dict)
    round_fn: Callable[..., tuple[dict[str, Any], list[dict[str, Any]] | object, dict[str, Any] | None]] | None = None


def verify_submit_loop(
    service: Any,
    actor: Any,
    working: list[dict[str, Any]],
    skipped: list[str],
    acknowledge_shadow: bool,
    note: str,
    existing_proposal_id: str | None,
) -> dict[str, Any]:
    """Mitigate blockers, peel stuck pins, submit the rest."""
    ctx = _loop_ctx(
        service, actor, skipped, acknowledge_shadow, note, existing_proposal_id,
    )
    done, current = _run_phase(ctx, working, _MAX_VERIFY_ROUNDS, peel=False)
    if done is not None:
        return done
    done, current = _run_phase(ctx, current, _MAX_PEEL_ROUNDS, peel=True)
    if done is not None:
        return done
    return _blocked_result(ctx, current)


def _loop_ctx(
    service: Any,
    actor: Any,
    skipped: list[str],
    acknowledge_shadow: bool,
    note: str,
    existing_proposal_id: str | None,
) -> _LoopCtx:
    from mappers.control_plane.gap_fix_verify import (
        _batch_body,
        _pin_implicated,
        _pin_sig,
        drop_implicated,
    )

    ctx = _LoopCtx(skipped=skipped)

    def track_dropped(dropped: list[str]) -> None:
        for item in dropped:
            if item not in ctx.seen_extra:
                ctx.seen_extra.add(item)
                ctx.extra.append(item)

    ctx.round_fn = _make_round(
        service,
        actor,
        skipped,
        ctx.extra,
        acknowledge_shadow,
        note,
        existing_proposal_id,
        track_dropped,
        drop_implicated=drop_implicated,
        batch_body=_batch_body,
        pin_sig=_pin_sig,
        pin_implicated=_pin_implicated,
    )
    return ctx


def _run_phase(
    ctx: _LoopCtx,
    current: list[dict[str, Any]],
    rounds: int,
    *,
    peel: bool,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Run up to ``rounds`` verify passes; return (early_result, working)."""
    round_fn = ctx.round_fn
    if round_fn is None:
        return None, current
    for _ in range(rounds):
        if not current:
            break
        ctx.last_verified, nxt, done = round_fn(current, peel=peel)
        if done is not None:
            return done, current
        if nxt is _UNCHANGED:
            break
        if isinstance(nxt, list):
            current = nxt
    return None, current


def _blocked_result(ctx: _LoopCtx, current: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = list(ctx.last_verified.get("blockers") or [])
    return {
        "ok": False,
        "blockers": blockers or ctx.extra or ["verify loop exhausted"],
        "skipped_blockers": ctx.skipped + ctx.extra,
        "warnings": list(ctx.last_verified.get("warnings") or []),
        "count": len(current),
    }


def _make_round(
    service: Any,
    actor: Any,
    skipped: list[str],
    extra: list[str],
    acknowledge_shadow: bool,
    note: str,
    existing_proposal_id: str | None,
    track_dropped: Callable[[list[str]], None],
    *,
    drop_implicated: Any,
    batch_body: Any,
    pin_sig: Any,
    pin_implicated: Any,
) -> Callable[..., tuple[dict[str, Any], list[dict[str, Any]] | object, dict[str, Any] | None]]:
    """Build one verify-round closure bound to the batch helpers."""

    def round_fn(
        working: list[dict[str, Any]],
        *,
        peel: bool,
    ) -> tuple[dict[str, Any], list[dict[str, Any]] | object, dict[str, Any] | None]:
        return _verify_round(
            service,
            actor,
            working,
            skipped,
            extra,
            acknowledge_shadow,
            note,
            existing_proposal_id,
            track_dropped,
            peel=peel,
            drop_implicated=drop_implicated,
            batch_body=batch_body,
            pin_sig=pin_sig,
            pin_implicated=pin_implicated,
        )

    return round_fn


def _verify_round(
    service: Any,
    actor: Any,
    working: list[dict[str, Any]],
    skipped: list[str],
    extra: list[str],
    acknowledge_shadow: bool,
    note: str,
    existing_proposal_id: str | None,
    track_dropped: Callable[[list[str]], None],
    *,
    peel: bool,
    drop_implicated: Any,
    batch_body: Any,
    pin_sig: Any,
    pin_implicated: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]] | object, dict[str, Any] | None]:
    """One verify pass; return (verified, next_working, early_result)."""
    verified = service.entry_batch_verify(
        batch_body(working, acknowledge_shadow=acknowledge_shadow, note=note),
    )
    if verified.get("ok"):
        return verified, working, _submit_verified(
            service, actor, verified, working, skipped, extra, existing_proposal_id,
        )
    blockers = list(verified.get("blockers") or [])
    if _noop_only(blockers):
        return verified, working, _noop_verify(skipped, extra, working)
    nxt, dropped = drop_implicated(working, blockers)
    track_dropped(dropped)
    if not nxt:
        return verified, [], _all_pins_dropped(verified, skipped, extra)
    if pin_sig(nxt) != pin_sig(working):
        return verified, nxt, None
    if peel:
        peeled = _peel_implicated(working, blockers, pin_implicated=pin_implicated)
        if peeled and pin_sig(peeled) != pin_sig(working):
            for blocker in blockers:
                if any(pin_implicated(pin, blocker) for pin in working):
                    track_dropped([blocker])
            return verified, peeled, None
    return verified, _UNCHANGED, None


def _all_pins_dropped(
    verified: dict[str, Any],
    skipped: list[str],
    extra: list[str],
) -> dict[str, Any]:
    """Verify dropped every pin; do not call batch verify on an empty cart."""
    blockers = list(verified.get("blockers") or [])
    return {
        "ok": False,
        "blockers": blockers or ["all pins dropped in verify"],
        "skipped_blockers": skipped + extra,
        "warnings": list(verified.get("warnings") or []),
        "count": 0,
    }


def _noop_only(blockers: list[str]) -> bool:
    """True when the batch is already live on the tip."""
    return bool(blockers) and all(blocker == NOOP_BLOCKER for blocker in blockers)


def _noop_verify(
    skipped: list[str],
    extra: list[str],
    working: list[dict[str, Any]],
) -> dict[str, Any]:
    """Everything in the batch already matches the tip."""
    return {
        "ok": True,
        "noop": True,
        "blockers": [],
        "skipped_blockers": skipped + extra,
        "warnings": [],
        "count": len(working),
    }


def _submit_verified(
    service: Any,
    actor: Any,
    verified: dict[str, Any],
    working: list[dict[str, Any]],
    skipped: list[str],
    extra: list[str],
    existing_proposal_id: str | None,
) -> dict[str, Any]:
    token = verified["preview_token"]
    review = (
        service.replace_batch_proposal(existing_proposal_id, token, actor)
        if existing_proposal_id
        else service.entry_batch_submit(token, actor)
    )
    return {
        "ok": True,
        "blockers": [],
        "skipped_blockers": skipped + extra,
        "warnings": list(verified.get("warnings") or []),
        "review": review,
        "count": len(working),
    }


def _peel_implicated(
    pins: list[dict[str, Any]],
    blockers: list[str],
    *,
    pin_implicated: Any,
) -> list[dict[str, Any]]:
    """Drop pins still named by blockers after mitigation made no progress."""
    return [
        pin for pin in pins
        if not any(pin_implicated(pin, blocker) for blocker in blockers)
    ]
