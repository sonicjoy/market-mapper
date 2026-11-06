"""Tip crypto_id vs catalogue name mismatch lines."""

from BigQuery.crypto_id_name_check import format_alert, mismatch_rows


def test_mismatch_rows_flags_swap() -> None:
    pins = [
        {
            "league": "ufc",
            "canonical_key": "NUR",
            "canonical_name": "Umar Nurmagomedov",
            "crypto_id": "140000440",
        },
        {
            "league": "ufc",
            "canonical_key": "SYO",
            "canonical_name": "Song Yadong",
            "crypto_id": "140000905",
        },
    ]
    live = {"140000440": "Song Yadong", "140000905": "Umar Nurmagomedov"}
    lines = mismatch_rows(pins, live)
    assert len(lines) == 2
    assert any("matches SYO" in line for line in lines)
    assert any("matches NUR" in line for line in lines)
    text = format_alert(lines)
    assert "2 pin(s)" in text


def test_mismatch_rows_accepts_fc_suffix() -> None:
    pins = [{
        "league": "france_ligue_1",
        "canonical_key": "LMN",
        "canonical_name": "Le Mans",
        "crypto_id": "1",
    }]
    assert mismatch_rows(pins, {"1": "Le Mans FC"}) == []


def test_mismatch_rows_ignores_kalshi_note_and_longer_club() -> None:
    pins = [{
        "league": "argentina_primera",
        "canonical_key": "GEM",
        "canonical_name": "CA Gimnasia y Esgrima de Mendoza -- Kalshi uses GEM",
        "crypto_id": "9",
    }]
    assert mismatch_rows(pins, {"9": "CA Gimnasia y Esgrima de Mendoza"}) == []


def test_mismatch_rows_accepts_player_middle_name() -> None:
    pins = [{
        "league": "atp",
        "canonical_key": "WON",
        "canonical_name": "Chak Lam Coleman Wong",
        "crypto_id": "1",
    }]
    assert mismatch_rows(pins, {"1": "Coleman Wong"}) == []
