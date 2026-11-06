"""Corpus materializer contract tests: root resolution, manifest
parsing, verify-on-pull for both cached and downloaded files."""
import hashlib
from pathlib import Path

import pytest

from regression.corpus import (CorpusIntegrityError, cache_root,
                               ensure_tick, read_sha256_manifest,
                               tick_files)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


TICK = "2026-07-29/16_19"
GOOD = b"good bytes\n"


def _manifest():
    return {f"data/{TICK}/optic_fixtures_odds.jsonl": _sha(GOOD),
            f"data/{TICK}/kalshi_markets.jsonl": _sha(b"k\n"),
            "data/2026-03-06/19_57/optic_fixtures_odds.jsonl": _sha(b"x")}


def test_cache_root_env_var_wins():
    root, why = cache_root({"MM_CORPUS_CACHE": "/tmp/corpus"})
    # Compare Path objects — str(Path) uses OS separators (Windows `\`).
    assert root == Path("/tmp/corpus") and "MM_CORPUS_CACHE" in why


def test_cache_root_fixed_default():
    root, why = cache_root({})
    assert root.name == "mm-corpus" and "unset" in why


def test_read_sha256_manifest(tmp_path):
    p = tmp_path / "MANIFEST.sha256"
    h = _sha(GOOD)
    p.write_text(f"{h}  data/{TICK}/optic_fixtures_odds.jsonl\n")
    assert read_sha256_manifest(p) == {
        f"data/{TICK}/optic_fixtures_odds.jsonl": h}
    p.write_text("not a manifest line\n")
    with pytest.raises(ValueError):
        read_sha256_manifest(p)


def test_tick_files_unknown_tick_raises():
    assert len(tick_files(_manifest(), TICK)) == 2
    with pytest.raises(KeyError):
        tick_files(_manifest(), "2026-01-01/00_00")


class _writer:
    """A fake downloader that writes canned bytes."""
    def __init__(self, data_by_rel):
        self.data = data_by_rel
        self.calls = []

    def __call__(self, rel, dest):
        self.calls.append(rel)
        dest.write_bytes(self.data[rel])


def test_cached_and_valid_downloads_nothing(tmp_path):
    (tmp_path / TICK).mkdir(parents=True)
    (tmp_path / TICK / "optic_fixtures_odds.jsonl").write_bytes(GOOD)
    (tmp_path / TICK / "kalshi_markets.jsonl").write_bytes(b"k\n")
    dl = _writer({})
    out = ensure_tick(TICK, root=tmp_path, manifest=_manifest(),
                      download=dl)
    assert out == tmp_path / TICK
    assert dl.calls == []


def test_missing_files_downloaded_then_verified(tmp_path):
    dl = _writer({f"data/{TICK}/optic_fixtures_odds.jsonl": GOOD,
                  f"data/{TICK}/kalshi_markets.jsonl": b"k\n"})
    ensure_tick(TICK, root=tmp_path, manifest=_manifest(), download=dl)
    assert len(dl.calls) == 2
    assert (tmp_path / TICK / "optic_fixtures_odds.jsonl").read_bytes() \
        == GOOD
    assert not list((tmp_path / TICK).glob("*.part"))


def test_corrupt_cached_file_aborts(tmp_path):
    (tmp_path / TICK).mkdir(parents=True)
    (tmp_path / TICK / "optic_fixtures_odds.jsonl").write_bytes(GOOD)
    (tmp_path / TICK / "kalshi_markets.jsonl").write_bytes(b"EDITED")
    with pytest.raises(CorpusIntegrityError, match="cached"):
        ensure_tick(TICK, root=tmp_path, manifest=_manifest(),
                    download=_writer({}))


def test_failed_download_cleans_up_part_file(tmp_path):
    def download(rel, dest):
        dest.write_bytes(b"partial")
        raise RuntimeError("network died")
    with pytest.raises(RuntimeError):
        ensure_tick(TICK, root=tmp_path, manifest=_manifest(),
                    download=download)
    assert not list((tmp_path / TICK).glob("*.part"))


def test_bad_download_aborts_and_leaves_no_file(tmp_path):
    dl = _writer({f"data/{TICK}/optic_fixtures_odds.jsonl": b"WRONG",
                  f"data/{TICK}/kalshi_markets.jsonl": b"k\n"})
    with pytest.raises(CorpusIntegrityError, match="downloaded"):
        ensure_tick(TICK, root=tmp_path, manifest=_manifest(),
                    download=dl)
    assert not list((tmp_path / TICK).glob("*")) or \
        not (tmp_path / TICK / "optic_fixtures_odds.jsonl").exists()
