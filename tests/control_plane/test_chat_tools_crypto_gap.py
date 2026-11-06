"""Read-only probe_crypto_gap (injected catalogue/Optic; no live network)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from mappers.control_plane import gap_optic_cache
from mappers.control_plane.chat_tools import TOOL_SCHEMAS, ChatToolContext
from mappers.control_plane.chat_tools_crypto_gap import run_probe_crypto_gap
from mappers.control_plane.gap_optic_cache import (
    clear_optic_cache,
    load_optic_fixtures_from_bq,
    tip_optic_keys,
)
from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.control_plane.store import InMemoryStore

_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
_UFC_SYM = "NX.F.OPT.UFC-00011-260822-M.O.1.1.20260822"
_TENNIS_SYM = "NX.F.OPT.TENNIS-0030-260819-M.O.1.1.20260819"
_NFL_FUT = "NX.F.OPT.NFL-2026.O.1.1.20260910"
_ITSA_SYM = "NX.F.OPT.ITSA-00001-260820-M.O.1.1.20260820"
_NFL_WEEK = "NX.F.OPT.NFL-00012-260907-M.O.1.1.20260907"


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
    slug: str,
    meta: str,
    optic: str,
    *,
    grouping: str | None = None,
    horizon: float = 96.0,
    sport: str = "soccer",
    extra_optic_league_ids: list[str] | None = None,
) -> LeagueRow:
    return LeagueRow(
        league=slug,
        sport=sport,
        optic_league_id=optic,
        extra_optic_league_ids=extra_optic_league_ids or [],
        fixture_source="api",
        fixture_horizon_hours=horizon,
        enabled=True,
        output_order=[],
        exchanges=[_crypto_ex(meta, grouping)],
    )


def _ent(
    league: str,
    key: str,
    name: str,
    crypto_id: str | None,
    *,
    kind: str = "external_id",
    entity_type: str = "team",
) -> EntityRow:
    aliases = []
    if crypto_id:
        aliases.append(
            {
                "sportsbook": "crypto.com",
                "alias_kind": kind,
                "alias_value": crypto_id,
            }
        )
    return EntityRow(
        league=league,
        entity_type=entity_type,
        canonical_key=key,
        canonical_name=name,
        aliases=aliases,
    )


def _store(entities: list[EntityRow], leagues: list[LeagueRow]) -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(rule_set_id="S0", entities=entities, leagues=leagues, activate=True)
    return store


def _ufc_store(*, pin_sch: bool = False, pin_mcv: bool = True) -> InMemoryStore:
    sch = "140005237" if pin_sch else None
    mcv = "140005468" if pin_mcv else None
    return _store(
        [
            _ent("ufc", "SCH", "Wesley Schultz", sch, entity_type="fighter"),
            _ent("ufc", "MCV", "Jackson McVey", mcv, entity_type="fighter"),
        ],
        [_league("ufc", "UFC", "ufc", grouping="MMA", sport="mma")],
    )


def _cat(
    symbol: str,
    *,
    seen: bool = True,
    name: str = "Wesley Schultz vs Jackson McVey",
    home_id: str = "140005237",
    away_id: str = "140005468",
    home_name: str = "Wesley Schultz",
    away_name: str = "Jackson McVey",
    kickoff: str = "2026-08-22T00:00:00+00:00",
    meta_league: str = "UFC",
) -> dict[str, Any]:
    return {
        "ok": True,
        "seen": seen,
        "symbol": symbol,
        "meta_name": name if seen else "",
        "meta_league": meta_league if seen else "",
        "meta_event_date": kickoff if seen else "",
        "contract_type": "Moneyline" if seen else "",
        "home_id": home_id if seen else "",
        "away_id": away_id if seen else "",
        "home_name": home_name if seen else "",
        "away_name": away_name if seen else "",
    }


def _fixtures(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": "fx-sch-mcv",
            "start_date": "2026-08-22T00:00:00Z",
            "home_competitors": [{"id": "oid-sch", "name": "Wesley Schultz"}],
            "away_competitors": [{"id": "oid-mcv", "name": "Jackson McVey"}],
        }
    ]


def _probe(store: InMemoryStore, **args: Any) -> dict[str, Any]:
    args.setdefault("catalogue_fn", lambda s: _cat(s))
    args.setdefault("fixtures_fn", _fixtures)
    args.setdefault("now", _NOW)
    return run_probe_crypto_gap(store, args)


def test_probe_reads_the_warmed_optic_cache(monkeypatch: Any) -> None:
    """Warm and probe must key the cache alike, or the probe re-fetches over HTTP."""
    clear_optic_cache()

    def boom(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise AssertionError("probe fell through to live Optic HTTP")

    monkeypatch.setattr(gap_optic_cache, "fetch_optic_fixtures", boom)
    store = _ufc_store(pin_sch=True)
    load_optic_fixtures_from_bq(
        tip_optic_keys(store),
        query_fn=lambda _sql, _ids, _fwd: [_bq_fixture()],
        now=_NOW,
    )
    warmed = _probe(store, symbol=_UFC_SYM, fixtures_fn=None)["results"][0]
    injected = _probe(_ufc_store(pin_sch=True), symbol=_UFC_SYM)["results"][0]
    assert warmed["kind"] != "missing_optic"
    assert warmed["kind"] == injected["kind"]


def _bq_fixture() -> SimpleNamespace:
    return SimpleNamespace(
        fixture_id="fx-sch-mcv",
        game_id="fx-sch-mcv",
        start_date=datetime(2026, 8, 22, tzinfo=UTC),
        optic_league_id="ufc",
        home_competitors=[{"id": "oid-sch", "name": "Wesley Schultz"}],
        away_competitors=[{"id": "oid-mcv", "name": "Jackson McVey"}],
    )


def test_schema_lists_probe_crypto_gap() -> None:
    names = {row["name"] for row in TOOL_SCHEMAS}
    assert "probe_crypto_gap" in names
    assert "probe_crypto_symbol" not in names, "string split with no evidence"
    assert "sweep_crypto_ids" not in names, "deterministic-only, never in a model toolset"


def test_unknown_alias_when_crypto_id_unpinned() -> None:
    result = _probe(_ufc_store(), symbol=_UFC_SYM)
    row = result["results"][0]
    assert result["ok"] is True
    assert row["league"] == "ufc"
    assert row["crypto_ids"] == ["140005237", "140005468"]
    assert row["kind"] == "unknown_alias"
    assert row["optic"]["fixture_id"] == "fx-sch-mcv"
    assert f"gap:{_UFC_SYM}" in row["evidence_refs"]
    assert (
        "optic:fixture:fx-sch-mcv:Wesley Schultz vs Jackson McVey (2026-08-22)"
        in row["evidence_refs"]
    )
    assert "optic:competitor:oid-sch:Wesley Schultz" in row["evidence_refs"]
    assert "optic:competitor:oid-mcv:Jackson McVey" in row["evidence_refs"]
    assert "crypto:title:Wesley Schultz vs Jackson McVey" in row["evidence_refs"]
    assert "crypto:name:Wesley Schultz" in row["evidence_refs"]
    assert "crypto:name:Jackson McVey" in row["evidence_refs"]
    assert "crypto:name:Wesley Schultz vs Jackson McVey" not in row["evidence_refs"]


def test_already_mapped_with_bq_external_id_kind() -> None:
    result = _probe(_ufc_store(pin_sch=True), symbol=_UFC_SYM)
    row = result["results"][0]
    assert row["kind"] == "unmapped"
    assert row["tip"][0]["owners"] == ["SCH"]


def test_already_mapped_with_sweep_crypto_id_kind() -> None:
    store = _store(
        [
            _ent("ufc", "SCH", "Wesley Schultz", "140005237", kind="crypto_id"),
            _ent("ufc", "MCV", "Jackson McVey", "140005468", kind="crypto_id"),
        ],
        [_league("ufc", "UFC", "ufc", grouping="MMA", sport="mma")],
    )
    row = _probe(store, symbol=_UFC_SYM)["results"][0]
    assert row["kind"] == "unmapped"


def test_tennis_shared_prefix_hits_challenger() -> None:
    store = _store(
        [
            _ent("atp", "SINNER", "Jannik Sinner", None, entity_type="player"),
            _ent("atp_challenger", "AMU", "Anton Matusevich", None, entity_type="player"),
        ],
        [
            _league("atp", "ATP", "atp", grouping="TENNIS", sport="tennis"),
            _league(
                "atp_challenger", "ATP", "atp_challenger", grouping="TENNIS", sport="tennis"
            ),
        ],
    )

    def fixtures(optic_league_id: str, **_k: Any) -> list[dict[str, Any]]:
        if optic_league_id != "atp_challenger":
            return []
        return [
            {
                "id": "fx-amu-eml",
                "start_date": "2026-08-19T10:00:00Z",
                "home_competitors": [{"id": "oid-amu", "name": "Anton Matusevich"}],
                "away_competitors": [{"id": "oid-eml", "name": "Elmer Moller"}],
            }
        ]

    row = _probe(
        store,
        symbol=_TENNIS_SYM,
        catalogue_fn=lambda s: _cat(
            s,
            name="Anton Matusevich vs Elmer Moller",
            home_id="763766",
            away_id="1100393",
            home_name="Anton Matusevich",
            away_name="Elmer Moller",
            kickoff="2026-08-19T18:00:00+00:00",
            meta_league="ATP",
        ),
        fixtures_fn=fixtures,
    )["results"][0]
    assert set(row["leagues"]) == {"atp", "atp_challenger"}
    assert row["league"] == "atp_challenger"
    assert row["kind"] == "unknown_alias"
    assert row["optic"]["fixture_id"] == "fx-amu-eml"


def test_davis_cup_extra_optic_matches_atp_catalogue() -> None:
    """ATP catalogue + Davis Cup Optic league must not dead-bucket as missing_optic."""
    store = _store(
        [
            _ent("atp", "SHELTON", "Ben Shelton", "1100001", entity_type="player"),
            _ent("atp", "MENSIK", "Jakub Mensik", "1100002", entity_type="player"),
        ],
        [
            _league(
                "atp",
                "ATP",
                "atp",
                grouping="TENNIS",
                sport="tennis",
                extra_optic_league_ids=["davis_cup"],
            ),
        ],
    )

    def fixtures(optic_league_id: str, **_k: Any) -> list[dict[str, Any]]:
        if optic_league_id == "atp":
            return []
        if optic_league_id != "davis_cup":
            return []
        return [
            {
                "id": "fx-dc-shelton-mensik",
                "start_date": "2026-08-20T14:00:00Z",
                "home_competitors": [{"id": "oid-shelton", "name": "Ben Shelton"}],
                "away_competitors": [{"id": "oid-mensik", "name": "Jakub Mensik"}],
            }
        ]

    row = _probe(
        store,
        symbol=_TENNIS_SYM,
        catalogue_fn=lambda s: _cat(
            s,
            name="Ben Shelton vs Jakub Mensik",
            home_id="1100001",
            away_id="1100002",
            home_name="Ben Shelton",
            away_name="Jakub Mensik",
            kickoff="2026-08-20T14:00:00+00:00",
            meta_league="ATP",
        ),
        fixtures_fn=fixtures,
    )["results"][0]
    assert row["leagues"] == ["atp"]
    assert row["league"] == "atp"
    assert row["kind"] == "unmapped"
    assert row["optic"]["fixture_id"] == "fx-dc-shelton-mensik"


def _tennis_wta_first_store() -> InMemoryStore:
    return _store(
        [
            _ent("wta", "SWIATEK", "Iga Swiatek", None, entity_type="player"),
            _ent("atp", "SINNER", "Jannik Sinner", None, entity_type="player"),
            _ent(
                "atp_challenger", "MILEV", "Yanaki Milev", None, entity_type="player"
            ),
        ],
        [
            _league("wta", "WTA", "wta", grouping="TENNIS", sport="tennis"),
            _league("atp", "ATP", "atp", grouping="TENNIS", sport="tennis"),
            _league(
                "atp_challenger",
                "ATP",
                "atp_challenger",
                grouping="TENNIS",
                sport="tennis",
            ),
        ],
    )


def _milev_cat(symbol: str) -> dict[str, Any]:
    return _cat(
        symbol,
        name="Yanaki Milev @ Petr Nesterov",
        home_id="1104531",
        away_id="1308111",
        home_name="Petr Nesterov",
        away_name="Yanaki Milev",
        kickoff="2026-08-19T18:00:00+00:00",
        meta_league="ATP",
    )


def test_tennis_atp_catalogue_skips_wta_book() -> None:
    """WTA-first tip order must not classify ATP Challenger as name_mismatch."""

    def fixtures(optic_league_id: str, **_k: Any) -> list[dict[str, Any]]:
        if optic_league_id == "wta":
            return [{
                "id": "fx-wta",
                "start_date": "2026-09-01T12:00:00Z",
                "home_competitors": [{"id": "oid-iga", "name": "Iga Swiatek"}],
                "away_competitors": [{"id": "oid-ary", "name": "Aryna Sabalenka"}],
            }]
        if optic_league_id != "atp_challenger":
            return []
        return [{
            "id": "18464-30918-2026-35",
            "start_date": "2026-09-01T15:10:00Z",
            "home_competitors": [{"id": "oid-nes", "name": "Petr Nesterov"}],
            "away_competitors": [{"id": "oid-mil", "name": "Yanaki Milev"}],
        }]

    row = _probe(
        _tennis_wta_first_store(),
        symbol=_TENNIS_SYM,
        catalogue_fn=_milev_cat,
        fixtures_fn=fixtures,
    )["results"][0]
    assert "wta" not in row["leagues"]
    assert set(row["leagues"]) == {"atp", "atp_challenger"}
    assert row["league"] == "atp_challenger"
    assert row["kind"] == "unknown_alias"
    assert row["optic"].get("name_mismatch") is not True
    assert row["optic"]["fixture_id"] == "18464-30918-2026-35"


def test_tennis_atp_empty_tours_are_not_wta_name_mismatch() -> None:
    def fixtures(optic_league_id: str, **_k: Any) -> list[dict[str, Any]]:
        if optic_league_id != "wta":
            return []
        return [{
            "id": "fx-wta",
            "start_date": "2026-09-01T12:00:00Z",
            "home_competitors": [{"id": "oid-iga", "name": "Iga Swiatek"}],
            "away_competitors": [{"id": "oid-ary", "name": "Aryna Sabalenka"}],
        }]

    row = _probe(
        _tennis_wta_first_store(),
        symbol=_TENNIS_SYM,
        catalogue_fn=_milev_cat,
        fixtures_fn=fixtures,
    )["results"][0]
    assert row["kind"] != "name_mismatch"
    assert row["league"] in {"atp", "atp_challenger"}
    assert not (row.get("optic") or {}).get("name_mismatch")


def test_tournament_future() -> None:
    def boom(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise AssertionError("futures residual must not Optic-match")

    row = _probe(_ufc_store(), symbol=_NFL_FUT, fixtures_fn=boom)["results"][0]
    assert row["kind"] == "tournament_future"
    assert row["optic"] is None


def test_league_not_wired() -> None:
    row = _probe(_ufc_store(), symbol=_ITSA_SYM)["results"][0]
    assert row["kind"] == "league_not_wired"


def test_outside_horizon_when_unpinned() -> None:
    store = _store(
        [_ent("nfl", "KC", "Kansas City Chiefs", None)],
        [_league("nfl", "NFL", "nfl", sport="football", horizon=168.0)],
    )

    def boom(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise AssertionError("outside-horizon residual must not Optic-match")

    row = _probe(
        store,
        symbol=_NFL_WEEK,
        catalogue_fn=lambda s: _cat(
            s,
            name="Chiefs vs Ravens",
            home_id="1",
            away_id="2",
            kickoff="2026-09-07T17:00:00+00:00",
            meta_league="NFL",
        ),
        fixtures_fn=boom,
    )["results"][0]
    assert row["kind"] == "outside_horizon"
    assert row["optic"] is None


def test_completed_stale_skips_optic() -> None:
    def boom(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise AssertionError("stale residual must not Optic-match")

    row = _probe(
        _ufc_store(),
        symbol=_UFC_SYM,
        catalogue_fn=lambda s: _cat(s, kickoff="2026-08-18T00:00:00+00:00"),
        fixtures_fn=boom,
    )["results"][0]
    assert row["kind"] == "completed_stale"
    assert row["optic"] is None


def test_missing_optic_when_pinned() -> None:
    row = _probe(
        _ufc_store(pin_sch=True),
        symbol=_UFC_SYM,
        fixtures_fn=lambda *_a, **_k: [],
    )["results"][0]
    assert row["kind"] == "missing_optic"


def test_different_fight_with_no_shared_name_is_missing_optic() -> None:
    def fixtures(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [{
            "id": "fx-other",
            "start_date": "2026-08-22T00:00:00Z",
            "home_competitors": [{"id": "oid-a", "name": "Other Home"}],
            "away_competitors": [{"id": "oid-b", "name": "Other Away"}],
        }]

    row = _probe(
        _ufc_store(pin_sch=True), symbol=_UFC_SYM, fixtures_fn=fixtures,
    )["results"][0]
    assert row["kind"] == "missing_optic"
    assert row["optic"] is None


def test_name_mismatch_when_one_side_is_on_the_card() -> None:
    def fixtures(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [{
            "id": "fx-other",
            "start_date": "2026-08-22T00:00:00Z",
            "home_competitors": [{"id": "oid-sch", "name": "Wesley Schultz"}],
            "away_competitors": [{"id": "oid-b", "name": "Other Away"}],
        }]

    row = _probe(_ufc_store(), symbol=_UFC_SYM, fixtures_fn=fixtures)["results"][0]
    assert row["kind"] == "name_mismatch"
    assert row["optic"].get("name_mismatch") is True


def test_umlaut_fixture_is_not_missing_optic() -> None:
    store = _store(
        [_ent("germany_bundesliga", "RBL", "RB Leipzig", None)],
        [_league("germany_bundesliga", "DEB", "germany_-_bundesliga")],
    )
    row = _probe(
        store,
        symbol="NX.F.OPT.DEB-00001-260829-M.O.1.1.20260830",
        catalogue_fn=lambda s: _cat(
            s,
            name="Borussia Monchengladbach @ RB Leipzig",
            home_id="9",
            away_id="8",
            home_name="RB Leipzig",
            away_name="Borussia Monchengladbach",
            kickoff="2026-08-22T13:30:00+00:00",
            meta_league="DEB",
        ),
        fixtures_fn=lambda *_a, **_k: [{
            "id": "fx-lei-bmg",
            "start_date": "2026-08-22T13:30:00Z",
            "home_competitors": [{"id": "oid-rbl", "name": "RB Leipzig"}],
            "away_competitors": [{"id": "oid-bmg", "name": "Borussia Mönchengladbach"}],
        }],
    )["results"][0]
    assert row["kind"] == "unknown_alias"
    assert row["optic"]["fixture_id"] == "fx-lei-bmg"


def test_legal_suffix_fixture_is_not_name_mismatch() -> None:
    store = _store(
        [_ent("france_ligue_1", "NIC", "OGC Nice Côte d'Azur", None)],
        [_league("france_ligue_1", "FRL1", "france_-_ligue_1")],
    )
    row = _probe(
        store,
        symbol="NX.F.OPT.FRL1-00001-260830-M.O.1.1.20260830",
        catalogue_fn=lambda s: _cat(
            s,
            name="Paris FC vs OGC Nice",
            home_id="90002808",
            away_id="90000901",
            home_name="Paris FC",
            away_name="OGC Nice",
            kickoff="2026-08-22T13:00:00+00:00",
            meta_league="FRL1",
        ),
        fixtures_fn=lambda *_a, **_k: [{
            "id": "fx-pfc-nice",
            "start_date": "2026-08-22T13:00:00Z",
            "home_competitors": [{"id": "oid-pfc", "name": "Paris FC"}],
            "away_competitors": [{"id": "oid-nic", "name": "OGC Nice Côte d'Azur"}],
        }],
    )["results"][0]
    assert row["kind"] == "unknown_alias"
    assert row["optic"]["away_id"] == "oid-nic"


def test_bosnia_and_spelling_matches_the_optic_fixture() -> None:
    """Catalogue 'and' is Optic's hyphen for the same 18:45 kickoff."""
    store = _store([], [_league("uefa_nations_league", "UNL", "uefa_-_nations_league")])
    row = _probe(
        store,
        symbol="NX.F.OPT.UNL-00003-261002-M.O.1.1.20261230",
        now=datetime(2026, 10, 1, 12, tzinfo=UTC),
        catalogue_fn=lambda s: _cat(
            s,
            name="Sweden @ Bosnia and Herzegovina",
            home_id="90001089",
            away_id="90000959",
            home_name="Bosnia and Herzegovina",
            away_name="Sweden",
            kickoff="2026-10-02T18:45:00+00:00",
            meta_league="UNL",
        ),
        fixtures_fn=lambda *_a, **_k: [{
            "id": "fx-bih-swe",
            "start_date": "2026-10-02T18:45:00Z",
            "home_competitors": [{"id": "8F98DB8E7FD1", "name": "Bosnia-Herzegovina"}],
            "away_competitors": [{"id": "2CCFDD0F5B48", "name": "Sweden"}],
        }],
    )["results"][0]
    assert row["kind"] == "unknown_alias"
    assert row["optic"]["fixture_id"] == "fx-bih-swe"


