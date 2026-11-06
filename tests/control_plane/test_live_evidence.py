"""Live evidence probes for alias verify (injected HTTP/BQ)."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.live_evidence import (
    EvidenceFetchers,
    EvidenceHit,
    collect_pins_evidence,
    probe_pin_evidence,
)
from mappers.control_plane.models import AliasPin, EntityAliasPayload
from mappers.control_plane.rows import EntityRow
from mappers.control_plane.store import InMemoryStore, LeagueRow


def _league(slug: str = "boxing_matches") -> LeagueRow:
    sport = "mma" if slug == "ufc" else "tennis" if slug == "atp" else "boxing"
    return LeagueRow(
        league=slug,
        sport=sport,
        optic_league_id=slug,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96,
        enabled=True,
        output_order=["moneyline"],
        exchanges=[],
    )


def _store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0_ev",
        entities=[],
        leagues=[_league()],
        activate=True,
    )
    return store


def test_optic_id_and_name_hit() -> None:
    fixtures = [{
        "id": "fx-1",
        "start_date": "2026-08-21T00:00:00Z",
        "home_competitors": [{"id": "E0133F3BCA247846", "name": "Amanda Serrano"}],
        "away_competitors": [{"id": "OTHER", "name": "Lucrecia Anabella Manzur"}],
    }]
    hit = probe_pin_evidence(
        _store(),
        league="boxing_matches",
        sportsbook="optic",
        alias_kind="external_id",
        alias_value="E0133F3BCA247846",
        canonical_name="Amanda Serrano",
        fetchers=EvidenceFetchers(optic_fixtures=lambda *_a, **_k: fixtures),
    )
    assert hit.blocker is None
    assert "optic:competitor:E0133F3BCA247846:Amanda Serrano" in hit.refs
    assert "optic:fixture:fx-1:Amanda Serrano vs Lucrecia Anabella Manzur (2026-08-21)" in hit.refs
    assert "optic:name:Amanda Serrano" in hit.refs
    assert all(not ref.startswith("polymarket:") for ref in hit.refs)


def test_optic_pin_uses_mapper_horizon_not_tip_96() -> None:
    """Sep-7 Nantes must still count as live evidence when tip horizon is 96h."""
    seen: dict[str, float] = {}

    def fetch(_oid: str, *, horizon_hours: float = 96.0) -> list[dict[str, object]]:
        seen["h"] = float(horizon_hours)
        return [{
            "id": "21428-79873-2026-09-07",
            "start_date": "2026-09-07T18:45:00Z",
            "home_competitors": [
                {"id": "F55591A73993AEC0", "name": "FC Nantes"},
            ],
            "away_competitors": [],
        }]

    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0_l2_ev",
        entities=[],
        leagues=[_league("france_ligue_2")],
        activate=True,
    )
    hit = probe_pin_evidence(
        store,
        league="france_ligue_2",
        sportsbook="optic",
        alias_kind="external_id",
        alias_value="F55591A73993AEC0",
        canonical_name="FC Nantes",
        fetchers=EvidenceFetchers(optic_fixtures=fetch),
    )
    assert hit.blocker is None
    assert seen["h"] >= 168.0


def test_optic_pin_probes_extra_optic_league_ids() -> None:
    """Davis Cup competitors live under extra_optic_league_ids, not primary atp."""
    seen: list[str] = []

    def fetch(optic_id: str, *, horizon_hours: float = 96.0) -> list[dict[str, object]]:
        seen.append(optic_id)
        if optic_id == "davis_cup":
            return [{
                "id": "dc-fx-1",
                "start_date": "2026-09-19T12:00:00Z",
                "home_competitors": [
                    {"id": "74F8F924E9DC9F69", "name": "Arthur Rinderknech"},
                ],
                "away_competitors": [
                    {"id": "OTHER", "name": "Other Player"},
                ],
            }]
        return []

    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0_atp_ev",
        entities=[],
        leagues=[LeagueRow(
            league="atp",
            sport="tennis",
            optic_league_id="atp",
            extra_optic_league_ids=["davis_cup"],
            fixture_source="api",
            fixture_horizon_hours=96,
            enabled=True,
            output_order=["moneyline"],
            exchanges=[{
                "sportsbook": "crypto.com",
                "parser_profile": "crypto_generic_v1",
                "source_league_id": "ATP",
            }],
        )],
        activate=True,
    )
    hit = probe_pin_evidence(
        store,
        league="atp",
        sportsbook="optic",
        alias_kind="external_id",
        alias_value="74F8F924E9DC9F69",
        canonical_name="Arthur Rinderknech",
        fetchers=EvidenceFetchers(optic_fixtures=fetch),
    )
    assert hit.blocker is None
    assert seen == ["atp", "davis_cup"]
    assert "optic:competitor:74F8F924E9DC9F69:Arthur Rinderknech" in hit.refs


def test_optic_pin_keeps_primary_when_extra_league_fetch_fails() -> None:
    def fetch(optic_id: str, *, horizon_hours: float = 96.0) -> list[dict[str, object]]:
        _ = horizon_hours
        if optic_id == "davis_cup":
            raise RuntimeError("davis_cup key missing")
        return [{
            "id": "atp-fx-1",
            "start_date": "2026-09-19T12:00:00Z",
            "home_competitors": [
                {"id": "58448A315FCFEEFF", "name": "Rafael Jodar"},
            ],
            "away_competitors": [],
        }]

    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0_atp_ev2",
        entities=[],
        leagues=[LeagueRow(
            league="atp",
            sport="tennis",
            optic_league_id="atp",
            extra_optic_league_ids=["davis_cup"],
            fixture_source="api",
            fixture_horizon_hours=96,
            enabled=True,
            output_order=["moneyline"],
            exchanges=[{
                "sportsbook": "crypto.com",
                "parser_profile": "crypto_generic_v1",
                "source_league_id": "ATP",
            }],
        )],
        activate=True,
    )
    hit = probe_pin_evidence(
        store,
        league="atp",
        sportsbook="optic",
        alias_kind="external_id",
        alias_value="58448A315FCFEEFF",
        canonical_name="Rafael Jodar",
        fetchers=EvidenceFetchers(optic_fixtures=fetch),
    )
    assert hit.blocker is None


def test_batch_crypto_row_reuses_lookup_inside_scope(monkeypatch: Any) -> None:
    from mappers.control_plane.live_evidence import (
        _batch_crypto_row,
        crypto_row_cache_scope,
    )

    calls: list[str] = []

    def lookup(cid: str) -> dict[str, Any]:
        calls.append(cid)
        return {"seen": True, "home_id": cid, "home_name": "Amanda Serrano"}

    monkeypatch.setattr(
        "mappers.control_plane.live_evidence._query_crypto_id",
        lookup,
    )
    assert _batch_crypto_row("90001")["home_name"] == "Amanda Serrano"
    assert _batch_crypto_row("90001")["home_name"] == "Amanda Serrano"
    assert calls == ["90001", "90001"]
    calls.clear()
    with crypto_row_cache_scope():
        assert _batch_crypto_row("90001")["home_name"] == "Amanda Serrano"
        assert _batch_crypto_row("90001")["home_name"] == "Amanda Serrano"
    assert calls == ["90001"]


def test_crypto_id_and_name_hit() -> None:
    row = {
        "seen": True,
        "symbol": "NX.F.OPT.BOX-1",
        "home_id": "90001",
        "home_name": "Amanda Serrano",
        "away_id": "90002",
        "away_name": "Lucrecia Anabella Manzur",
        "meta_name": "Serrano vs Manzur",
    }
    hit = probe_pin_evidence(
        _store(),
        league="boxing_matches",
        sportsbook="crypto.com",
        alias_kind="external_id",
        alias_value="90001",
        canonical_name="Amanda Serrano",
        fetchers=EvidenceFetchers(crypto_row=lambda _cid: row),
    )
    assert hit.blocker is None
    assert "crypto_id:90001" in hit.refs


def test_crypto_id_club_fc_suffix_matches() -> None:
    """Soccer tip names omit FC; crypto catalogue includes it (Le Mans)."""
    row = {
        "seen": True,
        "symbol": "NX.F.OPT.FRL1-1",
        "home_id": "90004421",
        "home_name": "Le Mans FC",
        "away_id": "90004422",
        "away_name": "Stade Brestois 29",
        "meta_name": "Le Mans FC vs Stade Brestois 29",
    }
    hit = probe_pin_evidence(
        _store(),
        league="france_ligue_1",
        sportsbook="crypto.com",
        alias_kind="external_id",
        alias_value="90004421",
        canonical_name="Le Mans",
        fetchers=EvidenceFetchers(crypto_row=lambda _cid: row),
    )
    assert hit.blocker is None
    assert "crypto_id:90004421" in hit.refs


def test_crypto_id_club_legal_suffix_is_reviewable() -> None:
    """Catalogue short name vs Optic legal name: propose, do not block."""
    row = {
        "seen": True,
        "symbol": "NX.F.OPT.FRL1-1",
        "home_id": "90000901",
        "home_name": "OGC Nice",
        "away_id": "90002808",
        "away_name": "Paris FC",
        "meta_name": "Paris FC vs OGC Nice",
    }
    hit = probe_pin_evidence(
        _store(),
        league="france_ligue_1",
        sportsbook="crypto.com",
        alias_kind="external_id",
        alias_value="90000901",
        canonical_name="OGC Nice Côte d'Azur",
        fetchers=EvidenceFetchers(crypto_row=lambda _cid: row),
    )
    assert hit.blocker is None
    assert "crypto_id:90000901" in hit.refs
    assert "crypto:name:OGC Nice" in hit.refs
    assert "crypto:tip:OGC Nice Côte d'Azur" in hit.refs


def test_crypto_id_meta_player_id_pins() -> None:
    """Player props use meta_player_id, not home/away external ids."""
    row = {
        "seen": True,
        "symbol": "NX.F.OPT.WNBA-00002-261002-M.O.1.80.20261230",
        "home_id": "13000013",
        "home_name": "Golden State Valkyries",
        "away_id": "13000007",
        "away_name": "Dallas Wings",
        "player_id": "130000338",
        "participant": "Awak Kuier",
        "meta_name": "Dallas Wings @ Golden State Valkyries",
    }
    hit = probe_pin_evidence(
        _store(),
        league="wnba",
        sportsbook="crypto.com",
        alias_kind="external_id",
        alias_value="130000338",
        canonical_name="Awak Kuier",
        fetchers=EvidenceFetchers(crypto_row=lambda _cid: row),
    )
    assert hit.blocker is None
    assert "crypto_id:130000338" in hit.refs
    assert "crypto:name:Awak Kuier" in hit.refs


def test_crypto_id_meta_player_id_wrong_player_blocks() -> None:
    """A player id live as another player's name stays blocked."""
    row = {
        "seen": True,
        "symbol": "NX.F.OPT.WNBA-00002-261002-M.O.1.80.20261230",
        "home_id": "13000013",
        "home_name": "Golden State Valkyries",
        "away_id": "13000007",
        "away_name": "Dallas Wings",
        "player_id": "130000338",
        "participant": "Awak Kuier",
        "meta_name": "Dallas Wings @ Golden State Valkyries",
    }
    hit = probe_pin_evidence(
        _store(),
        league="wnba",
        sportsbook="crypto.com",
        alias_kind="external_id",
        alias_value="130000338",
        canonical_name="Arike Ogunbowale",
        fetchers=EvidenceFetchers(crypto_row=lambda _cid: row),
    )
    assert hit.blocker is not None
    assert "Awak Kuier" in hit.blocker


