"""Tests for per-symbol crypto.com row attachment (no symbol overwrite)."""

from __future__ import annotations

from mappers.pipeline import _report_crypto_match_stats, attach_crypto_row, row_key
from mappers.shared import TIE_SIDE, CanonicalRow


def _ml_row(
    *,
    symbol: str,
    security_id: str,
    side: str = "GER",
    optic_id: str | None = None,
) -> CanonicalRow:
    return CanonicalRow(
        league="world_cup",
        start_date="2026-06-25T20:00:00+00:00",
        home="ECU",
        away="GER",
        market_type="moneyline_3way",
        side=side,
        optic_id=optic_id,
        crypto_security_id=security_id,
        crypto_symbol=symbol,
        crypto_market_id="m1",
        crypto_outcome_id="o1",
        crypto_selection_name="Germany to win",
    )


def _attach_all(*rows: CanonicalRow) -> list[CanonicalRow]:
    row_index: dict[tuple, CanonicalRow] = {}
    alt_crypto: dict[tuple[tuple, str], CanonicalRow] = {}
    all_rows: list[CanonicalRow] = []
    for cr in rows:
        attach_crypto_row(row_index, alt_crypto, all_rows, cr)
    return all_rows


def test_alternate_symbols_emit_separate_rows():
    """RFQ keys on exact symbol — two live symbols for one bet need two rows."""
    bare = _ml_row(
        symbol="NX.F.OPT.FIFA-00002-260625-M.O.1.2",
        security_id="202606240001000000000001D",
    )
    suffixed = _ml_row(
        symbol="NX.F.OPT.FIFA-00007-260625-M.O.1.2.20260830",
        security_id="202606240002000000000002D",
    )
    rows = _attach_all(bare, suffixed)
    symbols = {r.crypto_symbol for r in rows}
    assert symbols == {
        "NX.F.OPT.FIFA-00002-260625-M.O.1.2",
        "NX.F.OPT.FIFA-00007-260625-M.O.1.2.20260830",
    }
    assert len(rows) == 2
    assert row_key(rows[0]) == row_key(rows[1])
    assert not rows[0].crypto_satellite
    assert rows[1].crypto_satellite


def test_same_symbol_keeps_latest_security_id():
    older = _ml_row(
        symbol="NX.F.OPT.FIFA-00002-260625-M.O.1.2",
        security_id="202606240001000000000001D",
    )
    newer = _ml_row(
        symbol="NX.F.OPT.FIFA-00002-260625-M.O.1.2",
        security_id="202606240099000000000099D",
    )
    rows = _attach_all(older, newer)
    assert len(rows) == 1
    assert rows[0].crypto_security_id == "202606240099000000000099D"


def test_crypto_attaches_to_existing_optic_row_without_clobbering_symbol():
    optic_row = CanonicalRow(
        league="world_cup",
        start_date="2026-06-25T20:00:00+00:00",
        home="ECU",
        away="GER",
        market_type="moneyline_3way",
        side="GER",
        optic_id="optic-1",
    )
    row_index = {row_key(optic_row): optic_row}
    alt_crypto: dict[tuple[tuple, str], CanonicalRow] = {}
    all_rows = [optic_row]

    attach_crypto_row(
        row_index, alt_crypto, all_rows,
        _ml_row(
            symbol="NX.F.OPT.FIFA-00007-260625-M.O.1.2.20260830",
            security_id="202606240002000000000002D",
            optic_id=None,
        ),
    )
    assert len(all_rows) == 1
    assert optic_row.crypto_symbol == "NX.F.OPT.FIFA-00007-260625-M.O.1.2.20260830"
    assert optic_row.optic_id == "optic-1"

    attach_crypto_row(
        row_index, alt_crypto, all_rows,
        _ml_row(
            symbol="NX.F.OPT.FIFA-00002-260625-M.O.1.2",
            security_id="202606240001000000000001D",
        ),
    )
    assert len(all_rows) == 2
    assert all_rows[1].crypto_symbol == "NX.F.OPT.FIFA-00002-260625-M.O.1.2"
    assert all_rows[1].optic_id == "optic-1"
    assert not optic_row.crypto_satellite
    assert all_rows[1].crypto_satellite


