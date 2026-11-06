"""Batch verify + submit for harvest pins, with blocker-implicated retries."""

from __future__ import annotations

import ast
import re
from typing import Any

from mappers.alias_kinds import alias_value, is_optic_id
from mappers.control_plane.live_evidence import crypto_row_cache_scope
from mappers.control_plane.models import BatchEntryRequest, MappingLeaguePayload
from mappers.control_plane.pin_flow import alias_from_pin, is_league_pin
from mappers.control_plane.pin_flow_markets import is_market_pin, market_payload_from_pin

_DRY_RUN_FAIL = re.compile(r"entity_alias dry-run failed for (\S+) \(([^)]+)\)")

_LEAGUE_SLUG = r"([A-Za-z0-9_-]+)"
_OPTIC_LEAGUE_MISS = re.compile(
    rf"No Optic league id on tip for {_LEAGUE_SLUG}\.",
)
_OPTIC_NAME_MISMATCH = re.compile(
    r"^Optic (\S+) is (.+), not (.+)\.$",
)
_LOOKUP_FAIL = (
    (re.compile(rf"Optic fixture lookup failed for {_LEAGUE_SLUG}:"), "optic"),
    (re.compile(rf"crypto\.com catalogue lookup failed for {_LEAGUE_SLUG}:"), "crypto.com"),
)


def verify_submit(
    service: Any,
    actor: Any,
    kept: list[dict[str, Any]],
    skipped: list[str],
    acknowledge_shadow: bool,
    note: str,
    existing_proposal_id: str | None = None,
) -> dict[str, Any]:
    """Batch verify; on residual blockers drop implicated pins and retry."""
    from mappers.control_plane.gap_fix_verify_loop import verify_submit_loop

    with crypto_row_cache_scope():
        return verify_submit_loop(
            service,
            actor,
            drop_clone_on_existing(getattr(service, "store", None), kept),
            skipped,
            acknowledge_shadow,
            note,
            existing_proposal_id,
        )


def _batch_body(
    working: list[dict[str, Any]],
    *,
    acknowledge_shadow: bool,
    note: str,
) -> BatchEntryRequest:
    return BatchEntryRequest(
        entity_aliases=[
            alias_from_pin(pin) for pin in working
            if not is_league_pin(pin) and not is_market_pin(pin)
        ],
        leagues=[league_from_pin(pin) for pin in working if is_league_pin(pin)],
        market_rules=[
            market_payload_from_pin(pin) for pin in working if is_market_pin(pin)
        ],
        acknowledge_shadow=acknowledge_shadow,
        note=note,
    )


def league_from_pin(pin: dict[str, Any]) -> MappingLeaguePayload:
    """Strip harvest-only fields into a mapping_league payload."""
    return MappingLeaguePayload.model_validate(pin)


def alias_in_blocker(value: str, blocker: str) -> bool:
    """True when ``value`` appears as its own token in a blocker (not a substring)."""
    if not value:
        return False
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", blocker) is not None


