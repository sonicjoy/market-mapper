"""Fixture / alias / market stack for Unmapped and Missing Why."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mappers.control_plane.chat_tools_crypto_gap import (
    _catalogue_ids,
    _horizon,
    _hours_to_kick,
    _optic_match,
    _time_kind,
)
from mappers.control_plane.console_unmapped_markets import market_observation
from mappers.control_plane.gap_market_bind import is_name_match_book


def _layer_reason(code: str, text: str, *, actionable: bool = False) -> dict[str, Any]:
    """One Why reason dict (same shape as console_unmapped_explain)."""
    return {"code": code, "text": text, "actionable": actionable}


def mapping_stack_reasons(
    row: dict[str, Any],
    store: Any | None,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ordered Optic fixture → alias → market reasons for map-everything Why."""
    platform = str(row.get("platform") or "").lower()
    league = str(row.get("league") or "").strip()
    if not league and not any(item.get("kind") == "league" and item.get("mapped") for item in items):
        return []
    out: list[dict[str, Any]] = []
    out.extend(_fixture_layers(row, store, league))
    out.extend(_alias_layers(row, platform, items))
    out.extend(_market_layers(row, store, league, items))
    return out


def _fixture_layers(row: dict[str, Any], store: Any | None, league: str) -> list[dict[str, Any]]:
    """Optic fixture bind status for crypto catalogue rows."""
    platform = str(row.get("platform") or "").lower()
    if platform != "crypto" or store is None or not league:
        return []
    cat = _crypto_catalogue_fields(row)
    if not cat.get("meta_name") and not _catalogue_ids(cat):
        return []
    horizon = _horizon(store, [league])
    timed = _time_kind(_hours_to_kick(cat, datetime.now(UTC)), horizon)
    clock = _clock_fixture_reason(timed, horizon)
    if clock is not None:
        return [clock]
    return [_optic_bind_reason(_optic_match(store, [league], cat, row.get("fixtures_fn")))]


def _clock_fixture_reason(timed: str | None, horizon: float) -> dict[str, Any] | None:
    """Horizon and stale-kickoff residuals before an Optic lookup."""
    if timed == "outside_horizon":
        return _layer_reason(
            "outside_optic_horizon",
            f"Kickoff is outside the {int(horizon)}h Optic fixture horizon — wait for lines, not a tip pin.",
        )
    if timed == "completed_stale":
        return _layer_reason(
            "completed_stale",
            "Kickoff is in the past — stale catalogue symbol, not an actionable mapping gap.",
        )
    return None


def _optic_bind_reason(optic: dict[str, Any] | None) -> dict[str, Any]:
    """Turn one Optic match payload into a fixture reason."""
    if optic and optic.get("error"):
        return _layer_reason(
            "missing_optic_fixture",
            f"Could not load Optic fixtures ({optic.get('error')}).",
        )
    if optic and optic.get("fixture_id"):
        home = optic.get("home") or "?"
        away = optic.get("away") or "?"
        return _layer_reason(
            "optic_fixture_present",
            f"Optic fixture matched: {away} @ {home} ({optic.get('fixture_id')}).",
        )
    if optic and optic.get("name_mismatch"):
        return _layer_reason(
            "missing_optic_fixture",
            "Catalogue fixture names do not match a unique Optic fixture on kickoff day.",
        )
    return _layer_reason(
        "missing_optic_fixture",
        "No Optic fixture in horizon for this catalogue fixture (bind fixture before aliases/markets).",
    )


