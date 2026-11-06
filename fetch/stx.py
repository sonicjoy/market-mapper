"""Load STX's market catalogue (and event rosters) for the STX pass.

Usage:
    python -m fetch.stx --from-file docs/stx/.../stx_open_markets_identity.json.gz --out-dir data/<date>/<hh_mm>
    STX_KEY_ID=... STX_PRIVATE_KEY_PATH=... python -m fetch.stx --live --players --out-dir data/<date>/<hh_mm>
    STX_ENV=demo python -m fetch.stx --league nfl nba --out-dir data/<date>/<hh_mm>        # the tick: key from GSM

Writes ``stx_markets.jsonl`` (one market per line, the identity and rule fields only) and, with ``--players``,
``stx_event_players.jsonl`` (one ``GET /api/v1/events/{id}/players`` body per line).

**The tick** (``python -m fetch --league ...`` runs this with ``--league`` and ``--out-dir`` only) fetches live when
``STX_ENV`` is set in the VM's ``.env`` (``demo`` on test, via ``infra/ensure_env.sh``; prod leaves it unset, so
nothing is fetched there until the owner enables it; ``STX_HTTPS_PROXY`` in the same ``.env`` routes only this fetch
through the Ontario Squid, see ``PROXY_ENV``) and reads the key from Secret Manager in ``GCP_PROJECT``
(``stx-api-key-id``, ``stx-private-key``; the VM's service account has the project-wide accessor role). Rosters are
fetched for events with player props. Exit 0 and no file when unset or when no requested league is an STX league.

``--from-file`` reads an exported markets list: a JSON list, ``{"markets": [...]}`` (the workspace capture), or
JSONL, optionally gzipped. ``--live`` reads ``GET /api/v1/markets?status=open`` through the vendor SDK
(``stx-python``, ``AsyncSTX``; not in ``requirements.txt`` -- install it where the live fetch runs). Market reads are
signed (401 without a key, 2026-10-27), so the key id and the private-key FILE path come from the environment; neither
is ever printed or written. The key never leaves memory: the PEM text goes
straight to the SDK, and nothing secret is printed or written.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import importlib
import json
import os
import subprocess  # nosec B404 — gcloud secret read, the repo-wide pattern (fetch/underdog.py)
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple

from fetch.gcloud_util import gcloud_cmd

OUT_FILE = "stx_markets.jsonl"
PLAYERS_FILE = "stx_event_players.jsonl"
#: The fields the pass reads, plus provenance. Descriptions are long and not read.
KEEP = (
    "market_id",
    "event_id",
    "event_title",
    "event_start",
    "event_status",
    "event_type",
    "sport",
    "competition",
    "rules",
    "specifier",
    "stat_detail",
    "participants",
    "powered_by",
    "grouping_id",
    "max_price",
    "status",
)
KEY_ID_ENV = "STX_KEY_ID"
KEY_PATH_ENV = "STX_PRIVATE_KEY_PATH"
TICK_ENV = "STX_ENV"  # demo | prod; unset = the tick does not fetch STX
TICK_REGION_ENV = "STX_REGION"
#: Squid URL for the STX REST calls only (``http://<ip>:3128``). STX production accepts Ontario source IPs; the
#: mapper VM is not one, so prod routes through the Toronto proxy. Unset = direct (demo on test). Never
#: ``HTTPS_PROXY``: that would send every other book's fetch through Squid, which refuses all but ``.stxapp.ca:443``.
PROXY_ENV = "STX_HTTPS_PROXY"
GSM_KEY_ID = "stx-api-key-id"
GSM_PRIVATE_KEY = "stx-private-key"


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """The kept fields of one STX market record (absent fields stay None)."""
    return {k: raw.get(k) for k in KEEP}


def _read_text(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    return path.read_text(encoding="utf-8")


def load_markets_list(path: Path) -> list[dict[str, Any]]:
    """Every market record in an exported list: JSON list, ``{"markets": [...]}`` or JSONL, optionally gzipped."""
    text = _read_text(path)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        doc = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(doc, dict):
        doc = doc["markets"] if isinstance(doc.get("markets"), list) else [doc]
    return [r for r in doc if isinstance(r, dict) and r.get("market_id")]


def load_players(path: Path) -> dict[str, dict[str, Any]]:
    """``{event_id: roster body}`` from JSONL bodies or the workspace capture's ``{event_id: body}``."""
    text = _read_text(path)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        doc = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(doc, dict) and "teams" in doc:
        doc = [doc]  # one JSONL body
    if isinstance(doc, dict):
        return {str(k): v for k, v in doc.items() if isinstance(v, dict)}
    return {str(b["event_id"]): b for b in doc if isinstance(b, dict) and b.get("event_id")}


def write_jsonl(rows: Iterable[dict[str, Any]], path: Path) -> int:
    """Write ``rows`` one per line; returns the count."""
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":"), default=str) + "\n")
            n += 1
    return n


def _dump(obj: Any) -> dict[str, Any]:
    return obj.model_dump() if hasattr(obj, "model_dump") else dict(obj)


def _gsm(name: str, project: str) -> str:
    return subprocess.check_output(  # nosec B603 — fixed argv, no shell, code-derived args
        gcloud_cmd("secrets", "versions", "access", "latest", f"--secret={name}", f"--project={project}"),
        text=True,
    ).strip()


