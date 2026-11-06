"""Read-only crypto_id sweep matcher (tip vs harvest)."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.control_plane.store import InMemoryStore
from mappers.control_plane.sweep_crypto_ids import (
    build_crypto_id_suggestions,
    harvest_window_days,
    run_sweep_crypto_ids,
)


def _player(
    *,
    key: str,
    name: str,
    optic_id: str | None = None,
    crypto_id: str | None = None,
    league: str = "atp",
) -> EntityRow:
    aliases: list[dict[str, str]] = []
    if optic_id:
        aliases.append(
            {"sportsbook": "optic", "alias_kind": "optic_id", "alias_value": optic_id}
        )
    if crypto_id:
        aliases.append(
            {
                "sportsbook": "crypto.com",
                "alias_kind": "crypto_id",
                "alias_value": crypto_id,
            }
        )
    return EntityRow(
        league=league,
        entity_type="player",
        canonical_key=key,
        canonical_name=name,
        aliases=aliases,
    )


def test_missing_pin_via_canonical_name() -> None:
    ents = [_player(key="SINNER", name="Jannik Sinner")]
    built = build_crypto_id_suggestions(
        league="atp",
        harvest={"Jannik Sinner": "90001"},
        entities=ents,
    )
    assert built["ok"] is True
    assert built["count"] == 1
    payload = built["suggestions"][0]["payload"]
    assert payload["canonical_key"] == "SINNER"
    assert payload["aliases"][0]["alias_value"] == "90001"
    assert payload["aliases"][0]["sportsbook"] == "crypto.com"
    assert payload["aliases"][0]["alias_kind"] == "external_id"


def test_skips_already_pinned_external_id_kind() -> None:
    ents = [
        EntityRow(
            league="atp_challenger",
            entity_type="team",
            canonical_key="GAD",
            canonical_name="Buvaysar Gadamauri",
            aliases=[
                {
                    "sportsbook": "crypto.com",
                    "alias_kind": "external_id",
                    "alias_value": "1006197",
                }
            ],
        )
    ]
    built = build_crypto_id_suggestions(
        league="atp_challenger",
        harvest={"Buvaysar Gadamauri": "1006197"},
        entities=ents,
    )
    assert built["suggestions"] == []
    assert built["already_pinned"] == 1


def test_skips_already_pinned_crypto_id() -> None:
    ents = [_player(key="SINNER", name="Jannik Sinner", crypto_id="90001")]
    built = build_crypto_id_suggestions(
        league="atp",
        harvest={"Jannik Sinner": "90001"},
        entities=ents,
    )
    assert built["ok"] is False
    assert built["suggestions"] == []
    assert built["already_pinned"] == 1


def test_tennis_matches_via_optic_id() -> None:
    ents = [_player(key="ALCARAZ", name="Carlos A", optic_id="OA11")]
    built = build_crypto_id_suggestions(
        league="atp",
        harvest={"Carlos Alcaraz": "90002"},
        entities=ents,
        optic_competitors=[{"optic_id": "OA11", "name": "Carlos Alcaraz", "abbreviation": ""}],
    )
    assert built["count"] == 1
    assert built["suggestions"][0]["payload"]["canonical_key"] == "ALCARAZ"


def test_unmatched_harvest_does_not_invent_canonical() -> None:
    built = build_crypto_id_suggestions(
        league="atp",
        harvest={"Someone New": "99999"},
        entities=[_player(key="SINNER", name="Jannik Sinner")],
    )
    assert built["ok"] is False
    assert built["unmatched"] == 1
    assert built["suggestions"] == []


def test_run_sweep_uses_injected_harvest(monkeypatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "marketmaking-test")
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[_player(key="SINNER", name="Jannik Sinner")],
        leagues=[
            LeagueRow(
                league="atp",
                sport="tennis",
                optic_league_id="atp",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[
                    {
                        "sportsbook": "crypto.com",
                        "enabled": True,
                        "parser_profile": "crypto_generic_v1",
                        "source_league_id": "ATP",
                        "settings": {"league": "ATP", "sport_grouping": "TENNIS"},
                    }
                ],
            )
        ],
        activate=True,
    )
    result = run_sweep_crypto_ids(
        store,
        "atp",
        harvest_fn=lambda _meta, _days: {"Jannik Sinner": "90001"},
        fixtures_fn=lambda *_a, **_k: [],
    )
    assert result["ok"] is True
    assert result["suggestions"][0]["payload"]["canonical_key"] == "SINNER"


def test_run_sweep_rejects_unknown_league() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[],
        leagues=[],
        activate=True,
    )
    result = run_sweep_crypto_ids(
        store,
        "not_a_league",
        harvest_fn=lambda *_a, **_k: {"X": "1"},
        fixtures_fn=lambda *_a, **_k: [],
    )
    assert result["ok"] is False
    assert "not on tip" in result["warnings"][0]


def test_run_sweep_rejects_league_without_crypto_meta() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[],
        leagues=[
            LeagueRow(
                league="atp",
                sport="tennis",
                optic_league_id="atp",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[],
            )
        ],
        activate=True,
    )
    result = run_sweep_crypto_ids(
        store,
        "atp",
        harvest_fn=lambda *_a, **_k: {"X": "1"},
        fixtures_fn=lambda *_a, **_k: [],
    )
    assert result["ok"] is False
    assert "no crypto.com meta" in result["warnings"][0]


def _club(*, key: str, name: str, league: str = "brazil_serie_a") -> EntityRow:
    return EntityRow(
        league=league,
        entity_type="team",
        canonical_key=key,
        canonical_name=name,
        aliases=[],
    )


def test_strict_match_pins_sao_paulo_not_santos() -> None:
    built = build_crypto_id_suggestions(
        league="brazil_serie_a",
        harvest={"Sao Paulo FC": "90000933", "Santos FC": "90000932"},
        entities=[
            _club(key="SAN", name="Santos FC Sao Paulo"),
            _club(key="SAO", name="São Paulo FC"),
        ],
    )
    by_key = {row["payload"]["canonical_key"]: row["payload"] for row in built["suggestions"]}
    assert by_key["SAO"]["aliases"][0]["alias_value"] == "90000933"
    assert "SAN" not in by_key


def test_strict_match_rejects_academy_on_parent() -> None:
    built = build_crypto_id_suggestions(
        league="lol",
        harvest={"CTBC Flying Oyster Academy": "1535401"},
        entities=[_club(key="CFO", name="CTBC Flying Oyster", league="lol")],
    )
    assert built["suggestions"] == []
    assert built["unmatched"] == 1


def test_harvest_window_days_allows_unbounded_catalogue() -> None:
    assert harvest_window_days(None) == 30
    assert harvest_window_days(30) == 30
    assert harvest_window_days(400) == 30
    assert harvest_window_days(0) == 0
    assert harvest_window_days(-1) == 0


def test_run_sweep_unbounded_passes_days_zero(monkeypatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "marketmaking-test")
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[_player(key="SINNER", name="Jannik Sinner")],
        leagues=[
            LeagueRow(
                league="atp",
                sport="tennis",
                optic_league_id="atp",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[
                    {
                        "sportsbook": "crypto.com",
                        "enabled": True,
                        "parser_profile": "crypto_generic_v1",
                        "source_league_id": "ATP",
                        "settings": {"league": "ATP", "sport_grouping": "TENNIS"},
                    }
                ],
            )
        ],
        activate=True,
    )
    seen: list[int] = []

    def harvest(_meta: str, days: int) -> dict[str, str]:
        seen.append(days)
        return {"Jannik Sinner": "90001"}

    result = run_sweep_crypto_ids(
        store,
        "atp",
        days=0,
        harvest_fn=harvest,
        fixtures_fn=lambda *_a, **_k: [],
        keys={"SINNER"},
    )
    assert seen == [0]
    assert result["suggestions"][0]["payload"]["canonical_key"] == "SINNER"


def test_run_sweep_keys_drops_other_entities(monkeypatch) -> None:
    monkeypatch.setenv("GCP_PROJECT", "marketmaking-test")
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[
            _player(key="AAA", name="Aaa Fighter", league="ufc"),
            _player(key="CKI", name="Giga Chikadze", league="ufc"),
        ],
        leagues=[
            LeagueRow(
                league="ufc",
                sport="mma",
                optic_league_id="ufc",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[
                    {
                        "sportsbook": "crypto.com",
                        "enabled": True,
                        "parser_profile": "crypto_generic_v1",
                        "source_league_id": "UFC",
                        "settings": {"league": "UFC", "sport_grouping": "MMA"},
                    }
                ],
            )
        ],
        activate=True,
    )
    result = run_sweep_crypto_ids(
        store,
        "ufc",
        days=0,
        harvest_fn=lambda *_a, **_k: {
            "Aaa Fighter": "1",
            "Giga Chikadze": "140000001",
        },
        fixtures_fn=lambda *_a, **_k: [],
        keys={"CKI"},
    )
    keys = {row["payload"]["canonical_key"] for row in result["suggestions"]}
    assert keys == {"CKI"}


def test_run_sweep_fetches_extra_optic_league_fixtures(monkeypatch) -> None:
    """Primary plus extra Optic leagues feed the harvest name index."""
    monkeypatch.setenv("GCP_PROJECT", "marketmaking-test")
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[
            _player(
                key="JOD",
                name="Rafael Jodar",
                optic_id="58448A315FCFEEFF",
            ),
        ],
        leagues=[
            LeagueRow(
                league="atp",
                sport="tennis",
                optic_league_id="atp",
                extra_optic_league_ids=["davis_cup"],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[
                    {
                        "sportsbook": "crypto.com",
                        "enabled": True,
                        "parser_profile": "crypto_generic_v1",
                        "source_league_id": "ATP",
                        "settings": {"league": "ATP", "sport_grouping": "TENNIS"},
                    }
                ],
            )
        ],
        activate=True,
    )
    seen: list[str] = []

    def fixtures(optic_id: str, **_k: Any) -> list[dict[str, Any]]:
        seen.append(optic_id)
        if optic_id == "davis_cup":
            return [
                {
                    "id": "dc-1",
                    "home_competitors": [
                        {
                            "id": "74F8F924E9DC9F69",
                            "name": "Rafael Jodar",
                            "abbreviation": "",
                        },
                    ],
                    "away_competitors": [
                        {"id": "OTHER", "name": "Other Player", "abbreviation": ""},
                    ],
                },
            ]
        return [
            {
                "id": "atp-1",
                "home_competitors": [
                    {
                        "id": "58448A315FCFEEFF",
                        "name": "Rafael Jodar",
                        "abbreviation": "",
                    },
                ],
                "away_competitors": [
                    {"id": "OTHER2", "name": "Other Two", "abbreviation": ""},
                ],
            },
        ]

    result = run_sweep_crypto_ids(
        store,
        "atp",
        harvest_fn=lambda _meta, _days: {"Rafael Jodar": "1460336"},
        fixtures_fn=fixtures,
        keys={"JOD"},
    )
    assert "atp" in seen
    assert "davis_cup" in seen
    assert result["suggestions"][0]["payload"]["canonical_key"] == "JOD"
