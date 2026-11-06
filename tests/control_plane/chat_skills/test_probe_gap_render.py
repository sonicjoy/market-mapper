"""probe_gap verify table, manual-map copy, and offer buttons."""

from __future__ import annotations

from mappers.control_plane.chat_skills.probe_gap_render import (
    crypto_anatomy,
    manual_lines,
    manual_prefill,
    on_tip_lines,
    tip_lines,
    verdict_table,
    verify_lines,
)
from mappers.control_plane.chat_skills.render import cart_buttons, prefill_buttons


def test_verify_lines_show_fixture_and_selection() -> None:
    row = {
        "optic": {
            "fixture_id": "fx-usc",
            "start_date": "2026-08-12T19:00:00Z",
            "home": "PSG",
            "away": "Aston Villa",
        }
    }
    mapped = [{
        "sportsbook": "Kalshi",
        "market_ticker": "KXUEFASCGAME-26AUG12PSGAVL-TIE",
        "market_type": "moneyline_3way",
        "entity": "game",
        "line": "",
        "side": "_TIE",
        "selection": "Draw",
        "home": "PSG",
        "away": "Aston Villa",
        "start_date": "2026-08-12T19:00:00Z",
        "fixture_id": "fx-usc",
        "game_id": "game-usc",
    }]
    text = "\n".join(verify_lines(row, mapped))
    assert "**Fixture:** PSG vs Aston Villa" in text
    assert "moneyline_3way" in text
    assert "Draw" in text
    assert "`game-usc`" in text


def test_maker_lag_table_is_not_manual_map() -> None:
    text = "\n".join(
        verdict_table(
            "NX.F.OPT.TENNIS-0015-260902-M.O.1.1.20261231",
            "maker_lag",
            {
                "symbol": "NX.F.OPT.TENNIS-0015-260902-M.O.1.1.20261231",
                "kind": "already_mapped",
                "league": "wta",
                "codes": ["942505", "847110"],
                "tip": [
                    {"crypto_id": "942505", "owners": ["OSK8"]},
                    {"crypto_id": "847110", "owners": ["RAK"]},
                ],
                "mapped_rows": [],
                "optic": {
                    "fixture_id": "20260902A98210F7",
                    "home": "Oksana Selekhmeteva",
                    "away": "Kamilla Rakhimova",
                },
            },
        )
    )
    assert "**Map manually**" not in text
    assert "**Already mapped**" in text
    assert "We have not mapped this." not in text
    assert "`942505` → OSK8" in text
    assert "20260902A98210F7" in text


def test_on_tip_lines_show_codes_and_optic() -> None:
    text = "\n".join(
        on_tip_lines(
            {
                "codes": ["SIN", "ALC"],
                "tip": [{"code": "SIN", "owners": ["SINNER"]}],
                "optic": {"fixture_id": "fx-sin", "home": "Sinner", "away": "Alcaraz"},
            }
        )
    )
    assert "**Already mapped**" in text
    assert "`SIN`" in text
    assert "fx-sin" in text


def test_manual_lines_include_codes_and_unpinned_tip() -> None:
    row = {
        "event_ticker": "KXUEFASCGAME-26AUG12PSGAVL",
        "market_ticker": "KXUEFASCGAME-26AUG12PSGAVL-TIE",
        "sub_title": "Paris Saint-Germain vs Aston Villa",
        "codes": ["PSG", "AVL", "TIE"],
        "tip": [
            {"code": "PSG", "owners": ["PSG"]},
            {"code": "AVL", "owners": []},
        ],
        "optic": {},
        "status": "finalized",
        "result": "no",
    }
    text = "\n".join(manual_lines(row))
    assert "**Map manually**" in text
    assert "`KXUEFASCGAME-26AUG12PSGAVL`" in text
    assert "`KXUEFASCGAME-26AUG12PSGAVL-TIE`" in text
    assert "`PSG` → PSG" in text
    assert "`AVL` → (unpinned)" in text
    assert "Optic: none" in text


def test_tip_lines_accept_bare_canonical_names() -> None:
    text = "\n".join(tip_lines(["SINNER", "ALCARAZ"]))
    assert "`SINNER`" in text
    assert "`ALCARAZ`" in text


def test_single_pin_uses_add_to_cart_label() -> None:
    buttons = cart_buttons(1)
    assert [b.label for b in buttons] == ["Add to cart", "Not now"]
    many = cart_buttons(2)
    assert [b.label for b in many] == ["Add all to cart", "Not now"]


