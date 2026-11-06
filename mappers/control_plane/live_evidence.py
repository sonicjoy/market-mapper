"""Live exchange evidence for alias verify (hard-block on miss)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from mappers.alias_kinds import CRYPTO_ID_KINDS, OPTIC_ID_KINDS
from mappers.control_plane.evidence_format import (
    optic_competitor_ref,
    optic_fixture_ref,
)
from mappers.control_plane.gap_fix_ai_suggest import is_ai_suggest_pin
from mappers.control_plane.gap_optic_cache import cached_optic_fixtures, optic_horizon_hours
from mappers.control_plane.live_evidence_names import name_ok
from mappers.control_plane.live_evidence_txodds import TXODDS_BOOK, TXODDS_ID_KINDS, txodds_team_pin
from mappers.control_plane.live_evidence_types import EvidenceFetchers, EvidenceHit
from mappers.control_plane.suggest_aliases import fetch_optic_fixtures
from mappers.crypto_meta import harvest_exception_key

_crypto_row_batch: ContextVar[dict[str, dict[str, Any]] | None] = ContextVar(
    "_crypto_row_batch",
    default=None,
)

# Re-export for existing importers.
__all__ = [
    "EvidenceFetchers",
    "EvidenceHit",
    "apply_evidence_fn",
    "collect_pins_evidence",
    "crypto_row_cache_scope",
    "probe_pin_evidence",
]


@contextmanager
def crypto_row_cache_scope():
    """Per-batch crypto catalogue cache (gap-propose verify retries only)."""
    token = _crypto_row_batch.set({})
    try:
        yield
    finally:
        _crypto_row_batch.reset(token)


def probe_pin_evidence(
    store: Any,
    *,
    league: str,
    sportsbook: str,
    alias_kind: str,
    alias_value: str,
    canonical_name: str,
    raw_paste: str = "",
    fetchers: EvidenceFetchers | None = None,
) -> EvidenceHit:
    """Confirm one alias pin against live Optic / crypto.com / the TxODDS team list."""
    book = sportsbook.strip().lower()
    kind = alias_kind.strip().lower()
    value = alias_value.strip()
    name = canonical_name.strip()
    fx = fetchers or EvidenceFetchers()
    if book == "optic" and kind in OPTIC_ID_KINDS:
        return _optic_pin(store, league, value, name, fx)
    if book == "crypto.com" and kind in CRYPTO_ID_KINDS:
        return _crypto_pin(store, value, name, league, fx)
    if book == TXODDS_BOOK and kind in TXODDS_ID_KINDS:
        return txodds_team_pin(store, league, value, name, fx)
    return EvidenceHit()


def apply_evidence_fn(
    evidence_fn: Any,
    store: Any,
    *,
    league: str,
    sportsbook: str,
    alias_kind: str,
    alias_value: str,
    canonical_name: str,
    raw_paste: str = "",
) -> tuple[list[str], list[str]]:
    """Run a wired probe; return (refs, blockers)."""
    if evidence_fn is None:
        return [], []
    hit = evidence_fn(
        store,
        league=league,
        sportsbook=sportsbook,
        alias_kind=alias_kind,
        alias_value=alias_value,
        canonical_name=canonical_name,
        raw_paste=raw_paste,
    )
    if hit.blocker:
        return [], [hit.blocker]
    return list(hit.refs), []


def collect_pins_evidence(
    store: Any,
    aliases: Sequence[Any],
    *,
    fetchers: EvidenceFetchers | None = None,
    probe: Callable[..., EvidenceHit] | None = None,
) -> tuple[list[str], list[str]]:
    """Probe every alias pin; return (refs, blockers)."""
    if probe is None:
        return [], []
    impl = probe
    refs: list[str] = []
    blockers: list[str] = []
    seen: set[str] = set()
    for ea in aliases:
        if is_ai_suggest_pin(ea):
            continue
        name = str(ea.canonical_name or ea.canonical_key or "")
        for index, pin in enumerate(getattr(ea, "aliases", None) or []):
            if getattr(pin, "remove", False):
                continue
            hit = impl(
                store,
                league=str(ea.league or ""),
                sportsbook=pin.sportsbook,
                alias_kind=pin.alias_kind,
                alias_value=pin.alias_value,
                canonical_name=name,
                fetchers=fetchers,
            )
            if hit.blocker and not _soft_optic_miss(index, pin, hit.blocker):
                blockers.append(hit.blocker)
            for ref in hit.refs:
                if ref not in seen:
                    seen.add(ref)
                    refs.append(ref)
    return refs, blockers


def _soft_optic_miss(index: int, pin: Any, blocker: str) -> bool:
    """Horizon miss on a secondary Optic pin must not kill the card."""
    if index == 0:
        return False
    if str(getattr(pin, "sportsbook", "") or "").lower() != "optic":
        return False
    return "not in active" in blocker


def _name_ok(left: str, right: str, league: str) -> bool:
    """Compatibility shim for tests that import _name_ok from this module."""
    return name_ok(left, right, league)


def _optic_pin(
    store: Any,
    league: str,
    oid: str,
    name: str,
    fx: EvidenceFetchers,
) -> EvidenceHit:
    """Active fixture competitor id + name."""
    tip = _optic_tip(store, league)
    if tip is None:
        return EvidenceHit(blocker=f"No Optic league id on tip for {league}.")
    horizon = optic_horizon_hours(tip)
    fetch_fn = fx.optic_fixtures or fetch_optic_fixtures
    fixtures: list[dict[str, Any]] = []
    errors: list[str] = []
    for lid in _optic_league_ids(tip):
        try:
            fixtures.extend(cached_optic_fixtures(
                lid,
                horizon_hours=horizon,
                fetch_fn=fetch_fn,
            ))
        except Exception as exc:  # noqa: BLE001 — Optic key/network miss
            errors.append(f"{lid}: {exc}"[:80])
    if not fixtures and errors:
        return EvidenceHit(
            blocker=f"Optic fixture lookup failed for {league}: {errors[0]}"[:160],
        )
    return _optic_in_fixtures(fixtures, oid, name, league)


def _optic_tip(store: Any, league: str) -> Any | None:
    """Tip league row for live Optic verify, or None."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "leagues_for"):
        return None
    tip = next((r for r in store.leagues_for(rid) if r.league == league), None)
    if tip is None or not str(tip.optic_league_id or "").strip():
        return None
    return tip


