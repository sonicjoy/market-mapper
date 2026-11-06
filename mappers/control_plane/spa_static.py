"""SPA static serving helpers for the mapping console."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

SPA_EXACT = frozenset(
    {
        "/",
        "/entry",
        "/cart",
        "/review",
        "/rules",
        "/coverage",
        "/unmapped",
        "/catalog",
        "/api-docs",
        "/inbox",
    }
)


class SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html for client-side routes."""

    async def get_response(self, path: str, scope: Any) -> Response:
        try:
            resp = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            resp = await super().get_response("index.html", scope)
        if getattr(resp, "media_type", None) == "text/html" or path in ("", "index.html"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp


def resolve_static_dir() -> Path | None:
    """Return the SPA dist dir when present (env override or image default)."""
    raw = os.environ.get("MAPPING_CP_STATIC_DIR", "").strip()
    candidates = [Path(raw)] if raw else []
    candidates.append(Path("/app/console/dist"))
    for path in candidates:
        if path.is_dir() and (path / "index.html").exists():
            return path
    return None


def wants_html_document(accept: str) -> bool:
    """True for browser document navigations, false for JSON API clients."""
    if "application/json" in accept:
        return False
    return "text/html" in accept


def is_spa_document_path(path: str) -> bool:
    """Paths the React router owns (hard-refresh must return index.html)."""
    if path in SPA_EXACT:
        return True
    if path.startswith("/review/") and path.count("/") == 2:
        return True
    return bool(path.startswith("/inbox/") and path.count("/") == 2)