def test_manual_prefill_needs_league_and_code() -> None:
    assert manual_prefill({"league": "mlb", "codes": ["XYZ"]}, "px", "code") == {
        "tab": "alias",
        "league": "mlb",
        "sportsbook": "px",
        "code": "XYZ",
        "canonical_key": "",
        "entity_name": "",
        "entity_type": "team",
        "alias_kind": "code",
    }
    assert manual_prefill({"league": "", "codes": ["XYZ"]}, "px", "code") is None
    assert [b.send for b in prefill_buttons()] == ["prefill entry", "no"]


_EPL_SYM = "NX.F.OPT.EPL-00001-260828-M.O.1.64.20261230"


def test_crypto_anatomy_unpacks_epl_slot_symbol() -> None:
    parts = crypto_anatomy(_EPL_SYM)
    assert parts["token"] == "EPL"
    assert parts["event_id"] == "00001"
    assert parts["kickoff"] == "2026-08-28"
    assert parts["fixture_prefix"] == "NX.F.OPT.EPL-00001-260828"
    assert parts["market_slot"] == "1.64"
    assert parts["slot_hint"] == "opaque without catalogue"
    assert parts["maturity"] == "20261230"


def test_catalogue_miss_table_shows_ticker_anatomy() -> None:
    text = "\n".join(
        verdict_table(
            _EPL_SYM,
            "expected_residual",
            {
                "symbol": _EPL_SYM,
                "kind": "catalogue_miss",
                "mapped_rows": [],
                "optic": {},
            },
        )
    )
    assert "crypto.com" in text
    assert "| League | EPL |" in text
    assert "2026-08-28" in text
    assert "not in crypto_security_def" in text
    assert "`M.O.1.64`" in text
    assert "wait for upstream" in text
    assert "NX.F.OPT.EPL-00001-260828" in text


def test_unmapped_poly_table_shows_id_kind() -> None:
    token = "ab" * 32
    text = "\n".join(
        verdict_table(
            token,
            "expected_residual",
            {
                "symbol": token,
                "kind": "unmapped",
                "sportsbook": "polymarket",
                "id_kind": "condition_id",
                "norm_id": "0x" + token,
                "slug": "epl-ars-che",
                "outcomes": ["Yes", "No"],
                "title": "Will Arsenal win?",
                "mapped_rows": [],
                "optic": {},
            },
        )
    )
    assert "Polymarket" in text
    assert "`condition_id`" in text
    assert "epl-ars-che" in text
    assert "`Yes`" in text
    assert "Gamma slug/question" in text


def test_unmapped_px_table_shows_event() -> None:
    text = "\n".join(
        verdict_table(
            "730003207",
            "expected_residual",
            {
                "symbol": "730003207",
                "kind": "unmapped",
                "sportsbook": "px",
                "id_kind": "px_id",
                "title": "Lakers vs Celtics",
                "tournament": "NBA",
                "mapped_rows": [],
                "optic": {"home": "Lakers", "away": "Celtics", "start_date": "2026-08-28"},
            },
        )
    )
    assert "Prophet X" in text
    assert "Lakers vs Celtics" in text
    assert "PX fetch snapshot" in text
    assert "NBA" in text


def test_unmapped_novig_table_shows_event() -> None:
    ident = "01a03c33-d23f-7040-90cb-d64c165ae185"
    text = "\n".join(
        verdict_table(
            ident,
            "expected_residual",
            {
                "symbol": ident,
                "kind": "unmapped",
                "sportsbook": "novig",
                "id_kind": "novig_event",
                "title": "Lakers vs Celtics",
                "novig_type": "GAME",
                "mapped_rows": [],
                "optic": {
                    "fixture_id": "20260828ABC",
                    "home": "Lakers",
                    "away": "Celtics",
                    "start_date": "2026-08-28",
                },
            },
        )
    )
    assert "Novig" in text
    assert "Lakers vs Celtics" in text
    assert "Novig fetch snapshot" in text
    assert "`GAME`" in text
    assert "20260828ABC" in text


def test_unmapped_poly_us_symbol_shows_gateway_fields() -> None:
    ticker = "aec-atp-benbon-botzan-2026-08-27"
    text = "\n".join(
        verdict_table(
            ticker,
            "expected_residual",
            {
                "symbol": ticker,
                "kind": "unmapped",
                "sportsbook": "polymarket_usa",
                "id_kind": "us_symbol",
                "title": "benbon vs botzan",
                "sports_market_type": "tennis_match_winner",
                "mapped_rows": [],
                "optic": {"home": "benbon", "away": "botzan", "start_date": "2026-08-27"},
            },
        )
    )
    assert "Polymarket (USA)" in text
    assert "benbon vs botzan" in text
    assert "`tennis_match_winner`" in text
    assert "gateway fields" in text
