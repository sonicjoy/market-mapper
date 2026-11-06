"""Fetch the Underdog Exchange (UDX) open single-leg catalogue.

Usage:
    python -m fetch.underdog --league nfl mlb --out-dir data/2026-09-24/16_00
    python -m fetch.underdog --all-leagues --out-dir data_raw/...

Writes ``underdog_markets.jsonl``: one venue ``Market`` object per line
(``ticker``, ``description``, ``status``, ``expires_at``, tick/price
bounds) — the rows ``mappers.exchanges.underdog_pass.run_pass`` reads.
The pass keys on ``ticker`` (grammar), ``description`` (team and player
names) and ``status``; everything else is carried verbatim.

Source: ``GET /markets?type=single_leg&status=open`` (prod openapi
``listMarkets``: ``limit`` 1..100, opaque ``page`` cursor, root-relative
``next_page_url`` that keeps the filters, ordered by ticker). The read is
public — its ``security`` list includes ``{}`` — so no key is needed.
Unauthenticated calls share the public per-client bucket (observed
2026-09-24: ``RateLimit-Policy: "read";q=8;w=2``), so the pager honours
``RateLimit`` / ``Retry-After`` and backs off on 429 and 5xx.

Every open single-leg row is kept: the mapper decides which league a row
belongs to from its Optic fixture id, so nothing is filtered by ticker.
Nothing is written when no requested league has Underdog. The file is
written atomically, so a failed page leaves no half catalogue behind.

Optional signed auth (``UDX_AUTH=signed``) reads ``udx-api-key-id`` and
``udx-private-key`` from Secret Manager in ``GCP_PROJECT`` and signs each
request the way mm-underdogrfq's ``UdxSigner`` does (RSA-PSS SHA-256,
32-byte salt over ``timestamp + METHOD + path``).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess  # nosec B404 — gcloud secret read, the repo-wide pattern (fetch/novig.py)
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from fetch.gcloud_util import gcloud_cmd

DEFAULT_BASE = "https://api.underdogexchange.com"
OUT_FILE = "underdog_markets.jsonl"
MARKETS_PATH = "/markets"
PAGE_SIZE = 100  # listMarkets limit maximum
API_VERSION = "2026-07-15"  # UDX-Version the prod server answered with on 2026-09-24
USER_AGENT = "wsd-mmmapper/1.0 (+underdog catalogue fetch)"
# Runaway guard: ~33k open single-leg rows on 2026-09-23 is ~330 pages.
MAX_PAGES = 3000
MAX_TRIES = 6
MAX_SLEEP_S = 30.0
TIMEOUT_S = 30
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_RATELIMIT_RE = re.compile(r"\br=(\d+)\b.*?\bt=(\d+)\b")

Sleep = Callable[[float], None]


class UdxFetchError(RuntimeError):
    """A catalogue fetch that cannot complete."""


def _signed_headers_factory(project: str) -> Callable[[str, str], dict[str, str]]:
    """Header builder for signed reads, from the two GSM secrets."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

    def secret(name: str) -> str:
        return subprocess.check_output(  # nosec B603 — fixed argv, no shell, code-derived args
            gcloud_cmd(
                "secrets",
                "versions",
                "access",
                "latest",
                f"--secret={name}",
                f"--project={project}",
            ),
            text=True,
        ).strip()

    key_id = secret("udx-api-key-id")
    key = serialization.load_pem_private_key(secret("udx-private-key").encode(), password=None)
    if not isinstance(key, RSAPrivateKey):
        raise UdxFetchError("udx-private-key is not an RSA key")
    pss = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)

    def headers(method: str, path: str) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        sig = key.sign((ts + method.upper() + path).encode(), pss, hashes.SHA256())
        return {
            "UDX-Access-Key": key_id,
            "UDX-Access-Timestamp": ts,
            "UDX-Access-Signature": base64.b64encode(sig).decode("ascii"),
        }

    return headers


