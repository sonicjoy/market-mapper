"""Judge the same mapping rows N times and report how often each one flags.

Some false-positive classes in the AI validator are INTERMITTENT — the spread
polarity one flagged 9 rows on one run, 0 on the next three, and 10 on the one
after, with no rule change in between (dynamic thinking; `temperature=0` does not
make this deterministic). A single clean run therefore proves nothing about a
prompt change, and a single dirty run does not prove a mapping is wrong.

This replays the same rows repeatedly, keeping production's row order, batch size
and concurrency — batch composition matters, so an oversized one-off call does not
reproduce the behaviour — and reports per-rep counts plus a per-row flag rate.

Use it to:
- decide whether a flag is real or noise (a row flagging 1/5 is noise, 5/5 is not);
- check a prompt change (compare flag rates over several reps, not one run).

Nothing is written to BigQuery. It DOES spend tokens: reps x batches calls.

Usage:
    GCP_PROJECT=marketmaking-test .venv/bin/python -m scripts.ai_validation_replay \
        --sportsbook Kalshi --reps 3
    ... --market-type point_spread --reps 5    # narrow to one suspect class
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from BigQuery import ai_validation as av
from BigQuery.polymarket_bq_util import bq_client


def _row_key(row: dict) -> str:
    """Short human label for a row in the per-row report."""
    return (
        f"{row.get('league')}/{row.get('market_type')} {row.get('side')}"
        f" line={row.get('line')} {str(av.exchange_ref(row))[:38]}"
    )


def judge_batch(client, model: str, chunk: list[dict]) -> list[tuple[dict, bool]]:
    """Judge one batch; return (row, flagged) pairs. A failed call yields nothing."""
    try:
        verdicts = av.validate_chunk(client, model, chunk)
    except Exception as exc:  # noqa: BLE001 — report and carry on; this is a probe
        print(f"  batch failed: {exc}")
        return []
    by_i = {v.i: v for v in verdicts}
    out: list[tuple[dict, bool]] = []
    for i, row in enumerate(chunk):
        verdict = by_i.get(i)
        if verdict is not None:
            flagged = not av.derive_mapping_ok(verdict, is_prop=bool(row.get("entity")))
            out.append((row, flagged))
    return out


def main() -> None:
    """Replay the selected rows `--reps` times and print the flag rates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sportsbook", default="Kalshi", choices=list(av.SPORTSBOOKS))
    parser.add_argument("--market-type", help="restrict to one canonical market_type")
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--max-rows", type=int, help="cap the replay set")
    parser.add_argument("--model", default=av.DEFAULT_MODEL)
    args = parser.parse_args()

    client = bq_client()
    now = datetime.now(UTC)
    rows = av.fetch_rows(
        client,
        # revalidate: the point is to re-judge rows that already have verdicts
        av.build_sql(client.project, revalidate=True, include_corroborated=False),
        date_from=now.replace(hour=0, minute=0, second=0, microsecond=0),
        date_to=(now + timedelta(days=14)).replace(hour=23, minute=59, second=59, microsecond=0),
        sportsbooks=[args.sportsbook],
    )
    rows = [r for r in rows if av.has_exchange_text(r)]
    if args.market_type:
        rows = [r for r in rows if r.get("market_type") == args.market_type]
    if args.max_rows:
        rows = rows[: args.max_rows]
    if not rows:
        print("no rows matched")
        return

    chunks = av.partition_chunks(rows, av.BATCH_ROWS)
    print(f"{len(rows)} rows -> {len(chunks)} batches of <= {av.BATCH_ROWS}, {args.reps} reps")

    from google import genai

    model_client = genai.Client(api_key=av._gemini_api_key(client.project))
    per_rep: list[int] = []
    flags_by_row: Counter[str] = Counter()
    for rep in range(args.reps):
        flagged = 0
        with ThreadPoolExecutor(max_workers=av.CONCURRENCY) as pool:
            for pairs in pool.map(lambda c: judge_batch(model_client, args.model, c), chunks):
                for row, is_flagged in pairs:
                    if is_flagged:
                        flagged += 1
                        flags_by_row[_row_key(row)] += 1
        per_rep.append(flagged)
        print(f"  rep {rep + 1}: {flagged} flagged")

    print(f"\nper-rep flags: {per_rep}  (of {len(rows)} rows each)")
    if flags_by_row:
        print(f"rows that flagged at least once ({len(flags_by_row)}):")
        for key, count in flags_by_row.most_common():
            verdict = "consistent" if count == args.reps else "INTERMITTENT"
            print(f"  {count}/{args.reps} {verdict:12} {key}")
    else:
        print("no row flagged in any rep")


if __name__ == "__main__":
    main()
