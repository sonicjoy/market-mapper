"""Read config TOML entities independently of the seed extractor.

Step 5's third reader: parse ``config/*/team_aliases.toml`` and
``player_aliases.toml`` at a git SHA into canonical config lines
(config_project.py, current VERSION) WITHOUT importing mappers/ —
stdlib tomllib plus this module's own comment handling.  Purpose
(decision 1, HISTORY.md): the entity slice of side A (config_extract)
is Joe's extractor reading the TOMLs, and side B is BQ rows loaded
FROM that extractor — comparing them can never catch an extractor
bug.  This reader breaks the tautology: it is a second, independent
transcription of the same files, so a reader↔extractor delta is an
extractor bug (or, symmetrically, a bug here — either way a loud
finding).  It also counts comment instances per league, the raw
number behind the differ's EXPECTED-LOSS bucket (decision 3).

Reads git OBJECTS (``git ls-tree`` + ``git show``), not any working
directory — stronger than the 2026-08-14 worktree decision it
implements: untracked or locally-edited TOMLs cannot exist in a
tree object, and no worktree needs creating.  Works at any SHA
(TOMLs long predate mappers/seed).

Semantics deliberately mirror ``mappers/seed/entities.py`` (the
shapes it must reproduce without importing; changes there are
contract changes here): the alias-key table (kalshi/crypto_id/
crypto_name/px + optic_id), string-or-list values coerced through
str(), entity_type from filename then league (player file ->
player, ufc -> fighter, else team), enabled always True, and
canonical_name = the section's ``name`` value if present else the
display comment (header comment wins, else the first inline comment
on a known value line within the section).  ONE deliberate
divergence: section keys are matched to display comments AFTER
TOML-unquoting, because tomllib unquotes dict keys while the
extractor's header regex captures the quotes — so the extractor
loses every quoted section's display name (["DK.C"]  # Dplus KIA
Challengers -> canonical_name null, verified in the e1a7136 extract
and in prod seeds).  This reader reports TOML truth; the resulting
deltas are the finding, not noise.  (Escape sequences inside quoted
keys are not processed — none exist in config/ — and ``#`` inside
quoted values is correctly ignored by a small string-aware scan.)

Loud-not-silent: a section key this reader does not recognize is
printed as a warning and counted in the report — the extractor
silently drops unknown keys, which is exactly the identity-loss
hazard its own comment block warns about.  alias_id is NOT
reproduced (a content hash needing mappers/ code); it is an
annotation, never compared.

Outputs, cached under the projection-cache convention with the
contract VERSION in the filename (``--refresh`` re-reads):

- ``<cache>/config/<sha>.toml.v<N>.jsonl``       canonical lines
- ``<cache>/config/<sha>.toml_report.v<N>.json`` per-league comment
  accounting {files, comments, migrated, lost} + unknown keys —
  ``migrated`` counts sections whose canonical_name came from a
  comment (the extractor's only comment harvest); every other
  comment instance is ``lost``, the EXPECTED-LOSS number.

Usage:
    python -m regression.config_toml e1a7136
    python -m regression.config_toml main --refresh

Prints the lines path on stdout; counts go to stderr.  This module
must not import from mappers/ or BigQuery/ (README design rules).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from regression.config_project import VERSION, canon_all

_REPO = Path(__file__).resolve().parent.parent

# TOML key -> (sportsbook, alias_kind); a deliberate copy of
# seed/entities.py LIST_ALIAS_KEYS.  optic_id is handled apart
# (string, not list); name feeds canonical_name only.
_LIST_ALIAS_KEYS = {
    "kalshi": ("kalshi", "code"),
    "crypto_id": ("crypto.com", "external_id"),
    "crypto_name": ("crypto.com", "name"),
    "px": ("px", "code"),
}
_META_KEYS = frozenset({"optic_id", "name"})

# [CODE]  # Display Name — copies of the seed/entities.py shapes.
_SECTION_HEADER = re.compile(
    r"^\[(?P<key>[^\]]+)\][^\S\n]*(?:#[^\S\n]*(?P<comment>.+?))?\s*$",
    re.MULTILINE,
)
_INLINE_VALUE_COMMENT = re.compile(
    r"^\s*(?:crypto_id|crypto_name|kalshi|px|optic_id)\s*=.*?#\s*(?P<comment>.+?)\s*$",
    re.MULTILINE,
)

_ALIAS_FILES = ("team_aliases.toml", "player_aliases.toml")


class TomlReadError(Exception):
    """The tree cannot be read or a TOML violates reader assumptions."""


def _git(*args):
    r = subprocess.run(["git", "-C", str(_REPO), *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise TomlReadError(
            f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def _unquote(key):
    """A section key as tomllib would report it.

    The divergence from the extractor's regex handling: strip one
    layer of basic/literal quotes so quoted sections match their
    parsed dict key.  Escapes are not processed (none in config/)."""
    if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
        return key[1:-1]
    return key


def _comment_pos(line):
    """Index of the first ``#`` outside a quoted string, else -1.

    Understands basic ("...", with backslash escapes) and literal
    ('...') strings; triple-quoted strings are not handled (none in
    config/ alias files)."""
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if quote == '"' and c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "#":
            return i
        i += 1
    return -1


def _entity_type(league, filename):
    if "player" in filename:
        return "player"
    return "fighter" if league == "ufc" else "team"


def display_names(text):
    """Section key (tomllib form) -> display comment, if any.

    Header comment wins; else the first inline comment on a known
    value line within the section body."""
    names = {}
    headers = list(_SECTION_HEADER.finditer(text))
    for i, m in enumerate(headers):
        key = _unquote(m.group("key"))
        chosen = (m.group("comment") or "").strip() or None
        if not chosen:
            end = headers[i + 1].start() if i + 1 < len(headers) \
                else len(text)
            for im in _INLINE_VALUE_COMMENT.finditer(
                    text[m.end():end]):
                inline = im.group("comment").strip()
                if inline:
                    chosen = inline
                    break
        if chosen:
            names[key] = chosen
    return names


def _count_comments(text):
    """Total comment instances, string-aware (standalone + trailing)."""
    n = 0
    for line in text.splitlines():
        if _comment_pos(line) >= 0:
            n += 1
    return n


def _section_records(league, entity_type, canon, section, display,
                     where, warn):
    """Records for ONE entity section -> (records, migrated, unknown).

    migrated is 1 when the canonical name comes from a same-line
    comment (no explicit name key); unknown lists the section keys
    the seed extractor would silently drop."""
    records = []
    migrated = 0
    unknown = []
    name = section.get("name")
    name = name.strip() if isinstance(name, str) and name.strip() \
        else None
    if name is None and canon in display:
        migrated = 1
    records.append(("entity", {
        "league": league, "entity_type": entity_type,
        "canonical_key": canon,
        "canonical_name": name or display.get(canon),
        "enabled": True, "source": where,
    }))
    optic_id = section.get("optic_id")
    if isinstance(optic_id, str) and optic_id:
        records.append(("alias", {
            "league": league, "entity_type": entity_type,
            "canonical_key": canon, "sportsbook": "optic",
            "alias_kind": "external_id", "alias_value": optic_id,
            "enabled": True, "source": where,
        }))
    for key, (sportsbook, alias_kind) in _LIST_ALIAS_KEYS.items():
        values = section.get(key)
        if isinstance(values, str):
            values = [values]
        for value in values or []:
            records.append(("alias", {
                "league": league, "entity_type": entity_type,
                "canonical_key": canon, "sportsbook": sportsbook,
                "alias_kind": alias_kind,
                "alias_value": str(value),
                "enabled": True, "source": where,
            }))
    for key in sorted(set(section) - set(_LIST_ALIAS_KEYS)
                      - _META_KEYS):
        unknown.append(f"{canon}.{key}")
        warn(f"WARNING: {where}: [{canon}] has unrecognized key "
             f"{key!r} — no alias emitted (the seed extractor "
             f"silently drops it: identity-loss hazard)")
    return records, migrated, unknown


def read_file(league, filename, text, warn=None):
    """One TOML file -> ((kind, dict) records, file report).

    The report counts every comment instance and how many migrate
    (become a canonical_name); unknown section keys are warned about
    and listed — the extractor drops them silently."""
    warn = warn or (lambda msg: print(msg, file=sys.stderr))
    where = f"config/{league}/{filename}"
    raw = tomllib.loads(text)
    display = display_names(text)
    entity_type = _entity_type(league, filename)
    records = []
    migrated = 0
    unknown = []
    for canon, section in raw.items():
        if not isinstance(section, dict):
            warn(f"WARNING: {where}: top-level key {canon!r} is not "
                 f"a section — skipped (the extractor skips it too)")
            continue
        recs, mig, unk = _section_records(
            league, entity_type, str(canon), section, display,
            where, warn)
        records += recs
        migrated += mig
        unknown += unk
    comments = _count_comments(text)
    report = {"comments": comments, "migrated": migrated,
              "lost": comments - migrated, "unknown_keys": unknown}
    return records, report


def alias_toml_paths(ref):
    """(league, filename, blob path) for every alias TOML at ref."""
    out = []
    for path in _git("ls-tree", "-r", "--name-only", ref,
                     "config/").splitlines():
        p = Path(path)
        if p.name in _ALIAS_FILES and len(p.parts) == 3:
            out.append((p.parts[1], p.name, path))
    return out


def read_tree(ref):
    """SHA -> (sorted canonical lines, stats, per-league report).

    Every alias TOML in the tree is read — including leagues the
    extractor's LEAGUES registry does not know, which the differ
    surfaces as reader-only lines (a TOML nobody wired up is a
    finding, not noise to pre-filter here)."""
    records = []
    report = {}
    for league, filename, path in alias_toml_paths(ref):
        recs, file_report = read_file(
            league, filename, _git("show", f"{ref}:{path}"))
        records.extend(recs)
        lr = report.setdefault(league, {"files": 0, "comments": 0,
                                        "migrated": 0, "lost": 0,
                                        "unknown_keys": []})
        lr["files"] += 1
        for k in ("comments", "migrated", "lost"):
            lr[k] += file_report[k]
        lr["unknown_keys"].extend(file_report["unknown_keys"])
    lines, stats = canon_all(records)
    return lines, stats, report


def toml_lines_path(sha):
    cache = Path(os.environ.get("MM_REGRESSION_CACHE",
                                Path.home() / ".cache" / "mm-regression"))
    return cache / "config" / f"{sha}.toml.v{VERSION}.jsonl"


def toml_report_path(sha):
    return toml_lines_path(sha).with_name(
        f"{sha}.toml_report.v{VERSION}.json")


def pull(ref, refresh=False):
    """Read into the cache (or reuse); returns the lines path.

    .part-then-rename as everywhere: an interrupted read never
    leaves a file a later run would trust."""
    sha = _git("rev-parse", "--short", ref).strip()
    dest = toml_lines_path(sha)
    if dest.is_file() and toml_report_path(sha).is_file() \
            and not refresh:
        print(f"cached: {dest.name}", file=sys.stderr)
        return dest
    lines, stats, report = read_tree(sha)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for path, payload in (
            (dest, "".join(line + "\n" for line in lines)),
            (toml_report_path(sha),
             json.dumps(report, indent=2, sort_keys=True) + "\n")):
        part = path.with_suffix(path.suffix + ".part")
        part.write_text(payload)
        part.rename(path)
    total = {k: sum(lr[k] for lr in report.values())
             for k in ("files", "comments", "migrated", "lost")}
    print(f"{ref} (= {sha}): {len(lines)} lines — "
          + ", ".join(f"{k} {n}" for k, n in stats.items()
                      if k in ("entity", "alias"))
          + f"; {total['files']} TOMLs, {total['comments']} comments "
          f"({total['migrated']} migrate, {total['lost']} lost)",
          file=sys.stderr)
    return dest


def main():
    ap = argparse.ArgumentParser(
        description="Read config alias TOMLs at a SHA to canonical "
                    "config lines, independently of the extractor.")
    ap.add_argument("refs", nargs="+", metavar="SHA")
    ap.add_argument("--refresh", action="store_true",
                    help="re-read even if cached files exist")
    args = ap.parse_args()
    for ref in args.refs:
        try:
            print(pull(ref, refresh=args.refresh))
        except TomlReadError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
