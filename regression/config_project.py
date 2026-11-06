"""Project mapping-rule CONFIG to the canonical comparison form.

This is the contract for roadmap step 5 (data equivalence): does BQ
rule snapshot S say exactly what the repo config at SHA X says?  It
is the config-side sibling of project.py, which does the same job
for engine OUTPUT — same three-layer model (README), different
subject matter, separately versioned.

Readers live elsewhere and may differ per source (the seed
extractor's SnapshotIR JSON, materialized BQ snapshot rows, the
independent TOML reader); each reduces its source to plain dicts and
feeds them here.  This module is the WRITER half: one canonical line
per record, so two sources agree iff their line sets agree.  It must
not import from mappers/ or BigQuery/ (README design rules).

Record kinds and their grain (one line each):

- market_rule  k = [league, sportsbook, source_key_type, source_key]
- entity       k = [league, entity_type, canonical_key]
- alias        k = [league, entity_type, canonical_key,
                    sportsbook, alias_kind, alias_value]
- canonical_market  k = [canonical_market_type]

Natural keys deliberately mirror mappers/control_plane/cow_diff.py
(entity_key / market_rule_key) — the redesign's own identity notion —
so a delta here is a delta there (a deliberate copy: changes there
are contract changes here).  alias_value is IN the alias key:
entity tables are exception lists on both sides, so presence itself
is the fact being compared; a surplus alias is as much a delta as a
missing one, and the differ must therefore diff BOTH directions.
mapping_leagues (exchange settings JSON) is deferred by decision
2026-08-13 — see HISTORY.md step 5.

Line shape: {"t": kind, "k": [...], "v": {...}, "a": {...}},
sort_keys.  Equality is on (t, k, v) ONLY — strip_annotations()
gives the compared form; "a" rides along so delta reports are
self-explaining (waiver raw material), and holds fields that are
real but not transcription content: content-hash ids (rule_id /
alias_id — derived, so comparing them double-counts v), notes,
confidence (assigned by the extractor, not present in TOML;
comparing it on a seed audit is tautological — and see the VIB4
confidence-inflation finding in HISTORY.md: its truthfulness is Joe's
fix, tracked as redesign ask 4, not a set-membership question),
evidence and
workflow refs.  Comment-loss accounting is the independent TOML
reader's job, reported by the differ as its own bucket — it never
affects line equality.

Normalization: an absent optional field equals an explicit null
(readers may omit; canon fills None).  Booleans and ints are
coerced from strings ("true", "100") because the bq CLI's JSON
stringifies scalars.  Strings are NOT trimmed: a leading space in
source_key is real matching content (px suffix rules like
" Assists").  v carries every behavior-bearing column of the BQ
schema even where the seed IR lacks the field (period,
source_selection_key, effective dates, target_optic_odd_id) — the
IR side canonicalizes to None, so a console-born rule that sets one
shows up as a changed value, not silence.

Bump VERSION on ANY change to kinds, keys, v field sets, or
normalization; it keys cached canonical files (never diff stale
against fresh) and baselines.toml-style pins if step 5 grows them.
"""
import json

# v1: market_rule + entity + alias + canonical_market; leagues deferred.
VERSION = 1

# kind -> (key fields, compared value fields).  Annotation fields are
# whatever else the reader supplies; they are never compared.
_KINDS = {
    "market_rule": (
        ("league", "sportsbook", "source_key_type", "source_key"),
        ("rule_kind", "action", "canonical_market_type",
         "match_operator", "market_family", "period", "priority",
         "enabled", "rule_group_id", "source_selection_key",
         "target_optic_odd_id", "effective_from_date",
         "effective_to_date"),
    ),
    "entity": (
        ("league", "entity_type", "canonical_key"),
        ("canonical_name", "enabled"),
    ),
    "alias": (
        ("league", "entity_type", "canonical_key",
         "sportsbook", "alias_kind", "alias_value"),
        ("enabled", "normalization_profile",
         "disambiguation_id", "disambiguation_name", "priority"),
    ),
    "canonical_market": (
        ("canonical_market_type",),
        ("scope", "shape", "enabled"),
    ),
}

_BOOL_STRINGS = {"true": True, "false": False}


def _norm(field, value):
    """Coerce a scalar to its canonical type; None stays None."""
    if value is None:
        return None
    if field in ("enabled",):
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in _BOOL_STRINGS:
            return _BOOL_STRINGS[s]
        raise ValueError(f"unbooleanable {field}={value!r}")
    if field in ("priority",):
        return int(value)
    return value


def canon_record(kind, rec):
    """One (kind, dict) record -> canonical line (str).

    rec must contain every key field (identity is never defaulted);
    missing value fields become None; all other fields land in "a".
    """
    if kind not in _KINDS:
        raise ValueError(f"unknown record kind: {kind}")
    key_fields, val_fields = _KINDS[kind]
    missing = [f for f in key_fields if f not in rec]
    if missing:
        raise ValueError(f"{kind} record missing key fields {missing}")
    k = [_norm(f, rec[f]) for f in key_fields]
    v = {f: _norm(f, rec.get(f)) for f in val_fields}
    a = {f: rec[f] for f in sorted(rec)
         if f not in key_fields and f not in val_fields}
    return json.dumps({"t": kind, "k": k, "v": v, "a": a},
                      sort_keys=True)


def strip_annotations(line):
    """Canonical line -> compared form (the (t, k, v) projection).

    Set-diff strips both sides with this; the full line (with "a")
    is what delta reports print."""
    d = json.loads(line)
    return json.dumps({"t": d["t"], "k": d["k"], "v": d["v"]},
                      sort_keys=True)


def canon_all(records):
    """Iterable of (kind, dict) -> (sorted canonical lines, stats).

    Sorted output is the determinism guarantee: two runs over the
    same records yield byte-identical files.  Duplicate compared
    forms are an input error (two records claiming one identity) —
    the redesign's activation validation enforces the same."""
    out = []
    stats = {kind: 0 for kind in _KINDS}
    for kind, rec in records:
        out.append(canon_record(kind, rec))
        stats[kind] += 1
    out.sort()
    seen = set()
    for line in out:
        d = json.loads(line)
        ident = json.dumps({"t": d["t"], "k": d["k"]}, sort_keys=True)
        if ident in seen:
            raise ValueError(f"duplicate identity: {ident}")
        seen.add(ident)
    return out, stats