def test_participants_match_when_the_event_title_has_no_sides() -> None:
    """meta_name is a display string; meta_home/away_participant are the sides."""
    store = _store([], [_league("uefa_nations_league", "UNL", "uefa_-_nations_league")])
    row = _probe(
        store,
        symbol="NX.F.OPT.UNL-00003-261002-M.O.1.1.20261230",
        now=datetime(2026, 10, 1, 12, tzinfo=UTC),
        catalogue_fn=lambda s: _cat(
            s,
            name="Nations League Match Winner",
            home_id="90001089",
            away_id="90000959",
            home_name="Bosnia and Herzegovina",
            away_name="Sweden",
            kickoff="2026-10-02T18:45:00+00:00",
            meta_league="UNL",
        ),
        fixtures_fn=lambda *_a, **_k: [{
            "id": "fx-bih-swe",
            "start_date": "2026-10-02T18:45:00Z",
            "home_competitors": [{"id": "8F98DB8E7FD1", "name": "Bosnia-Herzegovina"}],
            "away_competitors": [{"id": "2CCFDD0F5B48", "name": "Sweden"}],
        }],
    )["results"][0]
    assert row["kind"] == "unknown_alias"
    assert row["optic"]["fixture_id"] == "fx-bih-swe"


def test_friendly_with_no_optic_row_is_missing_optic() -> None:
    """Mozambique @ Botswana is not on the Optic friendlies card that day."""
    store = _store(
        [
            _ent("international_friendlies", "BOT", "Botswana", "90001305"),
            _ent("international_friendlies", "MOZ", "Mozambique", "90001352"),
        ],
        [_league("international_friendlies", "FIFAF", "international_-_friendlies")],
    )
    row = _probe(
        store,
        symbol="NX.F.OPT.FIFAF-00006-260930-M.O.1.1.20261230",
        now=datetime(2026, 9, 29, 12, tzinfo=UTC),
        catalogue_fn=lambda s: _cat(
            s,
            name="Mozambique @ Botswana",
            home_id="90001305",
            away_id="90001352",
            home_name="Botswana",
            away_name="Mozambique",
            kickoff="2026-09-30T14:00:00+00:00",
            meta_league="FIFAF",
        ),
        fixtures_fn=lambda *_a, **_k: [{
            "id": "fx-usa-chi",
            "start_date": "2026-09-30T00:00:00Z",
            "home_competitors": [{"id": "oid-usa", "name": "United States"}],
            "away_competitors": [{"id": "oid-chi", "name": "Chile"}],
        }],
    )["results"][0]
    assert row["kind"] == "missing_optic"
    assert row["optic"] is None


