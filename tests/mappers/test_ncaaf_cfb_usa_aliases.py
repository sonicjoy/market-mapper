"""NCAAF Polymarket US CFB code pins for Path 2."""

from scripts.submit_ncaaf_cfb_usa_aliases import build_payload


def test_payload_pins_mismatched_usa_codes() -> None:
    payload = build_payload()
    by_key = {row.canonical_key: row for row in payload.entity_aliases}
    assert set(by_key) == {
        "UNC", "SJSU", "NCSU", "UVA", "JVST", "NDSU",
        "SAC", "EMU", "HAW", "NMSU", "FSU", "MEM",
    }
    unc = { (a.sportsbook, a.alias_kind, a.alias_value) for a in by_key["UNC"].aliases }
    assert ("polymarket_usa", "code", "NCAR") in unc
    assert ("optic", "external_id", "D8E9069D0DAD") in unc
    ncsu = { (a.sportsbook, a.alias_kind, a.alias_value) for a in by_key["NCSU"].aliases }
    assert ("polymarket_usa", "code", "NCST") in ncsu
    assert not [a for a in ncsu if a[0] == "kalshi"]
    uva = { (a.sportsbook, a.alias_kind, a.alias_value) for a in by_key["UVA"].aliases }
    assert ("polymarket_usa", "code", "VIR") in uva
    assert by_key["UNC"].canonical_name == "North Carolina"
