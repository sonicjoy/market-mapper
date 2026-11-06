"""Materialize corpus ticks from the bucket, verifying on pull.

The checked-in ``MANIFEST.sha256`` is the authoritative definition of
the corpus bytes; the bucket is just storage for them and any local
cache is trusted only insofar as it matches those hashes.  Every file
``ensure_tick`` returns has been hashed and checked THIS call —
whether it was already cached or freshly downloaded — so a truncated
download, a mutated bucket object, or a hand-edited local file aborts
with a corpus-integrity error instead of silently changing regression
results.  (This replaces the original presence-=-validity idea; see
regression/HISTORY.md, decision 2026-08-07.)

Cache root resolution (decided 2026-08-10): ``MM_CORPUS_CACHE`` env
var, else ``~/.cache/mm-corpus``.  A fixed default, deliberately NO
auto-detection of the repo's ``data/`` — point the env var there if
your ``data/`` is a full mirror.  The root is printed on every run so
a forgotten var is visible before any download starts.

Usage:
    python -m regression.corpus pull --smoke        # manifest tier
    python -m regression.corpus pull --full         # entire corpus
    python -m regression.corpus pull 2026-07-29/16_19 [TICK...]

Downloads go to ``<file>.part`` and are renamed only after their hash
verifies, so an interrupted pull can never leave a file a later run
would trust.  This module must not import from mappers/ or BigQuery/
(see README design rules).
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from fetch.gcloud_util import gcloud_cmd
from regression.build_manifest import BUCKET

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = Path.home() / ".cache" / "mm-corpus"
ENV_VAR = "MM_CORPUS_CACHE"


class CorpusIntegrityError(Exception):
    """A cached or downloaded file does not match MANIFEST.sha256."""


def cache_root(env=os.environ):
    """(root path, human-readable provenance) per the decided
    resolution: env var else fixed default, no auto-detection."""
    value = env.get(ENV_VAR)
    if value:
        return Path(value).expanduser(), f"${ENV_VAR}"
    return DEFAULT_ROOT, f"default (${ENV_VAR} unset)"


def read_sha256_manifest(path=HERE / "MANIFEST.sha256"):
    """{corpus-relative path: sha256 hex} from sha256sum format."""
    out = {}
    for n, line in enumerate(path.read_text().splitlines(), 1):
        m = re.fullmatch(r"([0-9a-f]{64})  (\S.*)", line)
        if not m:
            raise ValueError(f"{path}:{n}: not sha256sum format")
        out[m.group(2)] = m.group(1)
    return out


def tick_files(manifest, tick_id):
    """The manifest entries for one tick: {corpus-relative path:
    sha256}.  Raises on unknown tick — the manifest defines the
    corpus, so an unlisted tick does not exist."""
    prefix = f"data/{tick_id}/"
    files = {p: h for p, h in manifest.items() if p.startswith(prefix)}
    if not files:
        raise KeyError(f"tick {tick_id!r} not in MANIFEST.sha256")
    return files


def tier_ticks(tier, manifest_toml=HERE / "manifest.toml"):
    """Tick ids for a tier: 'smoke' or 'full' (full = every tick)."""
    doc = tomllib.loads(manifest_toml.read_text())
    return [t["id"] for t in doc["tick"]
            if tier == "full" or t["tier"] == tier]


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def _gcloud_download(rel_path, dest):
    subprocess.run(
        gcloud_cmd("storage", "cp", "--no-user-output-enabled",
                   f"{BUCKET}/{rel_path}", str(dest)),
        check=True)


def ensure_tick(tick_id, root=None, manifest=None,
                download=_gcloud_download, log=sys.stderr):
    """Make one tick available and verified under the cache root;
    return its directory.  Every file is hashed against
    MANIFEST.sha256 this call, cached or not.  ``download`` is
    injectable for tests: (corpus-relative path, dest Path) -> None.
    """
    if root is None:
        root, why = cache_root()
        print(f"corpus cache: {root} [{why}]", file=log)
    if manifest is None:
        manifest = read_sha256_manifest()
    fetched = 0
    for rel, want in sorted(tick_files(manifest, tick_id).items()):
        local = root / Path(rel).relative_to("data")
        if not local.is_file():
            local.parent.mkdir(parents=True, exist_ok=True)
            part = local.with_name(local.name + ".part")
            try:
                download(rel, part)
            except BaseException:
                part.unlink(missing_ok=True)
                raise
            if sha256_of(part) != want:
                part.unlink()
                raise CorpusIntegrityError(
                    f"downloaded {rel} does not match MANIFEST.sha256 "
                    f"— bucket drift?")
            part.rename(local)
            fetched += 1
        elif sha256_of(local) != want:
            raise CorpusIntegrityError(
                f"cached {local} does not match MANIFEST.sha256 — "
                f"remove it (or fix the cache) and re-pull")
    print(f"  {tick_id}: verified"
          + (f" ({fetched} files downloaded)" if fetched else " (cached)"),
          file=log)
    return root / tick_id


def main():
    ap = argparse.ArgumentParser(
        description="Materialize corpus ticks, verifying on pull.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pull = sub.add_parser("pull", help="ensure ticks are cached+verified")
    pull.add_argument("ticks", nargs="*", metavar="TICK",
                      help="tick ids like 2026-07-29/16_19")
    tier = pull.add_mutually_exclusive_group()
    tier.add_argument("--smoke", action="store_true",
                      help="all smoke-tier ticks from manifest.toml")
    tier.add_argument("--full", action="store_true",
                      help="the entire corpus")
    args = ap.parse_args()

    ticks = list(args.ticks)
    if args.smoke:
        ticks += tier_ticks("smoke")
    if args.full:
        ticks += tier_ticks("full")
    if not ticks:
        ap.error("nothing to pull: give TICK ids or --smoke/--full")

    root, why = cache_root()
    print(f"corpus cache: {root} [{why}]", file=sys.stderr)
    manifest = read_sha256_manifest()
    for tick_id in dict.fromkeys(ticks):  # dedupe, keep order
        try:
            ensure_tick(tick_id, root=root, manifest=manifest)
        except CorpusIntegrityError as e:
            print(f"CORPUS INTEGRITY VIOLATION: {e}", file=sys.stderr)
            return 1
        except subprocess.CalledProcessError:
            # gcloud already printed its own error (auth expiry is
            # the common one: `gcloud auth login` fixes it)
            print(f"download failed for {tick_id}; nothing partial "
                  f"was kept", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
