"""Crypto id on the wrong Optic side drafts a correction; mapping absence stays unmapped."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import pytest

from mappers.control_plane.batch_apply import apply_batch, dry_run_batch
from mappers.control_plane.chat_tools_crypto_gap import run_probe_crypto_gap
from mappers.control_plane.dry_run import thin_dry_run
from mappers.control_plane.gap_fix_draft import collect_crypto_probe_pins
from mappers.control_plane.gap_inventory import RfqGapItem
from mappers.control_plane.gap_ledger import TERMINAL_OUTCOMES, build_outcomes
from mappers.control_plane.live_evidence_types import EvidenceHit
from mappers.control_plane.models import AliasPin, BatchChangesPayload, EntityAliasPayload
from mappers.control_plane.pin_flow import alias_from_pin, draft_and_verify
from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.control_plane.store import InMemoryStore

_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
_LUCAS_OID = "93AF99AE3468DCF32"
_OLI_OID = "9C112155A4500"
_LUCAS_CID = "1666578"
_OLI_CID = "579857"

_UNMAPPED_SYMBOLS = [
    "NX.F.OPT.TENNIS-0120-260928-M.0.1.1.20261231",
    "NX.F.OPT.TENNIS-0026-260928-M.0.1.2.20261231",
    "NX.F.OPT.MLB-00001-260929-M.0.1.149.20261130",
    "NX.F.OPT.WNBA-00001-260929-M.0.1.23.20261230",
    "NX.F.OPT.NFL-00001-261001-M.0.1.212.20270301",
    "NX.F.OPT.NFL-00001-261001-M.0.1.590.20270301",
]


def _crypto_ex(meta: str, grouping: str | None = None) -> dict[str, Any]:
    settings: dict[str, Any] = {"league": meta}
    if grouping:
        settings["sport_grouping"] = grouping
    return {
        "sportsbook": "crypto.com",
        "enabled": True,
        "parser_profile": "crypto_generic_v1",
        "source_league_id": meta,
        "settings": settings,
    }


def _league(
    slug: str, meta: str, optic: str, *, grouping: str | None = None, sport: str = "soccer",
) -> LeagueRow:
    return LeagueRow(
        league=slug,
        sport=sport,
        optic_league_id=optic,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[_crypto_ex(meta, grouping)],
    )


def _ent(
    league: str, key: str, name: str, aliases: list[dict[str, Any]], *, entity_type: str = "team",
) -> EntityRow:
    return EntityRow(
        league=league,
        entity_type=entity_type,
        canonical_key=key,
        canonical_name=name,
        aliases=aliases,
    )


def _id(book: str, value: str) -> dict[str, str]:
    return {"sportsbook": book, "alias_kind": "external_id", "alias_value": value}


def _store(entities: list[EntityRow], leagues: list[LeagueRow]) -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(rule_set_id="S0", entities=entities, leagues=leagues, activate=True)
    return store


def _challenger_store(*, lucas_owns_crypto: bool) -> InMemoryStore:
    lucas_aliases = [_id("optic", _LUCAS_OID)]
    if lucas_owns_crypto:
        lucas_aliases.append(_id("crypto.com", _LUCAS_CID))
    sil_aliases = [_id("optic", "oid-other-silva")]
    if not lucas_owns_crypto:
        sil_aliases.append(_id("crypto.com", _LUCAS_CID))
    return _store(
        [
            _ent("atp_challenger", "LUCAS", "Lucas Andrade Da Silva", lucas_aliases),
            _ent("atp_challenger", "SIL", "Another Silva", sil_aliases),
            _ent(
                "atp_challenger", "OLI", "Genaro Alberto Olivieri",
                [_id("optic", _OLI_OID), _id("crypto.com", _OLI_CID)],
            ),
        ],
        [
            _league("atp", "ATP", "atp", grouping="TENNIS", sport="tennis"),
            _league(
                "atp_challenger", "ATP", "atp_challenger", grouping="TENNIS", sport="tennis",
            ),
        ],
    )


def _optic_pair(home: str, home_id: str, away: str, away_id: str) -> dict[str, Any]:
    return {
        "id": "fx-pair",
        "start_date": "2026-09-29T15:00:00Z",
        "home_competitors": [{"id": home_id, "name": home}],
        "away_competitors": [{"id": away_id, "name": away}],
    }


def _cat(symbol: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "ok": True,
        "seen": True,
        "symbol": symbol,
        "meta_name": "Genaro Alberto Olivieri @ Lucas Da Silva",
        "meta_league": "ATP",
        "meta_event_date": "2026-09-29T17:00:00+00:00",
        "contract_type": "Moneyline",
        "home_id": _LUCAS_CID,
        "away_id": _OLI_CID,
        "home_name": "Lucas Da Silva",
        "away_name": "Genaro Alberto Olivieri",
    }
    row.update(overrides)
    return row


def _challenger_fixtures(optic_league_id: str, **_k: Any) -> list[dict[str, Any]]:
    if optic_league_id != "atp_challenger":
        return []
    return [
        _optic_pair("Lucas Andrade Da Silva", _LUCAS_OID, "Genaro Alberto Olivieri", _OLI_OID),
    ]


def _probe(store: InMemoryStore, symbol: str, **args: Any) -> dict[str, Any]:
    args.setdefault("catalogue_fn", lambda s: _cat(s))
    args.setdefault("fixtures_fn", _challenger_fixtures)
    args.setdefault("now", _NOW)
    args["symbol"] = symbol
    return run_probe_crypto_gap(store, args)["results"][0]


def test_wrong_crypto_owner_is_alias_mismatch() -> None:
    row = _probe(
        _challenger_store(lucas_owns_crypto=False),
        "NX.F.OPT.TENNIS-0026-260928-M.0.1.1.20261231",
    )
    assert row["kind"] == "alias_mismatch"
    assert row["mapped_rows"] == []
    assert row["league"] == "atp_challenger"


def test_correction_card_moves_crypto_id_onto_optic_side() -> None:
    store = _challenger_store(lucas_owns_crypto=False)
    row = _probe(store, "NX.F.OPT.TENNIS-0026-260928-M.0.1.2.20261231")
    pins: list[dict[str, Any]] = []
    collect_crypto_probe_pins(store, row, pins, [], set())
    removes = [pin for pin in pins if pin["aliases"][0].get("remove")]
    claims = [pin for pin in pins if pin.get("reassign")]
    assert [pin["canonical_key"] for pin in removes] == ["SIL"]
    assert removes[0]["aliases"][0]["alias_value"] == _LUCAS_CID
    assert [pin["canonical_key"] for pin in claims] == ["LUCAS"]
    assert claims[0]["aliases"][0]["alias_value"] == _LUCAS_CID
    staged = draft_and_verify(store, [row], "crypto.com")
    assert staged["ok"] is True
    keys = [pin["canonical_key"] for pin in staged["pins"]]
    assert keys[0] == "SIL"
    assert "LUCAS" in keys
    rid = store.current_rule_set_id
    assert rid
    entities = list(store.entities_for(rid))
    dry = thin_dry_run(entities, alias_from_pin(claims[0]))
    assert dry["ok"] is True


def test_batch_move_survives_add_before_remove_and_legacy_kind() -> None:
    """Approve must move 1660578 even when the add is listed first or the tip kind is old."""
    cid = "1660578"
    legacy = {"sportsbook": "crypto.com", "alias_kind": "crypto_id", "alias_value": cid}
    optic = {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "oid-joao"}
    store = _store(
        [
            _ent(
                "atp_challenger", "SIL2", "Joao Lucas Da Silva", [optic, legacy],
                entity_type="player",
            ),
            _ent(
                "atp_challenger", "LAD57", "Lucas Andrade Da Silva",
                [{"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "oid-lucas"}],
                entity_type="player",
            ),
        ],
        [_league("atp_challenger", "ATP", "atp_challenger", grouping="TENNIS", sport="tennis")],
    )
    remove = EntityAliasPayload(
        league="atp_challenger",
        canonical_key="SIL2",
        canonical_name="Joao Lucas Da Silva",
        entity_type="team",
        aliases=[AliasPin(
            sportsbook="crypto.com", alias_kind="external_id", alias_value=cid, remove=True,
        )],
    )
    claim = EntityAliasPayload(
        league="atp_challenger",
        canonical_key="LAD57",
        canonical_name="Lucas Andrade Da Silva",
        entity_type="team",
        reassign=False,
        aliases=[AliasPin(sportsbook="crypto.com", alias_kind="external_id", alias_value=cid)],
    )
    payload = BatchChangesPayload(entity_aliases=[claim, remove])
    rid = store.current_rule_set_id
    assert rid
    dry = dry_run_batch(store, rid, payload)
    assert dry["ok"] is True, dry["blockers"]
    entities, _leagues, _rules = apply_batch(store, rid, payload)
    by_key = {ent.canonical_key: ent for ent in entities if ent.league == "atp_challenger"}
    assert [ent.entity_type for ent in by_key.values()] == ["player", "player"]
    joao = [a["alias_value"] for a in by_key["SIL2"].aliases if a["sportsbook"] == "crypto.com"]
    lucas = [a["alias_value"] for a in by_key["LAD57"].aliases if a["sportsbook"] == "crypto.com"]
    assert joao == []
    assert lucas == [cid]


def test_blocked_reassign_drops_the_paired_remove() -> None:
    store = _challenger_store(lucas_owns_crypto=False)
    row = _probe(store, "NX.F.OPT.TENNIS-0026-260928-M.0.1.1.20261231")

    def block(*_a: Any, **_k: Any) -> EvidenceHit:
        return EvidenceHit(blocker="crypto.com 1666578 does not name Lucas Andrade Da Silva")

    staged = draft_and_verify(store, [row], "crypto.com", probe=block)
    assert staged["pins"] == []
    assert staged["ok"] is False
    assert staged["blockers"]


def test_extra_owner_is_removed_when_optic_side_already_holds_id() -> None:
    lucas = [_id("optic", _LUCAS_OID), _id("crypto.com", _LUCAS_CID)]
    sil = [_id("optic", "oid-other-silva"), _id("crypto.com", _LUCAS_CID)]
    store = _store(
        [
            _ent("atp_challenger", "LUCAS", "Lucas Andrade Da Silva", lucas),
            _ent("atp_challenger", "SIL", "Another Silva", sil),
            _ent(
                "atp_challenger", "OLI", "Genaro Alberto Olivieri",
                [_id("optic", _OLI_OID), _id("crypto.com", _OLI_CID)],
            ),
        ],
        [
            _league("atp", "ATP", "atp", grouping="TENNIS", sport="tennis"),
            _league(
                "atp_challenger", "ATP", "atp_challenger", grouping="TENNIS", sport="tennis",
            ),
        ],
    )
    row = _probe(store, "NX.F.OPT.TENNIS-0026-260928-M.0.1.1.20261231")
    assert row["kind"] == "alias_mismatch"
    staged = draft_and_verify(store, [row], "crypto.com")
    assert staged["ok"] is True
    assert [pin["canonical_key"] for pin in staged["pins"]] == ["SIL"]
    assert staged["pins"][0]["aliases"][0]["remove"] is True


def test_two_owners_without_optic_keep_stay_collision() -> None:
    store = _store(
        [
            _ent("atp_challenger", "AAA", "Someone", [_id("crypto.com", _LUCAS_CID)]),
            _ent("atp_challenger", "BBB", "Someone Else", [_id("crypto.com", _LUCAS_CID)]),
            _ent(
                "atp_challenger", "OLI", "Genaro Alberto Olivieri",
                [_id("optic", _OLI_OID), _id("crypto.com", _OLI_CID)],
            ),
        ],
        [
            _league("atp", "ATP", "atp", grouping="TENNIS", sport="tennis"),
            _league(
                "atp_challenger", "ATP", "atp_challenger", grouping="TENNIS", sport="tennis",
            ),
        ],
    )
    row = _probe(store, "NX.F.OPT.TENNIS-0026-260928-M.0.1.1.20261231")
    assert row["kind"] == "collision"
    pins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    collect_crypto_probe_pins(store, row, pins, skipped, set())
    assert pins == []
    assert skipped[0]["reason"] == "collision"


def test_unmapped_skip_is_terminal() -> None:
    store = _challenger_store(lucas_owns_crypto=True)
    row = _probe(store, "NX.F.OPT.TENNIS-0026-260928-M.0.1.1.20261231")
    skipped: list[dict[str, str]] = []
    collect_crypto_probe_pins(store, row, [], skipped, set())
    assert skipped[0]["reason"] == "unmapped"
    symbol = str(row["symbol"])
    item = RfqGapItem("crypto", symbol, 1)
    [outcome] = build_outcomes(
        [item], [], skipped, walked_keys={("crypto", symbol)},
    )
    assert outcome.outcome == "skipped"
    assert outcome.reason == "unmapped"
    assert outcome.outcome in TERMINAL_OUTCOMES


def test_right_owners_without_mapping_rows_stay_unmapped() -> None:
    row = _probe(
        _challenger_store(lucas_owns_crypto=True),
        "NX.F.OPT.TENNIS-0026-260928-M.0.1.1.20261231",
    )
    assert row["kind"] == "unmapped"
    pins: list[dict[str, Any]] = []
    collect_crypto_probe_pins(
        _challenger_store(lucas_owns_crypto=True), row, pins, [], set(),
    )
    assert pins == []


@pytest.mark.parametrize("symbol", _UNMAPPED_SYMBOLS)
def test_listed_underlyings_are_not_mapped_from_team_aliases(symbol: str) -> None:
    """Team aliases on the tip do not clear a symbol absent from market_mapping."""
    matched = re.match(r"NX\.F\.OPT\.([A-Z]+)", symbol)
    assert matched is not None
    token = matched.group(1)
    league = {
        "TENNIS": ("atp_challenger", "ATP", "atp_challenger", "TENNIS", "tennis"),
        "MLB": ("mlb", "MLB", "mlb", None, "baseball"),
        "WNBA": ("wnba", "WNBA", "wnba", None, "basketball"),
        "NFL": ("nfl", "NFL", "nfl", None, "football"),
    }[token]
    slug, meta, optic, grouping, sport = league
    home, away = ("Home Side", "Away Side")
    store = _store(
        [
            _ent(slug, "HOME", home, [_id("optic", "oid-home"), _id("crypto.com", "100")]),
            _ent(slug, "AWAY", away, [_id("optic", "oid-away"), _id("crypto.com", "200")]),
        ],
        [_league(slug, meta, optic, grouping=grouping, sport=sport)],
    )
    if token == "TENNIS":
        row = _probe(_challenger_store(lucas_owns_crypto=True), symbol)
    else:
        kick = "2026-10-02T01:15:00+00:00" if token == "NFL" else "2026-09-29T19:00:00+00:00"

        def fixtures(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
            return [_optic_pair(home, "oid-home", away, "oid-away")]

        row = _probe(
            store,
            symbol,
            catalogue_fn=lambda s: _cat(
                s,
                meta_name=f"{away} @ {home}",
                meta_league=meta,
                meta_event_date=kick,
                contract_type="Total",
                home_id="100",
                away_id="200",
                home_name=home,
                away_name=away,
            ),
            fixtures_fn=fixtures,
        )
    assert row["kind"] == "unmapped"
    assert row["mapped_rows"] == []
