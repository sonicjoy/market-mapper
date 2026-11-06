"""Mapper Chat DKEX tools: recognise a ticker and read its anatomy from the catalogue."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fetch.dkex import normalize
from mappers.control_plane.chat_tools_dkex_mapping import (
    classify_dkex_symbol,
    dkex_symbol_fields,
    find_dkex_symbol,
)

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dkex" / "staging_markets_2026-09-28.json"
_TICKER = "BSA-MOVY-FG-02L4HV50HIO28DG-SALO008-GTE-P00035"


def _catalogue(tmp_path: Path) -> Path:
    path = tmp_path / "dkex_markets.jsonl"
    rows = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    path.write_text("".join(json.dumps(normalize(r, "api")) + "\n" for r in rows), encoding="utf-8")
    return path


def test_a_catalogue_ticker_is_recognised(tmp_path: Path) -> None:
    path = _catalogue(tmp_path)
    assert find_dkex_symbol(f"why is `{_TICKER}` unmapped?", path) == _TICKER


@pytest.mark.parametrize("text", [
    "",
    "hello",
    "KXNFLGAME-26OCT04DENSF",
    # DKEX-shaped but not listed: shape alone is never enough.
    "BSA-MOVY-FG-02L4HV50HIO28DG-SALO008-GTE-P00045",
])
def test_a_token_the_catalogue_does_not_list_is_not_dkex(tmp_path: Path, text: str) -> None:
    assert find_dkex_symbol(text, _catalogue(tmp_path)) == ""


def test_no_catalogue_recognises_nothing() -> None:
    assert find_dkex_symbol(_TICKER, None) == ""


def test_classify_is_recognition_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _catalogue(tmp_path)
    monkeypatch.setenv("MAPPING_DATA_DIR", str(tmp_path))
    out = classify_dkex_symbol(_TICKER)
    assert out == {"id": _TICKER, "norm_id": _TICKER, "sportsbook": "dkex", "id_kind": "dkex_symbol"}


def test_anatomy_comes_from_the_typed_catalogue_row(tmp_path: Path) -> None:
    raw = next(r for r in json.loads(_FIXTURE.read_text(encoding="utf-8")) if r["ticker"] == _TICKER)
    path = tmp_path / "dkex_markets.jsonl"
    path.write_text(json.dumps(normalize(raw, "api")) + "\n", encoding="utf-8")
    fields = dkex_symbol_fields(_TICKER, path)
    assert fields["league"] == "BSA"
    assert (fields["market"], fields["period"]) == ("MOVY", "FG")
    assert fields["participant_name"] == "Sao Paulo"
    assert fields["strike_price"] == 3.5
    assert fields["event_id"] == "02L4HV50HIO28DG"


def test_no_catalogue_row_means_no_anatomy(tmp_path: Path) -> None:
    """Without the typed row nothing is sliced out of the ticker."""
    path = tmp_path / "dkex_markets.jsonl"
    path.write_text("", encoding="utf-8")
    assert dkex_symbol_fields(_TICKER, path) == {}