def _credentials(gsm_project: str | None) -> tuple[str, str]:
    """``(key id, private key PEM text or file path)``: the tick reads Secret Manager, ``--live`` the environment."""
    if gsm_project:
        return _gsm(GSM_KEY_ID, gsm_project), _gsm(GSM_PRIVATE_KEY, gsm_project)
    key_id, key_path = os.environ.get(KEY_ID_ENV), os.environ.get(KEY_PATH_ENV)
    if not key_id or not key_path:
        raise SystemExit(f"--live needs {KEY_ID_ENV} and {KEY_PATH_ENV} (a key file path) in the environment")
    return key_id, key_path


def _proxy_kwargs() -> dict[str, Any]:
    """``AsyncSTX`` kwargs that send this client, and nothing else in the process, through ``STX_HTTPS_PROXY``.

    stx-python 0.8.0 builds ``httpx.AsyncClient(transport=self._transport)`` (``stx/_async_client.py:314``) from the
    ``transport=`` argument (``:225``); httpx ignores the environment proxies once a transport is given.
    """
    proxy = os.environ.get(PROXY_ENV)
    if not proxy:
        return {}
    import httpx  # a dependency of stx-python, imported only where the proxy is used

    return {"transport": httpx.AsyncHTTPTransport(proxy=proxy)}


async def _fetch_live(
    region: str, env: str, with_players: bool, gsm_project: str | None = None
) -> tuple[list[dict], list[dict]]:
    key_id, key_path = _credentials(gsm_project)
    sdk = importlib.import_module("stx")  # optional vendor SDK (stx-python), only for --live
    kwargs = _proxy_kwargs()

    markets: list[dict] = []
    players: list[dict] = []
    async with sdk.AsyncSTX(region=region, env=env, key_id=key_id, private_key=key_path, **kwargs) as client:
        async for m in client.iter_markets(status="open"):
            markets.append(normalize(_dump(m)))
        if with_players:
            events = sorted({m["event_id"] for m in markets if m.get("rules") == "player_stat_line"})
            missing = 0
            for event_id in events:
                try:
                    body = _dump(await client.event_players(event_id))
                except sdk.STXException:  # one event without a roster (404 on 2026-10-29) must not lose the catalogue
                    missing += 1
                    continue
                players.append({"event_id": event_id, **body})
            if missing:
                print(
                    f"  stx: {missing}/{len(events)} events have no roster; their props map as no_roster",
                    file=sys.stderr,
                )
    return markets, players


class _TickSettings(NamedTuple):
    region: str
    env: str
    project: str


def _tick_settings(leagues: list[str], default_region: str) -> _TickSettings | None:
    """What the tick fetches with, or None (printed why) when it must not fetch: no ``STX_ENV``, no STX league."""
    from fetch.tip import stx_requested

    env = os.environ.get(TICK_ENV)
    if not env:
        print(f"stx: {TICK_ENV} not set -- skipping")
        return None
    if leagues and not stx_requested(leagues):
        print("stx: no requested league is an STX competition -- skipping")
        return None
    project = os.environ.get("GCP_PROJECT")
    if not project:
        raise SystemExit("FATAL: the STX tick fetch needs GCP_PROJECT")
    return _TickSettings(os.environ.get(TICK_REGION_ENV, default_region), env, project)


def main() -> None:
    """CLI entry: load the catalogue from a file or the live API into ``--out-dir``."""
    parser = argparse.ArgumentParser(description="Load STX's open markets for the STX pass.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--from-file", type=Path, help="exported markets list (.json / .jsonl, optionally .gz)")
    source.add_argument("--live", action="store_true", help="read GET /api/v1/markets with the SDK (signed)")
    parser.add_argument("--players", action="store_true", help="live: also fetch rosters for events with props")
    parser.add_argument("--players-file", type=Path, help="with --from-file: a captured rosters file")
    parser.add_argument("--region", default="ontario")
    parser.add_argument("--env", default="demo")
    parser.add_argument("--league", nargs="*", default=[], help="the tick's leagues: skip when none is an STX league")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--max-items", type=int, help="smoke test: keep the first N markets (the tick's --minimal)")
    args = parser.parse_args()
    tick = not args.live and args.from_file is None
    settings = _tick_settings(args.league, args.region) if tick else None
    if tick and settings is None:
        return
    args.out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    if settings is not None:
        markets, players = asyncio.run(_fetch_live(settings.region, settings.env, True, settings.project))
    elif args.live:
        markets, players = asyncio.run(_fetch_live(args.region, args.env, args.players))
    elif args.from_file is not None:
        markets = [normalize(r) for r in load_markets_list(args.from_file)]
        players = list(load_players(args.players_file).values()) if args.players_file else []
    else:
        raise SystemExit("unreachable: no source")
    if args.max_items:
        markets = markets[: args.max_items]
    n = write_jsonl(markets, args.out_dir / OUT_FILE)
    if players:
        write_jsonl(players, args.out_dir / PLAYERS_FILE)
    print(
        f"  stx: {n} markets, {len(players)} rosters -> {args.out_dir} ({time.monotonic() - started:.1f}s)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