def test_crypto_id_team_side_wins_over_player_id_collision() -> None:
    """An id that is also a team external id resolves to the team: a player pin blocks."""
    row = {
        "seen": True,
        "symbol": "NX.F.OPT.WNBA-00002-261002-M.O.1.80.20261230",
        "home_id": "130000338",
        "home_name": "Golden State Valkyries",
        "away_id": "13000007",
        "away_name": "Dallas Wings",
        "player_id": "130000338",
        "participant": "Awak Kuier",
        "meta_name": "Dallas Wings @ Golden State Valkyries",
    }
    hit = probe_pin_evidence(
        _store(),
        league="wnba",
        sportsbook="crypto.com",
        alias_kind="external_id",
        alias_value="130000338",
        canonical_name="Awak Kuier",
        fetchers=EvidenceFetchers(crypto_row=lambda _cid: row),
    )
    assert hit.blocker is not None


def test_crypto_id_player_legal_name_is_reviewable() -> None:
    """Catalogue short name vs Optic legal name: propose, do not block."""
    row = {
        "seen": True,
        "symbol": "NX.F.OPT.TENNIS-0060",
        "home_id": "916463",
        "home_name": "Duje Ajdukovic",
        "away_id": "1528979",
        "away_name": "Juan Martin",
        "meta_name": "Juan Martin @ Duje Ajdukovic",
    }
    hit = probe_pin_evidence(
        _store(),
        league="atp_challenger",
        sportsbook="crypto.com",
        alias_kind="external_id",
        alias_value="1528979",
        canonical_name="Juan Cruz Martin Manzano",
        fetchers=EvidenceFetchers(crypto_row=lambda _cid: row),
    )
    assert hit.blocker is None
    assert "crypto_id:1528979" in hit.refs
    assert "crypto:name:Juan Martin" in hit.refs
    assert "crypto:tip:Juan Cruz Martin Manzano" in hit.refs


