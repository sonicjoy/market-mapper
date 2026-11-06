"""Official Polymarket name-overlay harvest (injected fixtures; no live BQ)."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.gap_fix import harvest_gap_pins
from mappers.control_plane.gap_fix_poly_names import (
    _ambiguous_skip,
    question_sides,
    significant_token,
    unique_name_binds,
)
from mappers.control_plane.gap_harvest_ttl import load_dead_buckets
from mappers.control_plane.pin_flow import alias_from_pin as _alias_from_pin
from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.exchanges.polymarket import _norm_name
from tests.control_plane.test_gap_fix import _optic_row, _store
from tests.control_plane.test_gap_fix_poly_official import (
    _official_event,
    _poly_official_league,
)


def _team(league: str, key: str, name: str, oid: str) -> EntityRow:
    return EntityRow(
        league=league,
        entity_type="team",
        canonical_key=key,
        canonical_name=name,
        aliases=[{"sportsbook": "optic", "alias_kind": "external_id", "alias_value": oid}],
    )


def _bun_optic() -> list[dict[str, Any]]:
    return [
        _optic_row(
            "germany_-_bundesliga",
            "RBL", "RasenBallsport Leipzig", "oid-rbl",
            "BMG", "Borussia VfL Mönchengladbach", "oid-bmg",
        ),
        _optic_row(
            "germany_-_bundesliga",
            "FCB", "FC Bayern München", "oid-bay",
            "BVB", "Borussia Dortmund", "oid-dor",
        ),
    ]


def _bun_store() -> Any:
    league = _poly_official_league("germany_bundesliga", "germany_-_bundesliga", "bun")
    return _store(
        [
            _team("germany_bundesliga", "RBL", "RasenBallsport Leipzig", "oid-rbl"),
            _team("germany_bundesliga", "BMG", "Borussia VfL Mönchengladbach", "oid-bmg"),
        ],
        [league],
    )


def test_question_sides_vs_and_beat() -> None:
    assert question_sides("RB Leipzig vs. Borussia Mönchengladbach: O/U 2.5") == (
        "RB Leipzig",
        "Borussia Mönchengladbach",
    )
    assert question_sides("Will RB Leipzig beat Borussia Mönchengladbach?") == (
        "RB Leipzig",
        "Borussia Mönchengladbach",
    )
    assert question_sides("Will there be a run scored in the first inning?: A vs B") is None
    assert question_sides("Will RB Leipzig win?") is None
    assert question_sides(
        "M15 Hurghada: Omar Kandil vs Lorenzo Lorusso", "tennis_prefix",
    ) == ("Omar Kandil", "Lorenzo Lorusso")
    assert question_sides(
        "US Open ATP: Completed Match: Tomas Etcheverry vs Jacob Fearnley",
        "tennis_prefix",
    ) is None
    assert question_sides("Austin FC to score first vs. Seattle Sounders FC?") is None
    assert question_sides(
        "Austin FC vs. Seattle Sounders FC: Neither team to score first?",
    ) is None
    assert question_sides("Kane to score 2+ vs. Chelsea?") is None
    assert question_sides(
        "Counter-Strike: 3DMAX vs Infinite (BO3) - ESL Pro League",
    ) == ("3DMAX", "Infinite")
    assert question_sides(
        "Counter-Strike: 3DMAX vs Infinite - Map 2 Winner",
    ) is None
    assert question_sides(
        "LoL: Kits Esports vs SDM Tigres (BO3) - Game 2 Winner",
    ) is None


def test_question_sides_soccer_draw_keeps_market_phrase_out_of_the_name() -> None:
    """The draw form trails the market phrase after team B with no colon."""
    assert question_sides(
        "Will RB Leipzig vs. Borussia Mönchengladbach end in a draw?",
    ) == ("RB Leipzig", "Borussia Mönchengladbach")
    assert question_sides("Will the match end in a draw?") is None


def test_significant_token_drops_particles() -> None:
    style = "mlb_suffix"
    assert significant_token(_norm_name("RB Leipzig", style)) == "leipzig"
    assert significant_token(_norm_name("Ohio State", style)) == "ohio"
    assert significant_token(_norm_name("Manchester United", style)) == "manchester"
    assert significant_token(_norm_name("Lorenzo Lorusso", "tennis_prefix")) == "lorusso"


def test_unique_binds_leipzig_among_a_busy_slate() -> None:
    binds = unique_name_binds(
        "RB Leipzig",
        "Borussia Mönchengladbach",
        _bun_optic(),
        "2026-08-29",
        "mlb_suffix",
    )
    by_poly = {row[0]: row for row in binds}
    assert set(by_poly) == {"RB Leipzig", "Borussia Mönchengladbach"}
    assert by_poly["RB Leipzig"][1] == "RasenBallsport Leipzig"
    assert by_poly["RB Leipzig"][2] == "oid-rbl"
    assert by_poly["Borussia Mönchengladbach"][1] == "Borussia VfL Mönchengladbach"


def test_unique_binds_exact_short_name_when_last_token_missing() -> None:
    fixtures = [
        _optic_row(
            "cs2", "RBL", "RasenBallsport Leipzig", "oid-rbl",
            "QUB", "QUB", "oid-qub",
        )
    ]
    binds = unique_name_binds(
        "RB Leipzig", "QUB", fixtures, "2026-08-29", "mlb_suffix",
    )
    by_poly = {row[0]: row for row in binds}
    assert set(by_poly) == {"RB Leipzig"}
    assert by_poly["RB Leipzig"][2] == "oid-rbl"


def test_unique_binds_skip_when_live_matcher_already_hits() -> None:
    fixtures = [
        _optic_row(
            "spain_-_la_liga", "VCFC", "Valencia CF", "oid-val",
            "RBB", "Real Betis", "oid-bet",
        )
    ]
    assert unique_name_binds(
        "Valencia CF", "Real Betis", fixtures, "2026-08-29", "mlb_suffix",
    ) == []


def test_unique_binds_skip_last_token_collision() -> None:
    fixtures = [
        _optic_row(
            "spain_-_la_liga", "RMA", "Real Madrid", "oid-rma",
            "VAL", "Valencia CF", "oid-val",
        ),
        _optic_row(
            "spain_-_la_liga", "ATM", "Atletico Madrid", "oid-atm",
            "BET", "Real Betis", "oid-bet",
        ),
    ]
    assert unique_name_binds(
        "Real Madrid", "Valencia CF", fixtures, "2026-08-29", "mlb_suffix",
    ) == []


def test_unique_binds_skip_state_suffix() -> None:
    fixtures = [
        _optic_row(
            "ncaaf", "SCO", "Southern Connecticut", "oid-sco",
            "WAG", "Wagner", "oid-wag",
        ),
    ]
    assert unique_name_binds(
        "Southern Connecticut State",
        "Wagner",
        fixtures,
        "2026-08-29",
        "mlb_suffix",
    ) == []


def _tennis_optic() -> list[dict[str, Any]]:
    return [
        _optic_row(
            "itf_men", "", "Lorusso Lorenzo", "oid-lor",
            "", "Kandil Omar", "oid-kan",
        ),
        _optic_row(
            "itf_men", "", "Holger Rune", "oid-run",
            "", "Carlos Alcaraz", "oid-alc",
        ),
    ]


def test_unique_binds_reverse_tennis_names() -> None:
    binds = unique_name_binds(
        "Omar Kandil",
        "Lorenzo Lorusso",
        _tennis_optic(),
        "2026-08-29",
        "tennis_prefix",
    )
    by_poly = {row[0]: row for row in binds}
    assert set(by_poly) == {"Omar Kandil", "Lorenzo Lorusso"}
    assert by_poly["Lorenzo Lorusso"][1] == "Lorusso Lorenzo"
    assert by_poly["Omar Kandil"][2] == "oid-kan"


def test_unique_binds_optic_birth_year() -> None:
    fixtures = [
        _optic_row(
            "itf_women", "", "Katarina 2001 Kuzmova", "oid-kuz",
            "", "Andrea Mchich", "oid-mch",
        ),
    ]
    binds = unique_name_binds(
        "Katarina Kuzmova",
        "Andrea M'chich",
        fixtures,
        "2026-08-29",
        "tennis_prefix",
    )
    by_poly = {row[0]: row for row in binds}
    assert by_poly["Katarina Kuzmova"][1] == "Katarina 2001 Kuzmova"
    assert by_poly["Andrea M'chich"][1] == "Andrea Mchich"


def test_unique_binds_skip_surname_only_rune() -> None:
    assert unique_name_binds(
        "Rune", "Alcaraz", _tennis_optic(), "2026-08-29", "tennis_prefix",
    ) == []


def test_unique_binds_skip_shared_surname_when_only_one_in_window() -> None:
    fixtures = [
        _optic_row(
            "atp_challenger", "", "Thiago Seyboth Wild", "oid-thi",
            "", "Gianmarco Ferrari", "oid-gfi",
        ),
    ]
    assert unique_name_binds(
        "Thiago Seyboth Wild",
        "Francesco Ferrari",
        fixtures,
        "2026-08-29",
        "tennis_prefix",
    ) == []


def test_unique_binds_two_lorusso_still_unique_on_first_name() -> None:
    fixtures = [
        _optic_row(
            "itf_men", "", "Lorusso Lorenzo", "oid-lor",
            "", "Lorusso Marco", "oid-mar",
        ),
    ]
    binds = unique_name_binds(
        "Lorenzo Lorusso",
        "Marco Lorusso",
        fixtures,
        "2026-08-29",
        "tennis_prefix",
    )
    by_poly = {row[0]: row for row in binds}
    assert by_poly["Lorenzo Lorusso"][2] == "oid-lor"
    assert by_poly["Marco Lorusso"][2] == "oid-mar"


def test_harvest_wired_prefix_drafts_poly_name_overlay() -> None:
    result = harvest_gap_pins(
        _bun_store(),
        poly_prefixes=["bun"],
        us_events_fn=list,
        official_events_fn=lambda: [
            {
                **_official_event("bun", "RB Leipzig vs. Borussia Mönchengladbach: O/U 2.5"),
                "slug": "bun-lei-moe-2026-08-29-total-2pt5",
                "outcome_label": "Over",
            },
        ],
        optic_rows_fn=_bun_optic,
    )
    names = [
        (p["canonical_key"], p["aliases"][0]["alias_value"])
        for p in result["pins"]
        if p.get("kind") == "entity_alias"
    ]
    assert ("RBL", "RB Leipzig") in names
    assert ("BMG", "Borussia Mönchengladbach") in names
    assert all(p["aliases"][0]["alias_kind"] == "name" for p in result["pins"])
    assert all(
        any(a.get("sportsbook") == "optic" for a in p["aliases"])
        for p in result["pins"]
        if p.get("kind") == "entity_alias"
    )
    assert not any(p.get("kind") == "mapping_league" for p in result["pins"])
    refs = result["pins"][0]["evidence_refs"]
    joined = "\n".join(refs)
    assert "source:sport:soccer" in joined
    assert "source:league:Germany Bundesliga (germany_bundesliga)" in joined
    assert "polymarket:question:RB Leipzig vs. Borussia Mönchengladbach: O/U 2.5" in joined
    assert "polymarket:market:O/U 2.5" in joined
    assert "polymarket:slug:bun-lei-moe-2026-08-29-total-2pt5" in joined
    assert "polymarket:outcome:Over" in joined
    assert "source:date:2026-08-29" in joined
    assert "polymarket:name:RB Leipzig" in joined or "polymarket:name:Borussia Mönchengladbach" in joined
    assert any(item.startswith("optic:fixture:") for item in refs)
    assert any(item.startswith("optic:competitor:") for item in refs)


def test_harvest_shared_prefix_overlays_each_wired_league() -> None:
    men = _poly_official_league("itf_men", "itf_men", "itf")
    women = _poly_official_league("itf_women", "itf_women", "itf")
    store = _store(
        [
            _team("itf_men", "RBL", "RasenBallsport Leipzig", "oid-rbl"),
            _team("itf_men", "BMG", "Borussia VfL Mönchengladbach", "oid-bmg"),
        ],
        [men, women],
    )
    result = harvest_gap_pins(
        store,
        poly_prefixes=["itf"],
        us_events_fn=list,
        official_events_fn=lambda: [
            _official_event("itf", "RB Leipzig vs. Borussia Mönchengladbach: O/U 2.5"),
        ],
        optic_rows_fn=lambda: [
            _optic_row(
                "itf_men", "RBL", "RasenBallsport Leipzig", "oid-rbl",
                "BMG", "Borussia VfL Mönchengladbach", "oid-bmg",
            ),
        ],
    )
    leagues = {
        p["league"] for p in result["pins"] if p.get("kind") == "entity_alias"
    }
    assert leagues == {"itf_men"}


def _poly_tennis_league() -> LeagueRow:
    return LeagueRow(
        league="itf_men",
        sport="tennis",
        optic_league_id="itf_men",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[
            {
                "sportsbook": "polymarket",
                "enabled": True,
                "parser_profile": "poly_generic_v1",
                "source_league_id": "itf_men",
                "settings": {
                    "slug_prefix": "itf",
                    "optic_league_id": "itf_men",
                    "question_style": "tennis_prefix",
                },
            }
        ],
    )


def test_harvest_wired_prefix_drafts_reverse_tennis_overlay() -> None:
    store = _store(
        [
            _team("itf_men", "LOR", "Lorusso Lorenzo", "oid-lor"),
            _team("itf_men", "KAN", "Kandil Omar", "oid-kan"),
        ],
        [_poly_tennis_league()],
    )
    result = harvest_gap_pins(
        store,
        poly_prefixes=["itf"],
        us_events_fn=list,
        official_events_fn=lambda: [
            _official_event(
                "itf", "M15 Hurghada: Omar Kandil vs Lorenzo Lorusso",
            ),
        ],
        optic_rows_fn=lambda: [
            _optic_row(
                "itf_men", "", "Lorusso Lorenzo", "oid-lor",
                "", "Kandil Omar", "oid-kan",
            ),
        ],
    )
    names = {
        (p["canonical_key"], p["aliases"][0]["alias_value"])
        for p in result["pins"]
        if p.get("kind") == "entity_alias"
    }
    assert ("LOR", "Lorenzo Lorusso") in names
    assert ("KAN", "Omar Kandil") in names


def test_harvest_skips_set_handicap_name_crumbs() -> None:
    store = _store(
        [
            _team("itf_men", "GRU", "Ana Grubor", "oid-gru"),
            _team("itf_men", "MIH", "Anna Mihalka", "oid-mih"),
        ],
        [_poly_tennis_league()],
    )
    result = harvest_gap_pins(
        store,
        poly_prefixes=["itf"],
        us_events_fn=list,
        official_events_fn=lambda: [
            _official_event("itf", "Set Handicap: Mihalka (-1.5) vs Grubor (+1.5)"),
            _official_event("itf", "W15 Haren: Mihalka (-1.5) vs Grubor (+1.5)"),
        ],
        optic_rows_fn=lambda: [
            _optic_row(
                "itf_men", "", "Ana Grubor", "oid-gru",
                "", "Anna Mihalka", "oid-mih",
            ),
        ],
    )
    names = [
        p["aliases"][0]["alias_value"]
        for p in result["pins"]
        if p.get("kind") == "entity_alias"
    ]
    assert names == []


def test_harvest_skips_completed_match_questions() -> None:
    store = _store(
        [
            _team("itf_men", "GRU", "Ana Grubor", "oid-gru"),
            _team("itf_men", "MIH", "Anna Mihalka", "oid-mih"),
        ],
        [_poly_tennis_league()],
    )
    result = harvest_gap_pins(
        store,
        poly_prefixes=["itf"],
        us_events_fn=list,
        official_events_fn=lambda: [
            _official_event(
                "itf",
                "W15 Haren: Completed Match: Anna Mihalka vs Ana Grubor",
            ),
        ],
        optic_rows_fn=lambda: [
            _optic_row(
                "itf_men", "", "Ana Grubor", "oid-gru",
                "", "Anna Mihalka", "oid-mih",
            ),
        ],
    )
    names = [
        p["aliases"][0]["alias_value"]
        for p in result["pins"]
        if p.get("kind") == "entity_alias"
    ]
    assert names == []


def test_harvest_skips_esports_map_winner_questions() -> None:
    league = _poly_official_league("cs2", "cs2", "cs2")
    store = _store(
        [
            _team("cs2", "3DM9", "3DMAX", "oid-3dm"),
            _team("cs2", "INF", "Infinite", "oid-inf"),
        ],
        [league],
    )
    result = harvest_gap_pins(
        store,
        poly_prefixes=["cs2"],
        us_events_fn=list,
        official_events_fn=lambda: [
            _official_event(
                "cs2",
                "Counter-Strike: 3DMAX vs Infinite - Map 2 Winner",
            ),
        ],
        optic_rows_fn=lambda: [
            _optic_row(
                "cs2", "3DM9", "3DMAX", "oid-3dm",
                "INF", "Infinite", "oid-inf",
            ),
        ],
    )
    names = [
        p["aliases"][0]["alias_value"]
        for p in result["pins"]
        if p.get("kind") == "entity_alias"
    ]
    assert names == []
    assert not any(row.get("reason") == "name_ambiguous" for row in result["skipped"])


def test_harvest_esports_series_moneyline_already_mapped_is_silent() -> None:
    league = _poly_official_league("cs2", "cs2", "cs2")
    store = _store(
        [
            _team("cs2", "3DM9", "3DMAX", "oid-3dm"),
            _team("cs2", "INF", "Infinite", "oid-inf"),
        ],
        [league],
    )
    result = harvest_gap_pins(
        store,
        poly_prefixes=["cs2"],
        us_events_fn=list,
        official_events_fn=lambda: [
            _official_event(
                "cs2",
                "Counter-Strike: 3DMAX vs Infinite (BO3) - ESL Pro League",
            ),
        ],
        optic_rows_fn=lambda: [
            _optic_row(
                "cs2", "3DM9", "3DMAX", "oid-3dm",
                "INF", "Infinite", "oid-inf",
            ),
        ],
    )
    names = [
        p["aliases"][0]["alias_value"]
        for p in result["pins"]
        if p.get("kind") == "entity_alias"
    ]
    assert names == []
    assert not any(row.get("reason") == "name_ambiguous" for row in result["skipped"])


def test_harvest_skips_first_to_score_questions() -> None:
    store = _bun_store()
    result = harvest_gap_pins(
        store,
        poly_prefixes=["bun"],
        us_events_fn=list,
        official_events_fn=lambda: [
            _official_event(
                "bun",
                "RB Leipzig to score first vs. Borussia Mönchengladbach?",
            ),
        ],
        optic_rows_fn=_bun_optic,
    )
    names = [
        p["aliases"][0]["alias_value"]
        for p in result["pins"]
        if p.get("kind") == "entity_alias"
    ]
    assert names == []


def test_harvest_soccer_draw_already_mapped_is_silent() -> None:
    """Both Poly names already ARE the Optic names -- no pin, and no AI skip."""
    result = harvest_gap_pins(
        _bun_store(),
        poly_prefixes=["bun"],
        us_events_fn=list,
        official_events_fn=lambda: [
            _official_event(
                "bun",
                "Will RasenBallsport Leipzig vs. Borussia VfL Mönchengladbach "
                "end in a draw?",
            ),
        ],
        optic_rows_fn=_bun_optic,
    )
    names = [
        p["aliases"][0]["alias_value"]
        for p in result["pins"]
        if p.get("kind") == "entity_alias"
    ]
    assert names == []
    assert not any(row.get("reason") == "name_ambiguous" for row in result["skipped"])


def test_harvest_soccer_draw_still_pins_short_poly_names() -> None:
    """Teaching the draw grammar must not silence the overlays it should draft."""
    result = harvest_gap_pins(
        _bun_store(),
        poly_prefixes=["bun"],
        us_events_fn=list,
        official_events_fn=lambda: [
            _official_event(
                "bun",
                "Will RB Leipzig vs. Borussia Mönchengladbach end in a draw?",
            ),
        ],
        optic_rows_fn=_bun_optic,
    )
    names = sorted(
        p["aliases"][0]["alias_value"]
        for p in result["pins"]
        if p.get("kind") == "entity_alias"
    )
    assert names == ["Borussia Mönchengladbach", "RB Leipzig"]


def test_ambiguous_skip_silent_when_needle_is_already_an_optic_name() -> None:
    """Fail-safe for grammars we have not taught: never ask AI about an exact name."""
    row = _poly_official_league("germany_bundesliga", "germany_-_bundesliga", "bun")
    window = _bun_optic()[:1]
    event = {"prefix": "bun", "question": "unparsed", "date": "2026-08-29"}
    assert _ambiguous_skip(
        row,
        event,
        ("RasenBallsport Leipzig", "Borussia VfL Mönchengladbach end in a shootout"),
        window,
        "mlb_suffix",
    ) is None
    still_useful = _ambiguous_skip(
        row, event, ("Leipzig B", "Gladbach B"), window, "mlb_suffix",
    )
    assert still_useful is not None
    assert still_useful["needle"] == "Leipzig B"


def test_harvest_name_ambiguous_ttls_official_prefix() -> None:
    events = [_official_event("bun", "Will Mystery FC beat Other FC?")]
    result = harvest_gap_pins(
        _bun_store(),
        poly_prefixes=["bun"],
        us_events_fn=list,
        official_events_fn=lambda: events,
        optic_rows_fn=_bun_optic,
    )
    assert any(row.get("reason") == "name_ambiguous" for row in result["skipped"])
    assert "bun" in load_dead_buckets("polymarket")
    again = harvest_gap_pins(
        _bun_store(),
        poly_prefixes=["bun"],
        us_events_fn=list,
        official_events_fn=lambda: events,
        optic_rows_fn=_bun_optic,
    )
    assert not any(row.get("reason") == "name_ambiguous" for row in again["skipped"])


def test_alias_from_pin_keeps_source_evidence() -> None:
    pin = {
        "kind": "entity_alias",
        "league": "germany_bundesliga",
        "canonical_key": "RBL",
        "canonical_name": "RasenBallsport Leipzig",
        "entity_type": "team",
        "aliases": [{"sportsbook": "polymarket", "alias_kind": "name", "alias_value": "RB Leipzig"}],
        "evidence_refs": [
            "source:sport:soccer",
            "polymarket:question:RB Leipzig vs. Borussia Mönchengladbach: O/U 2.5",
        ],
        "reassign": False,
    }
    payload = _alias_from_pin(pin)
    assert payload.evidence_refs == pin["evidence_refs"]
