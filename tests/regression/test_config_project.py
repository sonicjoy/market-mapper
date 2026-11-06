"""Contract tests for regression/config_project.py (step 5, v1)."""
import json

import pytest

from regression.config_project import (
    VERSION,
    canon_all,
    canon_record,
    strip_annotations,
)

# The real MLB Kalshi SPREAD rule, as the BQ reader would supply it
# (bq CLI JSON stringifies scalars — coercion is part of the contract).
SPREAD_BQ = {
    "league": "mlb", "sportsbook": "kalshi",
    "source_key_type": "ticker_type", "source_key": "SPREAD",
    "rule_kind": "taxonomy", "action": "map",
    "canonical_market_type": "point_spread",
    "match_operator": "exact", "priority": "100", "enabled": "true",
    "rule_id": "fc054b9872ab0b4d", "confidence": "id_verified",
    "notes": None,
}

# The same rule as the extractor-IR reader would supply it: proper
# types, and no period/source_selection_key/etc. fields at all.
SPREAD_IR = {
    "league": "mlb", "sportsbook": "kalshi",
    "source_key_type": "ticker_type", "source_key": "SPREAD",
    "rule_kind": "taxonomy", "action": "map",
    "canonical_market_type": "point_spread",
    "match_operator": "exact", "priority": 100, "enabled": True,
    "rule_id": "fc054b9872ab0b4d", "confidence": "id_verified",
}


def test_version_is_one():
    assert VERSION == 1


def test_bq_and_ir_shapes_compare_equal():
    """String scalars coerce and absent-field == explicit-null, so the
    two readers' renderings of one rule share a compared form."""
    a = strip_annotations(canon_record("market_rule", SPREAD_BQ))
    b = strip_annotations(canon_record("market_rule", SPREAD_IR))
    assert a == b


def test_key_matches_cow_diff_natural_key():
    d = json.loads(canon_record("market_rule", SPREAD_IR))
    assert d["k"] == ["mlb", "kalshi", "ticker_type", "SPREAD"]


def test_annotations_ride_but_do_not_compare():
    noted = dict(SPREAD_IR, notes="from a console proposal",
                 proposal_id="prop_123")
    line = canon_record("market_rule", noted)
    assert json.loads(line)["a"]["proposal_id"] == "prop_123"
    assert strip_annotations(line) == strip_annotations(
        canon_record("market_rule", SPREAD_IR))


def test_leading_space_source_key_is_content():
    """px suffix rules like ' Assists' must not be trimmed."""
    px = dict(SPREAD_IR, sportsbook="px", source_key_type="market_name",
              source_key=" Assists", match_operator="suffix",
              canonical_market_type="player_assists")
    assert json.loads(canon_record("market_rule", px))["k"][3] == " Assists"


def test_alias_value_is_in_the_key():
    """Exception-list semantics: presence is the compared fact, so two
    aliases for one (entity, sportsbook, kind) are two lines."""
    base = {"league": "international_club_friendlies",
            "entity_type": "team", "canonical_key": "LIV",
            "sportsbook": "kalshi", "alias_kind": "code",
            "enabled": True}
    lines, _ = canon_all([
        ("alias", dict(base, alias_value="LFC")),
        ("alias", dict(base, alias_value="LIVFC")),
    ])
    assert len(lines) == 2


def test_missing_key_field_is_an_error():
    with pytest.raises(ValueError, match="missing key fields"):
        canon_record("alias", {"league": "mlb", "entity_type": "team",
                               "canonical_key": "NYM"})


def test_unknown_kind_is_an_error():
    with pytest.raises(ValueError, match="unknown record kind"):
        canon_record("league", {"league": "mlb"})


def test_duplicate_identity_is_an_error_even_when_values_differ():
    """Two claims about one identity must fail loudly, exactly like
    the redesign's activation validation."""
    with pytest.raises(ValueError, match="duplicate identity"):
        canon_all([
            ("market_rule", SPREAD_IR),
            ("market_rule", dict(SPREAD_IR,
                                 canonical_market_type="game_total")),
        ])


def test_canon_all_sorts_deterministically_and_counts():
    ent = {"league": "mlb", "entity_type": "team",
           "canonical_key": "NYM", "canonical_name": "New York Mets",
           "enabled": True}
    records = [("market_rule", SPREAD_IR), ("entity", ent)]
    lines1, stats = canon_all(records)
    lines2, _ = canon_all(list(reversed(records)))
    assert lines1 == lines2 == sorted(lines1)
    assert stats == {"market_rule": 1, "entity": 1, "alias": 0,
                     "canonical_market": 0}
