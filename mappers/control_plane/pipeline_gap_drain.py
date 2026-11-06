"""Gap-propose drain: checker starts worker; worker runs waves of league cards.

A wave is one planner child (one inventory fetch, every league seated), then one
child process per league card, ``MAPPING_GAP_DRAIN_POOL`` at a time.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess  # nosec B404 — drain worker spawns fixed-argv children to drop RSS
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TextIO

from BigQuery.alerts import Severity, build_gap_propose_publisher
from mappers.control_plane.gap_ledger import GapLedgerQueryError
from mappers.control_plane.pipeline_gap_card import plan_wave, run_league_card
from mappers.control_plane.pipeline_gap_k8s import (
    create_worker_job,
    hand_off_to_deployed_image,
    worker_job_running,
)
from mappers.control_plane.pipeline_gap_propose import (
    _publish,
    build_pipeline_service,
    pipeline_gap_propose_enabled,
)

logger = logging.getLogger(__name__)

_STALL_LIMIT = 2
_DEFAULT_POOL = 4
_PLAN_PREFIX = "GAP_DRAIN_PLAN="
_RESULT_PREFIX = "GAP_DRAIN_RESULT="
_IDLE_INFO = (
    "Pipeline gap-fix: idle — no unchecked Optic-mappable RFQ gaps remain "
    "for this tip (mapping_gap_ledger cursor)."
)


def run_checker() -> int:
    """Exit 0 after ensuring a worker Job exists or is already running."""
    if not pipeline_gap_propose_enabled():
        logger.info("pipeline gap-drain checker disabled (MAPPING_PIPELINE_GAP_PROPOSE=0)")
        return 0
    running = worker_job_running()
    if running is None:
        logger.warning("pipeline gap-drain checker: job list failed; not starting another worker")
        return 0
    if running:
        logger.info("pipeline gap-drain checker: worker already running")
        return 0
    create_worker_job()
    logger.info("pipeline gap-drain checker: started worker job")
    return 0


def run_worker(*, use_subprocess: bool = True) -> int:
    """Waves of league cards until idle, repeated stall, or a harvest failure."""
    if not pipeline_gap_propose_enabled():
        return 0
    stalled = 0
    stats: dict[str, int] = {}
    while True:
        cards = _plan(use_subprocess=use_subprocess)
        if cards is None:
            _finish(stats, "warning", "Pipeline gap-fix: drain wave plan failed (inventory or ledger read).")
            return 1
        if not cards:
            _finish(stats, "info", _IDLE_INFO)
            return 0
        results = _run_wave(cards, use_subprocess=use_subprocess)
        for result in results:
            action = str(result.get("action") or "")
            stats[action] = stats.get(action, 0) + 1
        if any(result.get("progress") for result in results):
            stalled = 0
        else:
            stalled += 1
            if stalled >= _STALL_LIMIT:
                _finish(
                    stats,
                    "critical",
                    f"Pipeline gap-fix: worker stalled with no progress after {_STALL_LIMIT} waves.",
                )
                return 1
        if any(result.get("action") == "harvest_failed" for result in results):
            _finish(stats)
            return 1
        deployed = hand_off_to_deployed_image()
        if deployed:
            _finish(stats, "info", f"Pipeline gap-fix drain worker handing off to {deployed}.")
            return 0


def _finish(stats: dict[str, int], severity: Severity | None = None, text: str = "") -> None:
    publisher = build_gap_propose_publisher()
    try:
        if severity is not None and text:
            _publish(publisher, severity, text)
        if stats:
            parts = ", ".join(f"{key}={count}" for key, count in sorted(stats.items()))
            _publish(publisher, "info", f"Pipeline gap-fix drain worker finished: {parts}")
    finally:
        publisher.close()


def _subprocess_mode(use_subprocess: bool) -> bool:
    return use_subprocess and os.environ.get("MAPPING_GAP_DRAIN_INPROCESS", "") != "1"


def _env_int(name: str, default: int, floor: int) -> int:
    try:
        return max(floor, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def _plan(*, use_subprocess: bool) -> list[dict[str, Any]] | None:
    """Every seated league card for this wave; ``None`` when planning failed."""
    if not _subprocess_mode(use_subprocess):
        service, _environment = build_pipeline_service()
        try:
            return plan_wave(service)
        except GapLedgerQueryError:
            logger.exception("pipeline gap-drain plan: ledger read failed")
            return None
    out = _child(["--role", "plan"], None, _PLAN_PREFIX)
    if out is None or "cards" not in out:
        return None
    return list(out["cards"])


def _run_wave(cards: list[dict[str, Any]], *, use_subprocess: bool) -> list[dict[str, Any]]:
    """Every league card of the wave; children run ``MAPPING_GAP_DRAIN_POOL`` at a time."""
    pool = _env_int("MAPPING_GAP_DRAIN_POOL", _DEFAULT_POOL, 1)
    logger.info("pipeline gap-drain wave leagues=%d pool=%d", len(cards), pool)
    if not _subprocess_mode(use_subprocess):
        return [_run_card_inprocess(card) for card in cards]
    with ThreadPoolExecutor(max_workers=pool) as executor:
        return list(executor.map(_run_card_child, cards))


def _run_card_child(card: dict[str, Any]) -> dict[str, Any]:
    league = card.get("league")
    result = _child(["--role", "one-card"], json.dumps(card), _RESULT_PREFIX)
    if result is None:
        return {"action": "subprocess_error", "progress": False, "league": league}
    return {"league": league, **result}


def _run_card_inprocess(card: dict[str, Any]) -> dict[str, Any]:
    service, environment = build_pipeline_service()
    publisher = build_gap_propose_publisher()
    try:
        return run_league_card(service, card, publisher=publisher, environment=environment)
    finally:
        publisher.close()


def _child(args: list[str], stdin: str | None, prefix: str) -> dict[str, Any] | None:
    """Run one drain child; parse its last ``prefix`` line. Logs go straight to the pod log."""
    timeout = _env_int("MAPPING_GAP_DRAIN_CARD_TIMEOUT_SEC", 7200, 60)
    try:
        proc = subprocess.run(  # nosec B603 — argv is sys.executable + module, no shell
            [sys.executable, "-m", "mappers.control_plane.pipeline_gap_drain", *args],
            check=False,
            input=stdin,
            stdout=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.error("pipeline gap-drain child %s timed out after %ss", args[-1], timeout)
        return {"action": "subprocess_error", "progress": True, "error": "timeout"}
    for line in reversed((proc.stdout or "").splitlines()):
        if line.startswith(prefix):
            return json.loads(line.removeprefix(prefix))
    logger.error("pipeline gap-drain child %s exit=%s without result", args[-1], proc.returncode)
    return None


def run_plan_cli() -> int:
    """Planner child: one inventory fetch, every league card seated, printed as JSON."""
    if not pipeline_gap_propose_enabled():
        print(_PLAN_PREFIX + json.dumps({"cards": []}), flush=True)
        return 0
    service, _environment = build_pipeline_service()
    try:
        cards = plan_wave(service)
    except GapLedgerQueryError as exc:
        logger.exception("pipeline gap-drain plan: ledger read failed")
        print(_PLAN_PREFIX + json.dumps({"error": str(exc)[:300]}), flush=True)
        return 1
    print(_PLAN_PREFIX + json.dumps({"cards": cards}), flush=True)
    return 0


def run_one_card_cli(stdin: TextIO | None = None) -> int:
    """League card child: read the seated card from stdin, harvest, maybe propose."""
    if not pipeline_gap_propose_enabled():
        return 0
    card = json.load(stdin or sys.stdin)
    service, environment = build_pipeline_service()
    publisher = build_gap_propose_publisher()
    try:
        result = run_league_card(
            service,
            card,
            publisher=publisher,
            environment=environment,
        )
    finally:
        publisher.close()
    action = str(result.get("action") or "")
    logger.info("pipeline gap-drain one-card league=%s action=%s", card.get("league"), action)
    safe = {
        key: result.get(key)
        for key in ("ok", "action", "progress", "count", "error", "harvested", "league")
    }
    print(_RESULT_PREFIX + json.dumps(safe), flush=True)
    if action == "harvest_failed":
        return 1
    if not result.get("progress"):
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="pipeline_gap_drain")
    parser.add_argument(
        "--role",
        choices=("checker", "worker", "plan", "one-card"),
        default="worker",
    )
    args = parser.parse_args(argv)
    if args.role == "checker":
        return run_checker()
    if args.role == "plan":
        return run_plan_cli()
    if args.role == "one-card":
        return run_one_card_cli()
    return run_worker()


if __name__ == "__main__":
    sys.exit(main())
