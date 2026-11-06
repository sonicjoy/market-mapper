"""Manifest generator contract tests: listing parse, tick
classification, deterministic TOML emission, tier preservation."""
import tomllib

import pytest

from regression.build_manifest import (classify, emit_manifest,
                                       existing_tiers, parse_listing,
                                       split_tick)

LISTING = """\
gs://rs-marketmaking-mapping/corpus/data/2026-03-06/19_57/optic_fixtures_odds.jsonl:
  Creation Time:               2026-08-07T05:28:53Z
  Content-Length:              123
  Content-Type:                application/octet-stream
  Hash (CRC32C):               plh63A==
  Hash (MD5):                  c8EMG+vjyCzuTCio6VId0g==
gs://rs-marketmaking-mapping/corpus/data/2026-03-06/19_57/gold/nba.jsonl:
  Content-Length:              456
  Hash (MD5):                  AAAAG+vjyCzuTCio6VId0g==
"""


def test_parse_listing():
    got = parse_listing(LISTING)
    assert got == {
        "data/2026-03-06/19_57/optic_fixtures_odds.jsonl":
            (123, "c8EMG+vjyCzuTCio6VId0g=="),
        "data/2026-03-06/19_57/gold/nba.jsonl":
            (456, "AAAAG+vjyCzuTCio6VId0g=="),
    }


def test_parse_listing_rejects_missing_hash():
    with pytest.raises(ValueError):
        parse_listing("gs://rs-marketmaking-mapping/corpus/data/"
                      "2026-03-06/19_57/x.jsonl:\n"
                      "  Content-Length:              1\n")


def test_split_tick():
    assert split_tick("data/2026-03-06/19_57/gold/nba.jsonl") == \
        ("2026-03-06/19_57", "gold/nba.jsonl")
    with pytest.raises(ValueError):
        split_tick("data/stray.jsonl")


def test_classify_exchanges_aux_empty():
    got = classify({
        "optic_fixtures_odds.jsonl": 100,
        "kalshi_markets.jsonl": 50,
        "prophetx_markets.jsonl": 0,     # empty -> not present
        "prophetx_events.jsonl": 10,     # companion, never aux
        "mappings.jsonl": 30,
        "gold/nba.jsonl": 20,
    })
    assert got == {"bytes": 210,
                   "exchanges": ["kalshi"],
                   "aux": ["gold/nba.jsonl", "mappings.jsonl"],
                   "empty_files": ["prophetx_markets.jsonl"]}


def test_classify_requires_optic():
    with pytest.raises(ValueError):
        classify({"kalshi_markets.jsonl": 50})


def _ticks():
    return {"2026-03-06/19_57": {
        "tier": "smoke", "bytes": 210,
        "exchanges": ["kalshi"], "aux": ["gold/nba.jsonl"],
        "empty_files": [],
        "leagues": ["nba", 'weird "league"']}}


def test_emit_round_trips_through_toml():
    text = emit_manifest(
        {"bucket": "gs://b/corpus", "ticks": 1, "files": 6,
         "bytes": 210}, _ticks())
    doc = tomllib.loads(text)
    assert doc["corpus"]["bytes"] == 210
    [t] = doc["tick"]
    assert t["id"] == "2026-03-06/19_57"
    assert t["tier"] == "smoke"
    assert t["leagues"] == ["nba", 'weird "league"']


def test_emit_is_deterministic():
    corpus = {"bucket": "b", "ticks": 1, "files": 6, "bytes": 210}
    assert emit_manifest(corpus, _ticks()) == \
        emit_manifest(corpus, _ticks())


def test_existing_tiers_preserved(tmp_path):
    corpus = {"bucket": "b", "ticks": 1, "files": 6, "bytes": 210}
    p = tmp_path / "manifest.toml"
    p.write_text(emit_manifest(corpus, _ticks()))
    assert existing_tiers(p) == {"2026-03-06/19_57": "smoke"}
    assert existing_tiers(tmp_path / "absent.toml") == {}