def test_crypto_id_ufc_ring_name_is_reviewable() -> None:
    """Tina Black is the registered crypto.com label for Valesca Machado."""
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0_ufc",
        entities=[
            EntityRow(
                league="ufc",
                entity_type="fighter",
                canonical_key="VMA5",
                canonical_name="Valesca Machado",
                aliases=[],
            ),
        ],
        leagues=[_league("ufc")],
        activate=True,
    )
    row = {
        "seen": True,
        "symbol": "NX.F.OPT.UFC-1",
        "home_id": "140005844",
        "home_name": "Melissa Amaya",
        "away_id": "140001286",
        "away_name": "Tina Black",
        "meta_name": "Tina Black vs Melissa Amaya",
    }
    hit = probe_pin_evidence(
        store,
        league="ufc",
        sportsbook="crypto.com",
        alias_kind="external_id",
        alias_value="140001286",
        canonical_name="Valesca Machado",
        fetchers=EvidenceFetchers(crypto_row=lambda _cid: row),
    )
    assert hit.blocker is None
    assert "crypto_id:140001286" in hit.refs
    assert "crypto:name:Tina Black" in hit.refs
    assert "crypto:tip:Valesca Machado" in hit.refs
    blocked = probe_pin_evidence(
        store,
        league="ufc",
        sportsbook="crypto.com",
        alias_kind="external_id",
        alias_value="140001286",
        canonical_name="Melissa Amaya",
        fetchers=EvidenceFetchers(crypto_row=lambda _cid: row),
    )
    assert blocked.blocker is not None
    assert "Tina Black" in blocked.blocker