def _optic_league_ids(tip: Any) -> list[str]:
    """Primary Optic league id plus ``extra_optic_league_ids`` (e.g. Davis Cup on ATP)."""
    extra = [str(x).strip() for x in (tip.extra_optic_league_ids or [])]
    primary = str(tip.optic_league_id or "").strip()
    return [lid for lid in [primary, *extra] if lid]


def _optic_in_fixtures(
    fixtures: list[dict[str, Any]],
    oid: str,
    name: str,
    league: str,
) -> EvidenceHit:
    """First competitor whose id matches and whose name aligns."""
    want = oid.strip()
    for game in fixtures:
        for side in ("home_competitors", "away_competitors"):
            for comp in game.get(side) or []:
                cid = str(comp.get("id") or "").strip()
                label = str(comp.get("name") or "").strip()
                if cid != want:
                    continue
                if not name_ok(name, label, league):
                    return EvidenceHit(
                        blocker=f"Optic {oid} is {label!r}, not {name!r}.",
                    )
                return EvidenceHit(refs=_optic_identity_hit(oid, label, comp, game))
    return EvidenceHit(
        blocker=f"Optic competitor {oid} not in active {league} fixtures.",
    )


def _optic_identity_hit(
    oid: str, label: str, comp: dict[str, Any], game: dict[str, Any],
) -> tuple[str, ...]:
    """Id, name, abbr, and fixture — skip exchange questions."""
    refs = [optic_competitor_ref(oid, label)]
    fx = optic_fixture_ref(game)
    if fx:
        refs.append(fx)
    if label:
        refs.append(f"optic:name:{label}")
    abbr = str(comp.get("abbreviation") or "").strip()
    if abbr:
        refs.append(f"optic:abbr:{abbr}")
    return tuple(refs)