def _crypto_catalogue_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Build catalogue-shaped dict for Optic match (row fields + optional inject)."""
    fixture_title = str(row.get("fixture") or "").strip()
    if " — " in fixture_title:
        fixture_title = fixture_title.split(" — ", 1)[0].strip()
    kick = str(row.get("start_date") or row.get("kickoff") or row.get("meta_event_date") or "")
    ids = row.get("crypto_ids")
    id_list = [str(v) for v in ids] if isinstance(ids, list) else []
    home_id = str(row.get("home_id") or "")
    away_id = str(row.get("away_id") or "")
    if not home_id and not away_id and len(id_list) >= 2:
        home_id, away_id = id_list[0], id_list[1]
    injected = row.get("catalogue")
    if isinstance(injected, dict):
        return {**injected, "meta_name": injected.get("meta_name") or fixture_title, "meta_event_date": kick}
    return {
        "meta_name": fixture_title,
        "meta_event_date": kick,
        "home_id": home_id,
        "away_id": away_id,
    }


def _alias_layers(
    row: dict[str, Any],
    platform: str,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Participant alias presence on the mapping tip."""
    aliases = [item for item in items if item.get("kind") == "alias"]
    if not aliases:
        if platform == "crypto" and str(row.get("league") or "").strip():
            if not _catalogue_ids(_crypto_catalogue_fields(row)):
                return [
                    _layer_reason(
                        "missing_alias",
                        "Participant crypto_id is not in catalogue metadata — "
                        "cannot pin aliases until upstream ids land.",
                    )
                ]
            return [
                _layer_reason(
                    "missing_alias",
                    "Participant crypto_id aliases are not on the mapping tip.",
                )
            ]
        return []
    unmapped = [item for item in aliases if not item.get("mapped")]
    if not unmapped:
        labels = ", ".join(str(item.get("label") or "") for item in aliases[:4])
        return [_layer_reason("alias_present", f"Participant aliases on tip: {labels}.")]
    fixable = [item for item in unmapped if item.get("fixable")]
    labels = ", ".join(str(item.get("label") or "") for item in unmapped[:4])
    if fixable:
        return [
            _layer_reason(
                "missing_alias",
                f"Missing alias on tip: {labels}.",
                actionable=True,
            )
        ]
    if platform == "polymarket":
        return [
            _layer_reason(
                "missing_alias",
                "Polymarket team names need an Optic competitor match before an alias pin is actionable.",
            )
        ]
    return [_layer_reason("missing_alias", f"Missing alias on tip: {labels}.")]


def _market_layers(
    row: dict[str, Any],
    store: Any | None,
    league: str,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Market-rule / Optic market bind status for this contract."""
    rules = [item for item in items if item.get("kind") == "market_rule"]
    if rules:
        return [_badge_market_reason(rules[0])]
    return _unbound_market_reasons(row, store, league)


def _badge_market_reason(rule: dict[str, Any]) -> dict[str, Any]:
    """Reason from an existing market-rule badge."""
    label = str(rule.get("label") or "market rule")
    if rule.get("mapped"):
        return _layer_reason("market_rule_present", f"Market rule on tip: {label}.")
    if rule.get("fixable"):
        return _layer_reason(
            "missing_market_rule",
            f"Missing market rule on tip: {label}.",
            actionable=True,
        )
    return _layer_reason(
        "missing_market_rule",
        f"Market rule {label} is not on the tip (Optic may not price this contract yet).",
    )


def _unbound_market_reasons(
    row: dict[str, Any],
    store: Any | None,
    league: str,
) -> list[dict[str, Any]]:
    """Reason when the kernel produced no market-rule badge."""
    platform = str(row.get("platform") or "").lower()
    book = {
        "kalshi": "kalshi",
        "crypto": "crypto.com",
        "polymarket": "polymarket",
        "prophetx": "px",
    }.get(platform, platform)
    contract = str(row.get("contract_type") or "").strip()
    if not contract or store is None or not league:
        return []
    if platform == "crypto" and not is_name_match_book("crypto.com"):
        return []
    obs = market_observation(row, store, league, book)
    if obs is None:
        return [
            _layer_reason(
                "missing_market_rule",
                f"No tip market rule for {contract} @ {row.get('market_group') or '?'}"
                " (needs_code or no live Optic market).",
            )
        ]
    return [
        _layer_reason(
            "missing_market_rule",
            f"Missing market rule for {contract} — draft failed (check Optic census / overlay).",
        )
    ]