def test_crypto_id_club_wrong_team_still_blocks() -> None:
    row = {
        "seen": True,
        "symbol": "NX.F.OPT.FRL1-1",
        "home_id": "90004421",
        "home_name": "Le Mans FC",
        "away_id": "90004422",
        "away_name": "Stade Brestois 29",
        "meta_name": "Le Mans FC vs Stade Brestois 29",
    }
    hit = probe_pin_evidence(
        _store(),
        league="france_ligue_1",
        sportsbook="crypto.com",
        alias_kind="external_id",
        alias_value="90004421",
        canonical_name="Paris Saint-Germain",
        fetchers=EvidenceFetchers(crypto_row=lambda _cid: row),
    )
    assert hit.blocker is not None
    assert "Le Mans FC" in hit.blocker


def test_collect_pins_skips_when_probe_unwired() -> None:
    refs, blockers = collect_pins_evidence(_store(), [])
    assert refs == []
    assert blockers == []


def test_collect_pins_merges_and_blocks() -> None:
    def probe(_store: object, **kw: object) -> EvidenceHit:
        value = str(kw.get("alias_value") or "")
        if value == "BAD":
            return EvidenceHit(blocker="not live")
        return EvidenceHit(refs=(f"gap:{value}",))

    aliases = [
        EntityAliasPayload(
            league="boxing_matches",
            canonical_key="SERRAN",
            entity_type="fighter",
            canonical_name="Amanda Serrano",
            aliases=[AliasPin(sportsbook="crypto.com", alias_kind="external_id", alias_value="SERRAN")],
        ),
        EntityAliasPayload(
            league="boxing_matches",
            canonical_key="SERRAN",
            entity_type="fighter",
            canonical_name="Amanda Serrano",
            aliases=[AliasPin(sportsbook="crypto.com", alias_kind="external_id", alias_value="BAD")],
        ),
    ]
    refs, blockers = collect_pins_evidence(_store(), aliases, probe=probe)
    assert "gap:SERRAN" in refs
    assert blockers == ["not live"]


def test_collect_pins_probes_every_alias() -> None:
    seen: list[str] = []

    def probe(_store: object, **kw: object) -> EvidenceHit:
        value = str(kw.get("alias_value") or "")
        seen.append(value)
        if value == "OID":
            return EvidenceHit(
                blocker="Optic competitor OID not in active boxing_matches fixtures.",
            )
        return EvidenceHit(refs=(f"crypto_id:{value}", "crypto:name:Amanda Serrano"))

    aliases = [
        EntityAliasPayload(
            league="boxing_matches",
            canonical_key="SERRAN",
            entity_type="fighter",
            canonical_name="Amanda Serrano",
            aliases=[
                AliasPin(
                    sportsbook="crypto.com",
                    alias_kind="external_id",
                    alias_value="90001",
                ),
                AliasPin(
                    sportsbook="optic",
                    alias_kind="external_id",
                    alias_value="OID",
                ),
            ],
        ),
    ]
    refs, blockers = collect_pins_evidence(_store(), aliases, probe=probe)
    assert seen == ["90001", "OID"]
    assert "crypto_id:90001" in refs
    assert blockers == []
