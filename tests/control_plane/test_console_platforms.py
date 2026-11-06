"""Explore platform registry."""

from __future__ import annotations

from mappers.control_plane.console_platforms import (
    default_missing_platform_id,
    explore_platform,
    explore_platforms,
    explore_platforms_payload,
)


def test_explore_platforms_include_crypto_and_kalshi() -> None:
    ids = {row.id for row in explore_platforms()}
    assert "crypto" in ids
    assert "kalshi" in ids
    assert "underdog" in ids


def test_crypto_maps_to_crypto_com_sportsbook() -> None:
    row = explore_platform("crypto")
    assert row is not None
    assert row.sportsbook == "crypto.com"
    assert row.missing_catalogue is True


def test_meta_payload_shape() -> None:
    payload = explore_platforms_payload()
    assert payload[0]["id"]
    assert "unmapped_inventory" in payload[0]
    assert default_missing_platform_id() == "crypto"