def test_draw_leg_does_not_collide_with_team_legs():
    home = _ml_row(
        symbol="NX.F.OPT.FIFA-00006-260625-M.O.1.1",
        security_id="202606240001000000000001D",
        side="TUR",
    )
    draw = _ml_row(
        symbol="NX.F.OPT.FIFA-00006-260625-M.O.1.3",
        security_id="202606240003000000000003D",
        side=TIE_SIDE,
    )
    rows = _attach_all(home, draw)
    assert len(rows) == 2


def test_optic_vs_fix_disagreement_latest_timestamp_wins():
    """Optic PM.NPO stamp vs FIX semantic stamp: replace, do not satellite."""
    optic_stamp = _ml_row(
        symbol="NX.F.OPT.FIFA-00002-260625-M.O.1.2.20260830",
        security_id="202606240002000000000002D",
    )
    optic_stamp.crypto_market_id = (
        "FIFA-00002-260625-M-MLAway-O12_260830-2300_1_PM.NPO"
    )
    optic_stamp.crypto_source_ts = 100.0

    fix_newer = _ml_row(
        symbol="NX.F.OPT.FIFA-00007-260625-M.O.1.2",
        security_id="202606249999000000000099D",
    )
    fix_newer.crypto_market_id = "202606240001"
    fix_newer.crypto_source_ts = 200.0

    rows = _attach_all(optic_stamp, fix_newer)
    assert len(rows) == 1
    assert rows[0].crypto_symbol == "NX.F.OPT.FIFA-00007-260625-M.O.1.2"
    assert rows[0].crypto_security_id == "202606249999000000000099D"


def test_optic_vs_fix_missing_timestamps_keeps_incumbent():
    optic_stamp = _ml_row(
        symbol="NX.F.OPT.FIFA-00002-260625-M.O.1.2.20260830",
        security_id="202606240002000000000002D",
    )
    optic_stamp.crypto_market_id = (
        "FIFA-00002-260625-M-MLAway-O12_260830-2300_1_PM.NPO"
    )
    optic_stamp.crypto_source_ts = None

    fix_row = _ml_row(
        symbol="NX.F.OPT.FIFA-00007-260625-M.O.1.2",
        security_id="202606249999000000000099D",
    )
    fix_row.crypto_market_id = "202606240001"
    fix_row.crypto_source_ts = None

    rows = _attach_all(optic_stamp, fix_row)
    assert len(rows) == 1
    assert rows[0].crypto_symbol == optic_stamp.crypto_symbol


def test_same_symbol_preserves_optic_market_id_when_fix_fresher():
    optic_stamp = _ml_row(
        symbol="NX.F.OPT.FIFA-00002-260625-M.O.1.2",
        security_id="202606240001000000000001D",
    )
    optic_stamp.crypto_market_id = (
        "FIFA-00002-260625-M-MLAway-O12_260830-2300_1_PM.NPO"
    )
    optic_stamp.crypto_source_ts = 100.0

    fix_newer = _ml_row(
        symbol="NX.F.OPT.FIFA-00002-260625-M.O.1.2",
        security_id="202606249999000000000099D",
    )
    fix_newer.crypto_market_id = "202606240001"
    fix_newer.crypto_source_ts = 200.0

    rows = _attach_all(optic_stamp, fix_newer)
    assert len(rows) == 1
    assert rows[0].crypto_security_id == "202606249999000000000099D"
    mid = rows[0].crypto_market_id
    assert mid is not None and "PM.NPO" in mid


def test_wholly_unmatched_crypto_slate_warns(capsys):
    """A whole slate in the other-date bucket is a look-back/horizon miss."""
    _report_crypto_match_stats(
        "mls",
        {"2026-08-15", "2026-08-16", "2026-08-19"},
        matched=0,
        flipped=0,
        no_fixture=0,
        other_date=32,
    )
    err = capsys.readouterr().err
    assert "crypto: 0 games matched, 32 other-date skipped" in err
    assert "WARN: crypto [mls]: none of 32 listed games" in err
    assert "2026-08-15, 2026-08-16, 2026-08-19" in err


def test_partly_matched_crypto_slate_does_not_warn(capsys):
    """Individual other-date games map from their own tick — not a warning."""
    _report_crypto_match_stats(
        "mls",
        {"2026-08-15"},
        matched=11,
        flipped=1,
        no_fixture=0,
        other_date=4,
    )
    err = capsys.readouterr().err
    assert "crypto: 11 games matched, 1 flipped, 4 other-date skipped" in err
    assert "WARN" not in err
