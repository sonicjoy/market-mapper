"""Same-canonical line/side amends and explicit ticker-suffix binds.

Harvest still skips a key the Python base already maps. An observation that
sets line, side, or official text may update that same canonical. A
Polymarket US ticker suffix the spine does not name binds only when the
caller supplies the Optic id and it is in the live census.
"""

from __future__ import annotations

from typing import Any, cast

from mappers.control_plane.dry_run_market_rules import served_fields_differ
from mappers.control_plane.gap_market_bind import (
    resolve_market_type,
    simulate_overlay_applies,
    tip_market_rule,
)
from mappers.control_plane.rof_before_rule import MarketRuleObservation, obs_text

_SERVED = (
    "line_offset",
    "yes_side",
    "side_swap",
    "official_description",
    "citation_url",
)


def observation_sets_served(obs: MarketRuleObservation) -> bool:
    """True when the caller set a line, side, or official-text field."""
    return any(_served_value(obs, key) is not None for key in _SERVED)


def explicit_suffix_bind(
    obs: MarketRuleObservation,
    cfg: Any,
) -> tuple[str, str, list[str]] | None:
    """Optic id for a ticker suffix the spine does not list."""
    if str(obs.get("source_key_type") or "").strip() != "ticker_suffix":
        return None
    canonical = str(obs.get("canonical_market_type") or "").strip()
    live = set(obs.get("live_optic_market_ids") or ())
    if not canonical or canonical not in live:
        return None
    mt = resolve_market_type(cfg, canonical)
    if mt is None or str(mt.value) != canonical:
        return None
    return canonical, canonical, [f"optic:market_id:{canonical}"]


def overlay_accepts(
    obs: MarketRuleObservation,
    cfg: Any,
    rules: list[Any],
    canonical: str,
    market_group: str,
    notes: str | None,
) -> bool:
    """Ticker-suffix maps record a canonical the parser already knows."""
    book = str(obs.get("sportsbook") or "").strip().lower()
    key_type = str(obs.get("source_key_type") or "").strip()
    if book == "polymarket_usa" and key_type == "ticker_suffix":
        mt = resolve_market_type(cfg, canonical)
        return mt is not None and str(mt.value) == canonical
    return simulate_overlay_applies(
        cfg,
        rules,
        sportsbook=book,
        source_key_type=key_type,
        source_key=str(obs.get("source_key") or "").strip(),
        canonical=canonical,
        market_group=market_group,
        notes=notes,
    )


def retarget_block(
    obs: MarketRuleObservation,
    cfg: Any,
    rules: list[Any],
    canonical: str,
) -> str:
    """Skip reason when a served amend would change the canonical."""
    if not observation_sets_served(obs):
        return ""
    book = str(obs.get("sportsbook") or "").strip().lower()
    key_type = str(obs.get("source_key_type") or "").strip()
    key = str(obs.get("source_key") or "").strip()
    prior = tip_market_rule(
        rules, sportsbook=book, source_key_type=key_type, source_key=key,
    )
    if prior is None or str(prior.action or "") != "map":
        return ""
    if str(prior.canonical_market_type or "") != canonical:
        return "already_mapped"
    if not served_fields_differ(prior, _proposed_fields(obs)):
        return "already_mapped"
    return ""


def _served_value(obs: MarketRuleObservation, key: str) -> Any:
    raw = obs.get(key)
    if raw is None or (key == "side_swap" and raw is False):
        return None
    if key in {"official_description", "citation_url", "yes_side"}:
        return obs_text(obs, key)
    return raw


_FLIP_KEYS = (
    "canonical_market_type",
    "match_operator",
    "line_offset",
    "yes_side",
    "side_swap",
    "official_description",
    "citation_url",
    "notes",
)


def fill_flip_prior(obs: MarketRuleObservation, prior: Any) -> None:
    """Copy the ignored tip row onto a flip. Blank and side_swap False stay empty."""
    if not obs.get("flip_ignore") or prior is None:
        return
    target = cast(dict[str, Any], obs)
    for key in _FLIP_KEYS:
        if _present(obs.get(key)):
            continue
        value = getattr(prior, key, None)
        if key == "side_swap" and value is False:
            continue
        if _present(value):
            target[key] = value


def flip_canonical_bind(
    obs: MarketRuleObservation,
    cfg: Any,
) -> tuple[str, str, list[str]] | None:
    """Optic id for an ignore→map flip whose prior canonical is a MarketType."""
    if not obs.get("flip_ignore"):
        return None
    canonical = str(obs.get("canonical_market_type") or "").strip()
    if not canonical:
        return None
    mt = resolve_market_type(cfg, canonical)
    if mt is None or str(mt.value) != canonical:
        return None
    return canonical, canonical, [f"optic:market_id:{canonical}"]


def blocked_prior(
    obs: MarketRuleObservation,
    rules: list[Any],
    book: str,
    key_type: str,
    key: str,
    skipped: list[dict[str, str]],
    skip: Any,
) -> bool:
    """True when this observation must not amend the tip row."""
    prior = tip_market_rule(
        rules, sportsbook=book, source_key_type=key_type, source_key=key,
    )
    fill_flip_prior(obs, prior)
    if prior is not None and str(prior.action or "") == "ignore" and not obs.get("flip_ignore"):
        skipped.append(skip(obs, "already_ignored"))
        return True
    if (
        prior is not None
        and str(prior.action or "") == "map"
        and prior.enabled
        and not observation_sets_served(obs)
    ):
        skipped.append(skip(
            obs, "already_mapped", detail=str(prior.canonical_market_type or ""),
        ))
        return True
    return False


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _proposed_fields(obs: MarketRuleObservation) -> dict[str, Any]:
    return {
        "line_offset": obs.get("line_offset"),
        "yes_side": obs_text(obs, "yes_side"),
        "side_swap": obs.get("side_swap"),
        "official_description": obs_text(obs, "official_description"),
        "citation_url": obs_text(obs, "citation_url"),
    }
