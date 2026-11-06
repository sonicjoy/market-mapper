"""Draft entity_alias pins from crypto gap probe rows."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.crypto_alias_correct import pins_for_crypto_id
from mappers.control_plane.entity_types import match_entity_type_for_league
from mappers.control_plane.gap_fix_crypto_onboard import try_crypto_league_onboard
from mappers.control_plane.gap_fix_onboard import stamp_gap_harvest_pin
from mappers.control_plane.gap_fix_optic_merge import (
    OpticDrafted,
    pin_optic_id,
    register_optic_draft,
)
from mappers.control_plane.gap_fix_skip import (
    crypto_id_labels as _crypto_id_labels,
    partner_catalogue_label as _partner_label,
)
from mappers.control_plane.gap_fix_skip import (
    probe_skip as _probe_skip,
)
from mappers.control_plane.gap_fix_tip import TipLeagueIndex, league_tip

_HARD_SKIP = frozenset({
    "missing_optic", "title_miss", "out_of_scope", "disambig", "outside_horizon",
})
_CRYPTO_SKIP = _HARD_SKIP | {
    "catalogue_miss",
    "tournament_future",
    "completed_stale",
    "outside_horizon",
    "name_mismatch",
    "collision",
    "unmapped",
}


def _tip_league_rows(store: Any) -> list[Any]:
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return []
    return list(store.leagues_for(rid))


def _draft_crypto_id_pins(
    store: Any,
    row: dict[str, Any],
    league: str,
    optic: dict[str, Any],
    ids: list[str],
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    tips: dict[str, TipLeagueIndex] | None,
    used_by_league: dict[str, set[str]] | None,
    optic_drafted: OpticDrafted | None,
) -> None:
    probe_tip = {str(t.get("crypto_id") or ""): t for t in (row.get("tip") or [])}
    evidence = list(row.get("evidence_refs") or [])
    entity_type = match_entity_type_for_league(store, league)
    indexed = league_tip(store, league, tips)
    used = (used_by_league or {}).setdefault(league, set(indexed.used))
    labels = _crypto_id_labels(row, ids)
    for cid, label in zip(ids, labels, strict=True):
        partner = _partner_label(labels, label)
        drafted = pins_for_crypto_id(
            league, cid, label, optic, probe_tip, used, entity_type, evidence,
            optic_drafted=optic_drafted, indexed=indexed,
            partner_label=partner,
        )
        for pin in drafted:
            _accept_crypto_pin(pin, pins, seen, used, optic_drafted, row)


def collect_crypto_probe_pins(
    store: Any,
    row: dict[str, Any],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    optic_drafted: OpticDrafted | None = None,
    tips: dict[str, TipLeagueIndex] | None = None,
    used_by_league: dict[str, set[str]] | None = None,
) -> None:
    """Draft crypto_id pins from one crypto gap probe row."""
    kind = str(row.get("kind") or "")
    if kind == "already_mapped" or row.get("mapped_rows"):
        skipped.append(_probe_skip(row, "already_mapped"))
        return
    if kind == "league_not_wired":
        if try_crypto_league_onboard(
            store, row, pins, skipped, seen, _tip_league_rows(store), None, {},
        ):
            return
        skipped.append(_probe_skip(row, kind))
        return
    if kind in _CRYPTO_SKIP:
        skipped.append(_probe_skip(row, kind or "skip"))
        return
    optic = row.get("optic") if isinstance(row.get("optic"), dict) else None
    league = str(row.get("league") or "")
    ids = [str(c) for c in (row.get("crypto_ids") or []) if c]
    if not league or not optic or not ids:
        skipped.append(_probe_skip(row, kind or "incomplete"))
        return
    _draft_crypto_id_pins(
        store, row, league, optic, ids, pins, seen, tips, used_by_league, optic_drafted,
    )


def _accept_crypto_pin(
    pin: dict[str, Any],
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    used: set[str],
    optic_drafted: OpticDrafted | None,
    row: dict[str, Any],
) -> None:
    """Keep one drafted crypto pin, including a correction remove."""
    key = (pin["league"], pin["canonical_key"], pin["aliases"][0]["alias_value"])
    if key in seen:
        return
    seen.add(key)
    used.add(str(pin["canonical_key"]).upper())
    register_optic_draft(
        optic_drafted, pin["league"], pin_optic_id(pin), str(pin["canonical_key"]),
    )
    symbol = str(row.get("symbol") or row.get("gap_key") or "")
    stamp_gap_harvest_pin(pin, book="crypto", key=symbol)
    pins.append(pin)
