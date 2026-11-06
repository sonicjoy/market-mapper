"""Project mapper benchmark output to the canonical comparison form.

Reads benchmark-format JSONL (mappers.run --json; one nested record
per merged bet) on stdin and emits sorted canonical JSONL on stdout:
one line per (9-field bet key x sportsbook stamp) — the grain of the
published market_mapping rows in BigQuery.

A record's stamps come from THREE sources, mirroring
BigQuery/load_mappings.flatten_rows (the publisher of that grain):

1. Constructed exchange blocks (STAMPS): kalshi / prophet_x /
   crypto_com / runshop / underdog fields built by the matchers, and
   the SX Bet block when Optic carries no SX id for the odd.  An
   Underdog satellite emits its Underdog stamp alone.
2. Optic source_ids passthrough (PASSTHROUGH): identifiers OpticOdds
   itself carries on the odd for Polymarket, Polymarket (USA), Novig,
   SX Bet, DraftKings.  These venues are not treated first-class in
   the repo (no fetcher, no matcher), but their rows ARE published —
   market_mapping doubles as an identifier-resolution table for RFQ
   tenants (e.g. the SX RFQ mapper resolves leg marketHash off it) —
   so they are ~a third of the table and must be compared.  The
   stamp is the source_ids payload verbatim.
3. Constructed Polymarket fallback: rec["polymarket"] tokens the
   matcher mapped but Optic never did.  Emitted only when no
   "Polymarket" passthrough exists for the record (the loader's
   double-emit gate), and normalized to the same {"selection_id"}
   stamp shape as the passthrough, so a change that merely flips
   which path produced the same token is not a false diff.

Load-time gates are mirrored too (missing > wrong, as in the loader):
no optic_odds -> no rows at all; key.line disagreeing with optic
points drops the constructed stamps but keeps the passthrough;
crypto is dropped when both sides carry Optic PM.NPO market_ids that
differ.  STAMPS + PASSTHROUGH + these gates ARE the comparison
contract; bump VERSION on any change to them (it keys the projection
cache — see run_engine.sh — so stale canonical files can never be
diffed against fresh ones).

Everything else in the record is excluded on purpose — the
human-facing "check" block, optic_odds value fields with their BQ
coercion quirks ("" / 0.0), and ordering.  The optic parent pointer
(fixture_id, optic market_id) rides along and IS compared:
re-routing the same bet key to a different Optic market or fixture
is a real mapping change even when the exchange stamp is unchanged.

Records yielding no stamps (Optic-only inventory nobody publishes)
are skipped — but counted on stderr, because a large swing in that
count is itself a signal.

This module must not import from mappers/ or BigQuery/ — it must
work unchanged against the output of ANY engine version (see README
design rules).  The loader-gate helpers below are deliberate
transcriptions of BigQuery/load_mappings.py, not imports.
"""
import json
import sys

# Bump on ANY change to the comparison contract (stamp sources, gate
# semantics, canonical line shape).  v1: constructed blocks only.
# v2: + optic source_ids passthrough, polymarket dedup, loader gates.
# v3: + kalshi_complement satellites emit their Kalshi stamp only.
# v4: + Betfair Exchange optic source_ids passthrough.
# v5: + constructed Underdog and SX Bet stamps; Underdog satellites.
# v6: + constructed STX stamps (market_id, selection_id, tie_pays_half); STX satellites.
VERSION = 6

# constructed sportsbook block name -> fields that constitute the
# stamp identity (polymarket is handled by the dedup rule, not here)
STAMPS = {
    "kalshi": ("market_ticker", "side"),
    "prophet_x": ("event_id", "line_id"),
    "crypto_com": ("security_id", "symbol"),
    "runshop": ("tx_odds_fixture_id", "market_id"),
    "underdog": ("market_id", "selection_id"),
    "stx": ("market_id", "selection_id", "tie_pays_half"),
}
SX_FIELDS = ("event_id", "market_id", "selection_id")

# optic_odds.source_ids key -> canonical sportsbook label.  Must
# track OPTIC_MAPPED_SPORTSBOOKS in mappers/exchanges/optic.py (a
# deliberate copy: additions there are contract changes here).
PASSTHROUGH = {
    "Polymarket": "polymarket",
    "Polymarket (USA)": "polymarket_usa",
    "Novig": "novig",
    "SX Bet": "sx_bet",
    "DraftKings": "draftkings",
    "Betfair Exchange": "betfair_exchange",
}


def norm_line(v):
    """Snap a line to 2dp; mirrors the engines' normalize_line so
    float drift can never masquerade as a mapping change."""
    return None if v is None else round(v, 2)