def test_collision_two_owners() -> None:
    store = _store(
        [
            _ent("ufc", "SCH", "Wesley Schultz", "140005237"),
            _ent("ufc", "DUP", "Dupe", "140005237"),
            _ent("ufc", "MCV", "Jackson McVey", "140005468"),
        ],
        [_league("ufc", "UFC", "ufc", grouping="MMA", sport="mma")],
    )
    row = _probe(store, symbol=_UFC_SYM)["results"][0]
    assert row["kind"] == "collision"


def test_parse_miss_and_catalogue_miss() -> None:
    parse = _probe(_ufc_store(), symbol="not-an-nx-symbol")
    assert parse["results"][0]["kind"] == "parse_miss"
    miss = _probe(
        _ufc_store(),
        symbol=_UFC_SYM,
        catalogue_fn=lambda s: _cat(s, seen=False),
    )
    assert miss["results"][0]["kind"] == "catalogue_miss"
    assert miss["results"][0]["sportsbook"] == "crypto.com"
    assert miss["results"][0]["token"] == "UFC"


def test_stale_page_league_does_not_override_nx_token() -> None:
    """Unmapped/Editor league must not beat a wired NX token (Kalshi parity)."""
    store = _store(
        [
            _ent("atp", "SINNER", "Jannik Sinner", None, entity_type="player"),
            _ent("epl", "ARS", "Arsenal", None),
        ],
        [
            _league("atp", "ATP", "atp", grouping="TENNIS", sport="tennis"),
            _league("epl", "EPL", "epl", sport="soccer"),
        ],
    )
    row = _probe(
        store,
        symbol=_TENNIS_SYM,
        league="epl",
        catalogue_fn=lambda s: _cat(
            s,
            name="Anton Matusevich vs Elmer Moller",
            home_id="763766",
            away_id="1100393",
            kickoff="2026-08-19T18:00:00+00:00",
            meta_league="ATP",
        ),
        fixtures_fn=lambda *_a, **_k: [],
    )["results"][0]
    assert row["league"] == "atp"
    assert row["leagues"] == ["atp"]
    assert row["kind"] != "league_not_wired"


