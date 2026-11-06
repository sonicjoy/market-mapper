"""Tests for crypto.com feed-name alias helpers."""

from fetch.crypto_com_aliases import (
    feed_team_names_match,
    normalize_feed_team_name,
    resolve_feed_name_to_code,
    resolve_feed_name_to_crypto_id,
)


def test_normalize_strips_prefixes_and_suffixes():
    assert normalize_feed_team_name("Győri ETO FC") == "gyori eto"
    assert normalize_feed_team_name("ETO FC") == "eto"
    assert normalize_feed_team_name("Ararat-Armenia FA") == "ararat armenia"


def test_feed_team_names_match_ucl_variants():
    assert feed_team_names_match("Ararat-Armenia FA", "Ararat-Armenia FC")
    assert feed_team_names_match("ETO FC", "Győri ETO FC")
    assert feed_team_names_match("KF Vikingur", "Víkingur Reykjavík")
    assert feed_team_names_match("SK Iberia 1999", "FC Iberia 1999")
    assert feed_team_names_match("FC Flora", "FC Flora Tallinn")
    assert not feed_team_names_match("FC Flora", "Floriana FC")


def test_resolve_feed_name_to_crypto_id_strict():
    mapping = {
        "Kuopion PS": "90001487",
        "Győri ETO FC": "90004202",
        "São Paulo FC": "90000933",
    }
    assert resolve_feed_name_to_crypto_id("Győri ETO FC", mapping) == "90004202"
    assert resolve_feed_name_to_crypto_id("Sao Paulo FC", mapping) == "90000933"
    assert resolve_feed_name_to_crypto_id("ETO FC", mapping) is None
    assert resolve_feed_name_to_crypto_id("Kuopion Palloseura", mapping) is None


def test_resolve_feed_name_to_code_strict():
    candidates = {
        "Győri ETO FC": "GYO",
        "Ararat-Armenia FC": "ARM",
        "Santos FC Sao Paulo": "SAN",
        "Sao Paulo FC": "SAO",
    }
    assert resolve_feed_name_to_code("Ararat-Armenia FC", candidates) == "ARM"
    assert resolve_feed_name_to_code("Sao Paulo FC", candidates) == "SAO"
    assert resolve_feed_name_to_code("ETO FC", candidates) is None
    assert resolve_feed_name_to_code("Ararat-Armenia FA", candidates) is None
    assert resolve_feed_name_to_code("Sao Paulo FC", candidates, player=True) == "SAO"