def _crypto_pin(
    store: Any, cid: str, name: str, league: str, fx: EvidenceFetchers,
) -> EvidenceHit:
    """Catalogue row for this pin (team home/away id or player ``meta_player_id``)."""
    lookup = fx.crypto_row or _batch_crypto_row
    try:
        row = lookup(cid)
    except Exception as exc:  # noqa: BLE001 — BQ miss
        return EvidenceHit(
            blocker=f"crypto.com catalogue lookup failed for {league}: {exc}"[:160],
        )
    if not row.get("seen"):
        return EvidenceHit(blocker=f"crypto.com id {cid} not in catalogue.")
    label = _crypto_side_name(row, cid)
    if not label or not _crypto_name_ok(store, league, name, label, row):
        shown = label or str(row.get("meta_name") or "unknown")
        return EvidenceHit(
            blocker=f"crypto.com {cid} is live as {shown!r}, not {name!r}.",
        )
    refs = [f"crypto_id:{cid}", f"crypto:name:{label}"]
    if label.strip() != name.strip():
        refs.append(f"crypto:tip:{name}")
    symbol = str(row.get("symbol") or "")
    if symbol:
        # cid-tagged: a batch flattens every pin's refs into one list, and a
        # bare symbol carries no name to attribute it back to this pin.
        refs.append(f"crypto:symbol:{cid}:{symbol}")
    return EvidenceHit(refs=tuple(refs))


def _crypto_name_ok(
    store: Any, league: str, name: str, label: str, row: dict[str, Any],
) -> bool:
    """True when the catalogue label is this tip name, or a registered feed alias."""
    partner = _crypto_partner_name(row, label)
    if name_ok(name, label, league, partner=partner):
        return True
    key = harvest_exception_key(league, label)
    if not key:
        return False
    return _tip_name_is(store, league, key, name)


def _tip_name_is(store: Any, league: str, key: str, name: str) -> bool:
    """True when the activated tip names this canonical with ``name``."""
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "entities_for"):
        return False
    for ent in store.entities_for(rid):
        if getattr(ent, "tombstone", False):
            continue
        if str(ent.league) != league or str(ent.canonical_key) != key:
            continue
        return str(ent.canonical_name or ent.canonical_key) == name
    return False


def _crypto_side_name(row: dict[str, Any], cid: str) -> str:
    """Participant name for this crypto id (team side or player prop)."""
    if str(row.get("home_id") or "") == cid:
        return str(row.get("home_name") or "")
    if str(row.get("away_id") or "") == cid:
        return str(row.get("away_name") or "")
    if str(row.get("player_id") or "") == cid:
        return str(row.get("participant") or "")
    return str(row.get("meta_name") or "")


def _crypto_partner_name(row: dict[str, Any], label: str) -> str:
    """Other catalogue participant on the same SecurityDef row."""
    home = str(row.get("home_name") or "").strip()
    away = str(row.get("away_name") or "").strip()
    want = label.strip()
    if home and away:
        if home.casefold() == want.casefold():
            return away
        if away.casefold() == want.casefold():
            return home
    return ""


def _batch_crypto_row(cid: str) -> dict[str, Any]:
    """Reuse catalogue rows within one ``crypto_row_cache_scope`` batch."""
    cache = _crypto_row_batch.get()
    if cache is None:
        return _query_crypto_id(cid)
    if cid not in cache:
        cache[cid] = _query_crypto_id(cid)
    return cache[cid]


def _query_crypto_id(cid: str) -> dict[str, Any]:
    """Latest security_def row for a team external id or player ``meta_player_id``."""
    from google.cloud import bigquery

    from BigQuery.client import CRYPTO_SECURITY_DEF_TABLE, ro_client, ro_query

    sql = _CRYPTO_ID_SQL.replace("{table}", CRYPTO_SECURITY_DEF_TABLE)
    job = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("cid", "STRING", cid)],
    )
    rows = list(ro_query(ro_client(), sql, job_config=job))
    if not rows:
        return {"seen": False, "id": cid}
    row = rows[0]
    return {
        "seen": True,
        "symbol": str(getattr(row, "symbol", "") or ""),
        "meta_name": str(getattr(row, "meta_name", "") or ""),
        "home_id": str(getattr(row, "home_id", "") or ""),
        "away_id": str(getattr(row, "away_id", "") or ""),
        "home_name": str(getattr(row, "home_name", "") or ""),
        "away_name": str(getattr(row, "away_name", "") or ""),
        "player_id": str(getattr(row, "player_id", "") or ""),
        "participant": str(getattr(row, "participant", "") or ""),
    }


_CRYPTO_ID_SQL = """
select
  symbol,
  meta_name,
  cast(meta_external_home_id as string) as home_id,
  cast(meta_external_away_id as string) as away_id,
  meta_home_participant as home_name,
  meta_away_participant as away_name,
  cast(meta_player_id as string) as player_id,
  meta_participant as participant
from `{table}`
where cast(meta_external_home_id as string) = @cid
   or cast(meta_external_away_id as string) = @cid
   or cast(meta_player_id as string) = @cid
qualify row_number() over (order by publish_time desc) = 1
"""