def test_missing_symbol_and_cap() -> None:
    empty = run_probe_crypto_gap(_ufc_store(), {})
    assert empty["ok"] is False
    result = _probe(
        _ufc_store(),
        symbols=[f"NX.F.OPT.UFC-0000{i}-260822-M.O.1.1.20260822" for i in range(8)],
        catalogue_fn=lambda s: _cat(s, seen=False),
    )
    assert result["count"] == 5


def test_chat_context_dispatches() -> None:
    tools = ChatToolContext(_ufc_store())
    out = tools.run(
        "probe_crypto_gap",
        {
            "symbol": _UFC_SYM,
            "catalogue_fn": lambda s: _cat(s),
            "fixtures_fn": _fixtures,
            "now": _NOW,
        },
    )
    assert out["results"][0]["kind"] == "unknown_alias"


def test_mapping_hit_skips_catalogue() -> None:
    calls: list[str] = []
    mapped = [{
        "sportsbook": "crypto.com",
        "symbol": _UFC_SYM,
        "league": "ufc",
        "home": "Wesley Schultz",
        "away": "Jackson McVey",
        "market_type": "moneyline",
        "side": "SCH",
        "selection": "Schultz",
        "fixture_id": "fx-sch-mcv",
    }]
    result = run_probe_crypto_gap(
        _ufc_store(),
        {
            "symbol": _UFC_SYM,
            "catalogue_fn": lambda s: calls.append(s) or _cat(s),
            "mapping_fn": lambda _s: mapped,
            "fixtures_fn": lambda *_a, **_k: [],
            "now": _NOW,
        },
    )
    row = result["results"][0]
    assert calls == []
    assert row["kind"] == "already_mapped"
    assert row["mapped_rows"] == mapped
    assert row["sportsbook"] == "crypto.com"