def make_session() -> requests.Session:
    """Session with the headers the prod edge accepts (default urllib UA got 403)."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "UDX-Version": API_VERSION,
        }
    )
    return session


def _retry_after(resp: requests.Response, fallback: float) -> float:
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return min(MAX_SLEEP_S, max(0.0, float(raw)))
        except ValueError:
            pass
    return min(MAX_SLEEP_S, fallback)


def _pace(resp: requests.Response, sleep: Sleep) -> None:
    """Wait out the window when the public bucket says nothing is left."""
    match = _RATELIMIT_RE.search(resp.headers.get("RateLimit") or "")
    if match is not None and int(match.group(1)) == 0:
        sleep(min(MAX_SLEEP_S, float(match.group(2))))


def get_json(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    sign: Callable[[str, str], dict[str, str]] | None = None,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    """GET with retries on 429/5xx/transport errors; raise on anything else."""
    backoff = 1.0
    path = urlsplit(url).path
    for attempt in range(1, MAX_TRIES + 1):
        headers = sign("GET", path) if sign is not None else None
        try:
            resp = session.get(url, params=params, headers=headers, timeout=TIMEOUT_S)
        except requests.RequestException as exc:
            if attempt == MAX_TRIES:
                raise UdxFetchError(f"GET {path}: {exc}") from exc
            print(f"  underdog GET {path} attempt {attempt}: {exc}; retry in {backoff:.0f}s", file=sys.stderr)
            sleep(backoff)
            backoff = min(MAX_SLEEP_S, backoff * 2)
            continue
        if resp.status_code in RETRY_STATUSES and attempt < MAX_TRIES:
            wait = _retry_after(resp, backoff)
            print(
                f"  underdog GET {path} attempt {attempt}: HTTP {resp.status_code}; retry in {wait:.1f}s",
                file=sys.stderr,
            )
            sleep(wait)
            backoff = min(MAX_SLEEP_S, backoff * 2)
            continue
        if resp.status_code in (401, 403) and sign is None:
            raise UdxFetchError(
                f"GET {path}: HTTP {resp.status_code} unauthenticated — set UDX_AUTH=signed "
                "to sign with GSM udx-api-key-id / udx-private-key"
            )
        if resp.status_code != 200:
            raise UdxFetchError(f"GET {path}: HTTP {resp.status_code} {resp.text[:200]}")
        _pace(resp, sleep)
        return resp.json()
    raise UdxFetchError(f"GET {path}: retries exhausted")  # pragma: no cover — loop always returns/raises


def _next_url(base: str, next_page_url: object) -> str | None:
    """Absolute URL for the venue's root-relative next page, or None at the end."""
    if not next_page_url:
        return None
    rel = str(next_page_url)
    if not rel.startswith("/") or rel.startswith("//"):
        raise UdxFetchError(f"refusing non root-relative next_page_url {rel!r}")
    return base.rstrip("/") + rel


def iter_markets(
    session: requests.Session,
    base: str,
    *,
    sign: Callable[[str, str], dict[str, str]] | None = None,
    sleep: Sleep = time.sleep,
    max_pages: int = MAX_PAGES,
) -> Iterator[dict[str, Any]]:
    """Every open single-leg market, page by page, following ``next_page_url``."""
    url: str | None = base.rstrip("/") + MARKETS_PATH
    params: dict[str, Any] | None = {"type": "single_leg", "status": "open", "limit": PAGE_SIZE}
    seen: set[str] = set()
    pages = 0
    while url is not None:
        pages += 1
        if pages > max_pages:
            raise UdxFetchError(f"more than {max_pages} pages — pagination loop?")
        body = get_json(session, url, params=params, sign=sign, sleep=sleep)
        markets = body.get("markets")
        if not isinstance(markets, list):
            raise UdxFetchError(f"page {pages}: no markets array")
        yield from markets
        url = _next_url(base, body.get("next_page_url"))
        params = None  # next_page_url carries limit/page/status/type
        if url is not None:
            if url in seen:
                raise UdxFetchError(f"page {pages}: next_page_url repeats")
            seen.add(url)


def keep_rows(
    markets: Iterable[dict[str, Any]],
    *,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    """Single-leg rows that carry a ticker."""
    out: list[dict[str, Any]] = []
    for market in markets:
        ticker = str(market.get("ticker") or "")
        if not ticker or market.get("legs"):
            continue
        out.append(market)
        if max_items is not None and len(out) >= max_items:
            break
    return out


def write_jsonl(rows: list[dict[str, Any]], out_dir: Path) -> Path:
    """Atomic write of ``underdog_markets.jsonl``."""
    path = out_dir / OUT_FILE
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    tmp.replace(path)
    return path


def main(argv: list[str] | None = None) -> int:
    """CLI entry: fetch, filter, write."""
    parser = argparse.ArgumentParser(description="Fetch the UDX open single-leg catalogue.")
    parser.add_argument("--league", nargs="+", default=[], help="League slugs; skipped when none has Underdog")
    parser.add_argument("--all-leagues", action="store_true", help="Fetch even when no league is requested")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--max-items", type=int, help="Stop after N kept rows (smoke test)")
    args = parser.parse_args(argv)

    if not args.all_leagues:
        from fetch.tip import underdog_requested

        if not underdog_requested(args.league):
            print("underdog: no requested league has Underdog enabled — skipping")
            return 0

    base = os.environ.get("UDX_API_BASE", DEFAULT_BASE)
    sign = None
    if os.environ.get("UDX_AUTH", "").lower() == "signed":
        project = os.environ.get("GCP_PROJECT")
        if not project:
            print("FATAL: UDX_AUTH=signed needs GCP_PROJECT", file=sys.stderr)
            return 2
        sign = _signed_headers_factory(project)

    started = time.monotonic()
    try:
        rows = keep_rows(
            iter_markets(make_session(), base, sign=sign),
            max_items=args.max_items,
        )
    except UdxFetchError as exc:
        print(f"FATAL: underdog fetch: {exc}", file=sys.stderr)
        return 1
    path = write_jsonl(rows, Path(args.out_dir))
    print(f"underdog: {len(rows)} open single-leg markets -> {path} ({time.monotonic() - started:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