def drop_clone_on_existing(
    store: Any, pins: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Clone is new-league only; strip it from slugs already on the tip."""
    existing = _tip_league_slugs(store)
    if not existing:
        return pins
    out: list[dict[str, Any]] = []
    for pin in pins:
        if not is_league_pin(pin):
            out.append(pin)
            continue
        slug = str(pin.get("league") or "").casefold()
        if pin.get("clone_market_rules_from") and slug in existing:
            pin = {**pin, "clone_market_rules_from": None}
        out.append(pin)
    return out


def _tip_league_slugs(store: Any) -> set[str]:
    rid = getattr(store, "current_rule_set_id", None)
    if not store or not rid or not hasattr(store, "leagues_for"):
        return set()
    return {str(lg.league).casefold() for lg in store.leagues_for(rid)}


def drop_implicated(
    pins: list[dict[str, Any]],
    blockers: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Mitigate or drop pins named by verify blockers; keep unrelated pins."""
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    for pin in pins:
        hits = [blocker for blocker in blockers if _pin_implicated(pin, blocker)]
        if not hits:
            kept.append(pin)
            continue
        nxt = _apply_mitigations(pin, hits)
        if not _keep_after_mitigate(pin, nxt, hits):
            dropped.extend(hits)
            continue
        kept.append(nxt)
        dropped.extend(hits)
    return kept, dropped or list(blockers)


def _keep_after_mitigate(
    pin: dict[str, Any], nxt: dict[str, Any], hits: list[str],
) -> bool:
    """True when the mitigated pin can retry or is fully clear."""
    if not is_league_pin(nxt) and not is_market_pin(nxt) and not nxt.get("aliases"):
        return False
    leftover = [blocker for blocker in hits if _pin_implicated(nxt, blocker)]
    return not (leftover and _pin_sig([nxt]) == _pin_sig([pin]))


def _apply_mitigations(pin: dict[str, Any], hits: list[str]) -> dict[str, Any]:
    """Apply every per-blocker strip/rename that this pin can absorb."""
    nxt = pin
    for blocker in hits:
        updated = _mitigate(nxt, blocker)
        if updated is not None:
            nxt = updated
    return nxt


def _mitigate(pin: dict[str, Any], blocker: str) -> dict[str, Any] | None:
    """Rewrite or strip this pin for one blocker; None when it cannot help."""
    if is_league_pin(pin) or is_market_pin(pin):
        return None
    miss = _lookup_fail(blocker)
    if miss is not None:
        _league, book = miss
        if book == "optic":
            return _strip_all_optic(pin)
        return _strip_book(pin, book)
    if _optic_league_miss_league(blocker):
        return _strip_all_optic(pin)
    if _optic_inactive_miss(blocker):
        return _strip_optic_aliases(pin, [blocker])
    if _optic_name_mismatch_parts(blocker):
        return _rewrite_or_strip_optic_name(pin, blocker)
    return None


def _pin_sig(pins: list[dict[str, Any]]) -> tuple[tuple[str, str, str, str, tuple[tuple[str, str, str], ...]], ...]:
    """Identity of a batch, including alias triples and display name."""
    return tuple(
        (
            str(pin.get("kind") or ""),
            str(pin.get("league") or ""),
            str(pin.get("canonical_key") or ""),
            str(pin.get("canonical_name") or ""),
            tuple(
                (
                    str(alias.get("sportsbook") or ""),
                    str(alias.get("alias_kind") or ""),
                    str(alias.get("alias_value") or ""),
                )
                for alias in (pin.get("aliases") or [])
            ),
        )
        for pin in pins
    )


def _pin_implicated(pin: dict[str, Any], blocker: str) -> bool:
    """True when a verify blocker names this pin's book or Optic/crypto id."""
    miss = _lookup_fail(blocker)
    if miss is not None:
        league, book = miss
        if str(pin.get("league") or "") != league:
            return False
        if book == "optic":
            return _has_optic(pin)
        return _has_book(pin, book)
    league = _optic_league_miss_league(blocker)
    if league:
        return str(pin.get("league") or "") == league and _has_optic(pin)
    dry_run = _dry_run_fail_parts(blocker)
    if dry_run is not None:
        key, league = dry_run
        return (
            str(pin.get("canonical_key") or "") == key
            and str(pin.get("league") or "") == league
        )
    return any(alias_in_blocker(value, blocker) for value in _implicated_tokens(pin))


def _has_book(pin: dict[str, Any], book: str) -> bool:
    return any(
        str(alias.get("sportsbook") or "").lower() == book
        for alias in (pin.get("aliases") or [])
    )


def _has_optic(pin: dict[str, Any]) -> bool:
    return any(is_optic_id(alias) for alias in (pin.get("aliases") or []))


def _strip_book(pin: dict[str, Any], book: str) -> dict[str, Any] | None:
    """Drop aliases for ``book``; None when the pin had none."""
    aliases = list(pin.get("aliases") or [])
    kept = [
        alias for alias in aliases
        if str(alias.get("sportsbook") or "").lower() != book
    ]
    if len(kept) == len(aliases):
        return None
    return {**pin, "aliases": kept}


def _strip_all_optic(pin: dict[str, Any]) -> dict[str, Any] | None:
    """Drop every Optic alias on this pin."""
    aliases = list(pin.get("aliases") or [])
    kept = [alias for alias in aliases if not is_optic_id(alias)]
    if len(kept) == len(aliases):
        return None
    return {**pin, "aliases": kept}


def _strip_optic_aliases(
    pin: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any] | None:
    """Remove Optic ids named in blockers; None when nothing changes."""
    aliases = list(pin.get("aliases") or [])
    if not aliases:
        return None
    drop: set[str] = set()
    for blocker in blockers:
        for alias in aliases:
            if is_optic_id(alias) and alias_in_blocker(alias_value(alias), blocker):
                drop.add(alias_value(alias))
    if not drop:
        return None
    kept_aliases = [
        alias for alias in aliases
        if not (is_optic_id(alias) and alias_value(alias) in drop)
    ]
    if len(kept_aliases) == len(aliases):
        return None
    return {**pin, "aliases": kept_aliases}


def _rewrite_or_strip_optic_name(
    pin: dict[str, Any], blocker: str,
) -> dict[str, Any] | None:
    """Set canonical_name to the live Optic label; strip Optic if already set."""
    aliases = list(pin.get("aliases") or [])
    if sum(1 for alias in aliases if is_optic_id(alias)) > 1:
        return _strip_all_optic(pin)
    parts = _optic_name_mismatch_parts(blocker)
    if parts is None:
        return None
    oid, live, _tip = parts
    if not any(is_optic_id(alias) and alias_value(alias) == oid for alias in aliases):
        return None
    if live and str(pin.get("canonical_name") or "") != live:
        return {**pin, "canonical_name": live}
    return _strip_optic_aliases(pin, [blocker])


def _optic_inactive_miss(blocker: str) -> bool:
    """Optic horizon miss — safe to propose book-only aliases."""
    return "not in active" in blocker.casefold()


def _optic_name_mismatch_parts(blocker: str) -> tuple[str, str, str] | None:
    """oid, live label, tip label from an Optic name-mismatch blocker."""
    match = _OPTIC_NAME_MISMATCH.match(blocker)
    if match is None:
        return None
    oid, live_repr, tip_repr = match.group(1), match.group(2), match.group(3)
    live = _repr_str(live_repr)
    tip = _repr_str(tip_repr)
    if live is None or tip is None:
        return None
    return oid, live, tip


def _repr_str(raw: str) -> str | None:
    """Parse a ``repr()`` string produced by live evidence."""
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return None
    return value if isinstance(value, str) else None


def _lookup_fail(blocker: str) -> tuple[str, str] | None:
    """(league, book) from a scoped lookup-failed blocker, else None."""
    for pattern, book in _LOOKUP_FAIL:
        match = pattern.search(blocker)
        if match:
            return match.group(1), book
    return None


def _optic_league_miss_league(blocker: str) -> str:
    """League slug from a missing Optic league-id blocker, else empty."""
    match = _OPTIC_LEAGUE_MISS.search(blocker)
    return match.group(1) if match else ""


def _dry_run_fail_parts(blocker: str) -> tuple[str, str] | None:
    """Canonical key and league from an entity_alias dry-run failure."""
    match = _DRY_RUN_FAIL.search(blocker)
    if match is None:
        return None
    return match.group(1), match.group(2)


def _implicated_tokens(pin: dict[str, Any]) -> list[str]:
    """Values that identify this pin inside a verify blocker string."""
    if is_league_pin(pin):
        return [
            token for token in (
                str(pin.get("league") or ""),
                str(pin.get("optic_league_id") or ""),
                str(pin.get("clone_market_rules_from") or ""),
            ) if token
        ]
    if is_market_pin(pin):
        values: list[str] = [str(pin.get("league") or "")]
        for rule in pin.get("rules") or []:
            values.append(str(rule.get("source_key") or ""))
            values.append(str(rule.get("canonical_market_type") or ""))
        return [value for value in values if value]
    return [
        str(a.get("alias_value") or "")
        for a in (pin.get("aliases") or [])
        if str(a.get("alias_value") or "")
    ]