def test_date_only_placeholder_is_not_name_mismatch() -> None:
    store = _store(
        [
            _ent("la_liga", "SEV", "Sevilla FC", "90000606"),
            _ent("la_liga", "VAL", "Valencia CF", "90000614"),
        ],
        [_league("la_liga", "ESP", "spain_-_la_liga")],
    )

    def fixtures(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "fx-cel-mal",
                "start_date": "2026-09-13T12:00:00Z",
                "home_competitors": [{"id": "oid-cel", "name": "RC Celta de Vigo"}],
                "away_competitors": [{"id": "oid-mal", "name": "Malaga CF"}],
            },
            {
                "id": "202609119DC4F1FD",
                "start_date": "2026-09-11T19:00:00Z",
                "home_competitors": [{"id": "oid-sev", "name": "Sevilla FC"}],
                "away_competitors": [{"id": "oid-val", "name": "Valencia CF"}],
            },
        ]

    row = _probe(
        store,
        symbol="NX.F.OPT.ESP-00009-260913-M.O.1.2.20261230",
        catalogue_fn=lambda s: _cat(
            s,
            name="Valencia CF @ Sevilla FC",
            home_id="90000606",
            away_id="90000614",
            home_name="Sevilla FC",
            away_name="Valencia CF",
            kickoff="2026-09-13T04:00:00+00:00",
            meta_league="ESP",
        ),
        fixtures_fn=fixtures,
        now=datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
    )["results"][0]
    assert row["kind"] != "name_mismatch"
    assert row["optic"]["fixture_id"] == "202609119DC4F1FD"
    assert row["kind"] == "unmapped"