def line_agrees_with_optic(key, odd):
    """False when both key.line and optic points are set and disagree.
    Optic serializes missing points as 0.0; treat that as absent when
    the mapping key also has no line (moneyline / 3-way).
    Transcribed from load_mappings._line_agrees_with_optic."""
    key_line = key.get("line")
    points = odd.get("points")
    if key_line is None or points is None:
        return True
    if points == 0.0 and key_line != 0.0:
        return True
    return float(key_line) == float(points)


def crypto_agrees_with_optic(block, optic_src):
    """False when both the crypto block and optic's crypto.com
    source_ids carry a PM.NPO market_id and they differ.
    Transcribed from load_mappings._crypto_agrees_with_optic."""
    src = optic_src.get("crypto.com")
    if not isinstance(src, dict):
        return True
    optic_mid = src.get("market_id")
    our_mid = block.get("market_id")
    if not (isinstance(optic_mid, str) and "PM.NPO" in optic_mid):
        return True
    if not (isinstance(our_mid, str) and "PM.NPO" in our_mid):
        return True
    return optic_mid == our_mid


def constructed_stamps(rec, odd):
    """(sb, stamp) for the matcher-built blocks, before the line gate."""
    optic_src = odd.get("source_ids") or {}
    stamps = []
    for sb, fields in STAMPS.items():
        block = rec.get(sb)
        if not block:
            continue
        if sb == "crypto_com" and \
                not crypto_agrees_with_optic(block, optic_src):
            continue
        stamps.append((sb, {f: block.get(f) for f in fields}))
    pm = rec.get("polymarket")
    if pm and "Polymarket" not in optic_src:
        stamps.append(
            ("polymarket",
             {"selection_id": pm["clob_token_id"]}))
    pusa = rec.get("polymarket_usa")
    if pusa and "Polymarket (USA)" not in optic_src:
        stamps.append(
            ("polymarket_usa",
             {"market_id": pusa["market_id"]}))
    sx = rec.get("sxbet")
    if sx and "SX Bet" not in optic_src:
        # same label as the passthrough: one MERGE key either way
        stamps.append(("sx_bet", {f: sx.get(f) for f in SX_FIELDS}))
    return stamps


def record_stamps(rec, odd):
    """Every (sb, stamp) the loader publishes for one record."""
    line_ok = line_agrees_with_optic(rec["key"], odd)
    for sat, sb in (("underdog_satellite", "underdog"), ("stx_satellite", "stx")):
        if rec.get(sat):
            # loader: a second ticker / market for the parent's bet, alone
            blk = rec.get(sb)
            if not (blk and line_ok):
                return []
            return [(sb, {f: blk.get(f) for f in STAMPS[sb]})]
    stamps = constructed_stamps(rec, odd) if line_ok else []
    # A Kalshi complement is a satellite on the parent's MERGE key:
    # the loader emits its own Kalshi row only, so the parent already
    # owns the Optic passthrough books.
    if not rec.get("kalshi_complement"):
        optic_src = odd.get("source_ids") or {}
        for src_key, sb in PASSTHROUGH.items():
            src = optic_src.get(src_key)
            if src:
                stamps.append((sb, src))
    return stamps


def project(records):
    """Yield canonical lines (unsorted) for an iterable of benchmark
    records; use project_all for the sorted list + stats."""
    for rec in records:
        k = rec["key"]
        key = [k["league"], k["start_date"], k["home"], k["away"],
               k["market_type"], k["entity"], norm_line(k["line"]),
               k["side"], k["grouping_key"]]
        odd = rec.get("optic_odds")
        if odd is None:
            continue  # loader: without an Optic join, no rows at all
        parent = {"fixture_id": odd.get("fixture_id"),
                  "optic_market_id": odd.get("market_id")}
        for sb, stamp in record_stamps(rec, odd):
            yield json.dumps(
                {"k": key, "sb": sb, "stamp": stamp, "parent": parent},
                sort_keys=True)


def project_all(lines):
    """Parse benchmark JSONL lines -> (sorted canonical lines, stats)."""
    records = [json.loads(s) for s in lines if s.strip()]
    out = []
    stamped_records = 0
    for rec in records:
        n = len(out)
        out.extend(project([rec]))
        if len(out) > n:
            stamped_records += 1
    out.sort()
    stats = {"records": len(records),
             "rowless": len(records) - stamped_records,
             "rows": len(out)}
    return out, stats


def main():
    out, stats = project_all(sys.stdin)
    for line in out:
        print(line)
    print(f"projected {stats['rows']} stamped rows from "
          f"{stats['records']} records "
          f"({stats['rowless']} rowless skipped)", file=sys.stderr)


if __name__ == "__main__":
    main()
