"""Operator-facing Why reasons for unmapped RFQ legs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mappers.control_plane.console_unmapped_why_layers import mapping_stack_reasons

ReasonPred = Callable[[str, str], bool]


def explain_unmapped_leg(
    row: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    has_fixes: bool,
    store: Any | None = None,
) -> list[dict[str, Any]]:
    """Human reasons this inventory row is unmapped (residual vs cart-fix)."""
    shape = _shape_reasons(row)
    if shape:
        return [
            *shape,
            *_context_reasons(row, items),
            *_item_reasons(row, items, has_fixes=has_fixes, has_shape=True),
        ]
    stack = mapping_stack_reasons(row, store, items)
    reasons = [*stack, *_context_reasons(row, items)]
    reasons.extend(
        _item_reasons(row, items, has_fixes=has_fixes, has_shape=False),
    )
    if not reasons:
        reasons.append(
            _reason(
                "no_cart_fix",
                "No mapping link identified (fixture, alias, or market rule).",
            )
        )
    return reasons


def _reason(code: str, text: str, *, actionable: bool = False) -> dict[str, Any]:
    return {"code": code, "text": text, "actionable": actionable}


def _blob(row: dict[str, Any]) -> str:
    parts = (
        str(row.get("platform_leg_description") or ""),
        str(row.get("fixture") or ""),
        str(row.get("key") or ""),
    )
    return " ".join(parts).casefold()


def _outcome(row: dict[str, Any]) -> str:
    desc = str(row.get("platform_leg_description") or "")
    if " — " not in desc:
        return ""
    return desc.split(" — ", 1)[1].strip().casefold()


def _has_exact_score(blob: str, _key: str) -> bool:
    return any(token in blob for token in ("exact score", "exact-score", "exact_score", "any other score"))


def _has_half_corners(blob: str, _key: str) -> bool:
    half = "first-half" in blob or "second-half" in blob or "1st half" in blob or "2nd half" in blob
    return "odd-even-corners" in blob or "odd even corners" in blob or ("corners" in blob and half)


def _has_doubles(blob: str, key: str) -> bool:
    return "doubles" in blob or "DOUBLES" in key.upper()


def _has_to_advance(blob: str, _key: str) -> bool:
    return "to-advance" in blob or "to advance" in blob


def _has_esports_prop(blob: str, _key: str) -> bool:
    return any(
        token in blob
        for token in ("-game1", "-game2", "-map1", "-map2", "round-handicap", "map-handicap", "maps-total")
    )


def _has_period_market(blob: str, _key: str) -> bool:
    return any(token in blob for token in ("-1q-", "-2q-", "-3q-", "-4q-", "-1h-", "-2h-"))


_SHAPES: tuple[tuple[str, ReasonPred, str], ...] = (
    (
        "exact_score",
        _has_exact_score,
        "Exact score is expected residual. We only map it when Optic prices "
        "correct_score for this league, and only the Yes contract. The No side is "
        "dropped. Leave this unmapped otherwise.",
    ),
    (
        "half_or_oddeven_corners",
        _has_half_corners,
        "Half-corners and odd/even corners have no Optic market. Leave unmapped.",
    ),
    (
        "doubles",
        _has_doubles,
        "Doubles are out of scope and are not mapped.",
    ),
    (
        "to_advance",
        _has_to_advance,
        "To-advance is expected residual unless this cup wires that Optic market.",
    ),
    (
        "esports_map_or_prop",
        _has_esports_prop,
        "Esports map/round props are expected residual.",
    ),
    (
        "period_market",
        _has_period_market,
        "Period markets (quarters/halves in the slug) are expected residual unless that league wires them.",
    ),
)


def _poly_yes_only_no_residual(row: dict[str, Any]) -> bool:
    """Polymarket THREE_WAY_FIXED / Yes-only matchers — not Kalshi GAME No."""
    platform = str(row.get("platform") or "").lower()
    return not platform.startswith("kalshi")


def _shape_reasons(row: dict[str, Any]) -> list[dict[str, Any]]:
    blob = _blob(row)
    key = str(row.get("key") or "")
    found = [_reason(code, text) for code, hit, text in _SHAPES if hit(blob, key)]
    if found:
        return found
    if _outcome(row) in {"no", "no."} and _poly_yes_only_no_residual(row):
        return [
            _reason(
                "yes_only_no",
                "Polymarket Yes/No: the matcher emits the Yes contract only. This No leg is expected residual.",
            )
        ]
    return []


def _participant_crypto_ids(row: dict[str, Any]) -> list[str]:
    raw = row.get("crypto_ids")
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw if value]


def _context_reasons(row: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any(item.get("kind") == "league" for item in items):
        return []
    platform = str(row.get("platform") or "").lower()
    if platform == "crypto":
        if not str(row.get("league") or "").strip() and not _participant_crypto_ids(row):
            return [
                _reason(
                    "crypto_contract_no_league",
                    "This NX symbol is the contract id, not a participant crypto_id. "
                    "There is no tip league on this row to attach an alias pin to.",
                )
            ]
        return []
    if str(row.get("league") or "").strip():
        return []
    return [
        _reason(
            "league_not_on_tip",
            "This competition is not on the mapping tip, so there is no Optic league "
            "to attach it to. Leave it, or onboard the league first.",
        )
    ]


def _item_reasons(
    row: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    has_fixes: bool,
    has_shape: bool,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    league = next((item for item in items if item.get("kind") == "league"), None)
    if league is not None and not league.get("mapped"):
        out.append(
            _reason(
                "league_not_on_tip",
                "This league is not on the mapping tip, so there is no Optic book to "
                "attach it to. Leave it, or onboard the league first.",
            )
        )
    if has_fixes:
        out.append(
            _reason(
                "missing_tip_fix",
                "A grey badge is missing on the mapping tip. Select it and Add to cart.",
                actionable=True,
            )
        )
        return out
    if has_shape:
        return out
    return out
