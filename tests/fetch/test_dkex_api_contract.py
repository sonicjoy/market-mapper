"""DKEX REST batch contract against a local server (no venue host)."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import requests

from fetch.dkex_api import fetch_combo_metadata, fetch_market_metadata


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.bodies.append((self.path, body))  # type: ignore[attr-defined]
        if self.path == "/api/v1/markets/queries":
            payload = {
                "markets": [
                    {
                        "market": {
                            "ticker": body["tickers"][0],
                            "status": "active",
                        },
                    },
                ],
            }
        elif self.path == "/api/v1/combos/queries":
            payload = {
                "combos": [
                    {
                        "ticker": body["tickers"][0],
                        "status": "active",
                        "legs": [
                            {"ticker": "NFL-WIN-FG-01O0F7PEVSSRVBG-DEOS024", "side": "yes"},
                            {"ticker": "NFL-WIN-FG-01O0F7PEVSSRVBG-KCFS011", "side": "no"},
                        ],
                    },
                ],
            }
        else:
            self.send_response(404)
            self.end_headers()
            return
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def test_batch_posts_match_v061_shape() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.bodies = []  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        session = requests.Session()
        markets = fetch_market_metadata(
            session, base, ["NFL-WIN-FG-01O0F7PEVSSRVBG-DEOS024"],
        )
        combos = fetch_combo_metadata(
            session, base, ["COMBO-12783464979703431470"],
        )
    finally:
        server.shutdown()
        server.server_close()
    assert markets[0]["ticker"] == "NFL-WIN-FG-01O0F7PEVSSRVBG-DEOS024"
    assert combos[0]["legs"][0]["side"] == "yes"
    assert server.bodies == [  # type: ignore[attr-defined]
        (
            "/api/v1/markets/queries",
            {"tickers": ["NFL-WIN-FG-01O0F7PEVSSRVBG-DEOS024"]},
        ),
        (
            "/api/v1/combos/queries",
            {"tickers": ["COMBO-12783464979703431470"]},
        ),
    ]
