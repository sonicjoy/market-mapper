"""Unit tests for BQ SoT alias inversion and taxonomy overlay."""

from __future__ import annotations

from mappers.control_plane.rows import EntityRow
from mappers.pipeline import _sot_alias_seed
from mappers.seed.sot import (
    SotSnapshot,
    entities_to_alias_data,
    poly_team_name_aliases,
)


def test_sot_alias_seed_uses_tip_not_toml():
    ents = [
        EntityRow(
            league="itf_men",
            entity_type="team",
            canonical_key="MMA",
            canonical_name="Martin Muller",
            aliases=[{
                "sportsbook": "optic",
                "alias_kind": "external_id",
                "alias_value": "4EAEA9E58102FA80",
                "enabled": True,
            }],
        ),
        EntityRow(
            league="epl",
            entity_type="team",
            canonical_key="HCA7",
            canonical_name="Hull City AFC",
            aliases=[{
                "sportsbook": "optic",
                "alias_kind": "external_id",
                "alias_value": "8CCE04981270F895",
                "enabled": True,
            }],
            tombstone=True,
        ),
    ]
    used, optic = _sot_alias_seed(
        SotSnapshot(rule_set_id="P_x", entities=ents, market_rules=[]),
        "itf_men",
    )
    assert used == {"MMA"}
    assert optic["4EAEA9E58102FA80"] == "MMA"
    assert "8CCE04981270F895" not in optic


def test_entities_to_alias_data_optic():
    ents = [
        EntityRow(
            league="europa_conference_league",
            entity_type="team",
            canonical_key="KÍ",
            canonical_name="KÍ Klaksvík",
            aliases=[
                {
                    "sportsbook": "optic",
                    "alias_kind": "external_id",
                    "alias_value": "B29E0BFC1622",
                    "enabled": True,
                },
            ],
        )
    ]
    data, optic = entities_to_alias_data(
        ents, league="europa_conference_league", entity_type="team"
    )
    assert data.canonicals == {"KÍ"}
    assert optic["B29E0BFC1622"] == "KÍ"


def test_entities_to_alias_data_accepts_harvest_optic_id_kind():
    ents = [
        EntityRow(
            league="itf_men",
            entity_type="team",
            canonical_key="DEL3",
            canonical_name="Matthew Dellavedova",
            aliases=[
                {
                    "sportsbook": "optic",
                    "alias_kind": "optic_id",
                    "alias_value": "80F9392DF1E215C5",
                    "enabled": True,
                },
                {
                    "sportsbook": "crypto.com",
                    "alias_kind": "crypto_id",
                    "alias_value": "1006197",
                    "enabled": True,
                },
            ],
        )
    ]
    data, optic = entities_to_alias_data(ents, league="itf_men", entity_type="team")
    assert optic["80F9392DF1E215C5"] == "DEL3"
    assert data.by_exchange["crypto_id"]["1006197"] == "DEL3"


def _poly_name_ent(league: str, key: str, optic_name: str, poly_name: str) -> EntityRow:
    return EntityRow(
        league=league,
        entity_type="team",
        canonical_key=key,
        canonical_name=optic_name,
        aliases=[
            {
                "sportsbook": "polymarket",
                "alias_kind": "name",
                "alias_value": poly_name,
                "enabled": True,
            }
        ],
    )


def test_poly_team_name_aliases_normalizes_mlb_suffix_keys():
    ents = [
        _poly_name_ent(
            "germany_bundesliga",
            "RBL",
            "RasenBallsport Leipzig",
            "RB Leipzig",
        ),
        _poly_name_ent(
            "germany_bundesliga",
            "BMG",
            "Borussia VfL Mönchengladbach",
            "Borussia Mönchengladbach",
        ),
    ]
    overlay = poly_team_name_aliases(ents, league="germany_bundesliga")
    assert overlay["rb leipzig"] == "rasenballsport leipzig"
    assert overlay["borussia monchengladbach"] == "borussia vfl monchengladbach"


def test_poly_team_name_aliases_omits_identity_after_normalize():
    ents = [
        _poly_name_ent(
            "argentina_primera",
            "VEL",
            "club atletico velez sarsfield",
            "club atletico velez sarsfield",
        ),
    ]
    overlay = poly_team_name_aliases(ents, league="argentina_primera")
    assert overlay == {}


def test_poly_team_name_aliases_keeps_tennis_prefix_underscores():
    ents = [
        _poly_name_ent("atp", "GJU", "Guido Ivan Justo", "guido_justo"),
    ]
    overlay = poly_team_name_aliases(
        ents, league="atp", question_style="tennis_prefix",
    )
    assert "guido_justo" in overlay
    assert overlay["guido_justo"] != "guido_justo"


def test_poly_team_name_aliases_skips_handicap_crumbs():
    ents = [
        _poly_name_ent("itf_women", "AMN8", "Anna Mihalka", "Mihalka (-1.5)"),
    ]
    overlay = poly_team_name_aliases(
        ents, league="itf_women", question_style="tennis_prefix",
    )
    assert overlay == {}
    data, _ = entities_to_alias_data(ents, league="itf_women", entity_type="team")
    assert "Mihalka (-1.5)" not in data.by_exchange.get("polymarket", {})

