"""FastAPI surface for the M3a/M3b mapping control plane."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated, Any, cast

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from google.auth import exceptions as google_auth_exceptions

from BigQuery.client import ro_client
from BigQuery.override_lane import lane_enabled
from mappers.control_plane.auth import resolve_actor
from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.chat_live import build_chat_live_lookup
from mappers.control_plane.chat_router import handle_chat_turn
from mappers.control_plane.chat_stream import iter_chat_sse
from mappers.control_plane.console_override_readers import override_unread_sportsbooks
from mappers.control_plane.console_platforms import explore_platforms_payload
from mappers.control_plane.http_console import register_console_routes
from mappers.control_plane.http_entry import register_entry_routes
from mappers.control_plane.live_evidence import probe_pin_evidence
from mappers.control_plane.models import (
    Actor,
    BigQueryUnavailableError,
    ChatRequest,
    ChatResponse,
    ConflictError,
    ForbiddenError,
    ProposeRequest,
    ReviewActionRequest,
    ValidationFailedError,
)
from mappers.control_plane.pipeline_gap_propose import combine_open_pipeline_cards
from mappers.control_plane.request_metrics import bq_jobs, reset_bq_jobs
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings, get_settings
from mappers.control_plane.spa_static import (
    SPAStaticFiles,
    is_spa_document_path,
    resolve_static_dir,
    wants_html_document,
)
from mappers.control_plane.store import ProposalStore

_API_DESCRIPTION = """
Mapping rules control plane (M3a + M3b).

**Auth:** IAP header `X-Goog-Authenticated-User-Email`. Roles from
`MAPPING_CP_ADMIN_EMAILS` — never from the body.

**Console path (traders):** `/entry/*`, `/review/*`, `/console/rules`, `/meta`
— no rule-set ids in requests or responses.

**Automation path:** `/proposals/*`, `/rules`, `/rule-sets/*`.

Human-readable guide: `docs/mapping-rules/control-plane-api.md`.
"""

@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Warm the rule snapshot off-thread so readiness probes stay responsive."""
    threading.Thread(target=warm_rule_snapshot, name="rule-warmup", daemon=True).start()
    yield


app = FastAPI(
    title="mmmapper mapping control plane",
    version="3b",
    description=_API_DESCRIPTION,
    lifespan=_lifespan,
    openapi_tags=[
        {"name": "meta", "description": "Environment and operator identity"},
        {"name": "chat", "description": "Mapper Chat (M3c)"},
        {"name": "entry", "description": "Trader paste verify + submit (M3b)"},
        {"name": "review", "description": "Maker/checker review queue (M3b)"},
        {"name": "console", "description": "Human-readable rules explorer"},
        {"name": "proposals", "description": "Proposal lifecycle (automation)"},
        {"name": "rules", "description": "Rule-set read / diff (includes internal ids)"},
    ],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_STATIC_DIR = resolve_static_dir()

logger = logging.getLogger(__name__)

# Only log fast requests when they touched BigQuery; log anything slow.
_SLOW_REQUEST_MS = 1000.0


@app.middleware("http")
async def spa_api_bridge(
    request: Request,
    call_next: Callable[[Request], Any],
) -> Any:
    """Rewrite ``/api/*`` → ``/*`` and serve the SPA for HTML navigations."""
    path = request.scope["path"]
    if path == "/api" or path.startswith("/api/"):
        path = path[4:] or "/"
        request.scope["path"] = path

    if (
        _STATIC_DIR is not None
        and request.method == "GET"
        and wants_html_document(request.headers.get("accept", ""))
        and is_spa_document_path(path)
    ):
        resp = FileResponse(_STATIC_DIR / "index.html", media_type="text/html")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    return await call_next(request)


@app.middleware("http")
async def request_timing(
    request: Request,
    call_next: Callable[[Request], Any],
) -> Any:
    """Log duration and BigQuery job count so a regression is visible."""
    reset_bq_jobs()
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    jobs = bq_jobs()
    if jobs or elapsed_ms >= _SLOW_REQUEST_MS:
        logger.info(
            "%s %s status=%s duration_ms=%.0f bq_jobs=%d",
            request.method,
            request.scope["path"],
            response.status_code,
            elapsed_ms,
            jobs,
        )
    return response


def warm_rule_snapshot() -> None:
    """Pre-load the tip so the first trader after a deploy hits a warm cache."""
    try:
        control = service()
        tip = control.store.current_rule_set_id
        if tip:
            control.store.entities_for(tip)
            control.store.leagues_for(tip)
            control.store.market_rules_for(tip)
    except Exception:  # noqa: BLE001 — warmup must never block startup
        logger.warning("rule snapshot warmup skipped", exc_info=True)


@app.get("/healthz", tags=["meta"])
def healthz() -> dict[str, bool]:
    """Liveness/readiness probe — no upstream calls."""
    return {"ok": True}


def authenticated_actor(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Actor:
    """Derive the actor from the IAP gateway identity + server-side allow-lists."""
    return resolve_actor(request, settings)


@lru_cache
def service() -> ProposalService:
    """Build the production BigQuery-backed service once per process."""
    settings = get_settings()
    store = BigQueryStore(
        ro_client(),
        environment=settings.environment,
        allow_activate=settings.allow_activate,
        cow_enabled=settings.cow_enabled,
        review_window_days=settings.review_window_days,
    )
    return ProposalService(
        cast(ProposalStore, store),
        require_maker_checker=settings.require_maker_checker,
        live=build_chat_live_lookup(settings),
        evidence_fn=probe_pin_evidence,
    )


def _translate_error(exc: Exception) -> HTTPException:
    """Translate domain errors to stable HTTP status codes."""
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=409, detail={"reason_code": exc.reason_code})
    if isinstance(exc, ForbiddenError):
        return HTTPException(status_code=403, detail={"reason_code": exc.reason_code})
    if isinstance(exc, ValidationFailedError):
        return HTTPException(
            status_code=422,
            detail={
                "reason_code": exc.reason_code,
                "message": str(exc),
                "dry_run": exc.dry_run,
            },
        )
    if isinstance(exc, BigQueryUnavailableError):
        return HTTPException(
            status_code=503,
            detail={"reason_code": exc.reason_code, "message": str(exc)},
        )
    if isinstance(exc, google_auth_exceptions.GoogleAuthError):
        # Expired ADC locally, or an unmintable Workload Identity token in GKE.
        return HTTPException(
            status_code=503,
            detail={"reason_code": "bq_credentials", "message": str(exc)},
        )
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail={"reason_code": "not_found"})
    return HTTPException(status_code=500, detail={"reason_code": "internal_error"})


def _call(action: Any) -> Any:
    """Execute one service call with domain-to-HTTP translation."""
    try:
        return action()
    except (
        ConflictError,
        ForbiddenError,
        ValidationFailedError,
        BigQueryUnavailableError,
        google_auth_exceptions.GoogleAuthError,
        KeyError,
    ) as exc:
        raise _translate_error(exc) from exc


@app.get("/meta", tags=["meta"])
def meta(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Shell metadata: env, operator, role (trading-dash pattern)."""
    actor = resolve_actor(request, settings)
    return {
        "env": settings.environment,
        "operator": actor.subject,
        "role": actor.role.value,
        "build": "dev",
        "require_maker_checker": settings.require_maker_checker,
        "chat_enabled": settings.chat_enabled,
        "catalog_enabled": settings.catalog_enabled,
        "live_sot": settings.live_sot,
        "allow_activate": settings.allow_activate,
        "explore_platforms": explore_platforms_payload(),
        "override_unread_sportsbooks": override_unread_sportsbooks(),
        "override_lane_enabled": lane_enabled(),
    }


@app.post("/chat", tags=["chat"], response_model=ChatResponse)
def chat(
    body: ChatRequest,
    actor: Annotated[Actor, Depends(authenticated_actor)],
    settings: Annotated[Settings, Depends(get_settings)],
    control: Annotated[ProposalService, Depends(service)],
) -> ChatResponse:
    """Mapper Chat turn (JSON). Prefer `/chat/stream` for progressive tokens."""
    return handle_chat_turn(
        body,
        settings=settings,
        store=control.store,
        live=control.live,
        actor=actor.subject,
        evidence_fn=control.evidence_fn,
    )


@app.post("/chat/stream", tags=["chat"])
async def chat_stream(
    body: ChatRequest,
    actor: Annotated[Actor, Depends(authenticated_actor)],
    settings: Annotated[Settings, Depends(get_settings)],
    control: Annotated[ProposalService, Depends(service)],
) -> StreamingResponse:
    """Mapper Chat turn as SSE (`status`, keepalives, `token` chunks + `final`)."""
    status_queue: queue.Queue[str] = queue.Queue()

    def _turn() -> ChatResponse:
        return handle_chat_turn(
            body,
            settings=settings,
            store=control.store,
            live=control.live,
            status_queue=status_queue,
            actor=actor.subject,
            evidence_fn=control.evidence_fn,
        )

    return StreamingResponse(
        iter_chat_sse(body.message or "", _turn, status_queue=status_queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


register_entry_routes(
    app,
    authenticated_actor=authenticated_actor,
    service=service,
    call=_call,
)


@app.get("/review/recent", tags=["review"])
def review_recent(
    control: Annotated[ProposalService, Depends(service)],
    limit: int = 10,
) -> Any:
    """Recent proposals (pending, approved, rejected) for the console list."""
    capped = max(1, min(limit, 50))
    return _call(lambda: control.list_review_history(limit=capped))


@app.get("/review", tags=["review"])
def review_list(control: Annotated[ProposalService, Depends(service)]) -> Any:
    """Trader-safe review queue."""
    return _call(lambda: control.list_review())


@app.post("/review/combine-pipeline", tags=["review"])
def review_combine_pipeline(
    actor: Annotated[Actor, Depends(authenticated_actor)],
    control: Annotated[ProposalService, Depends(service)],
) -> Any:
    """Union open pipeline-gap-fix cards into one Review card, then re-list."""
    _ = actor

    def _combine_and_list() -> Any:
        combine_open_pipeline_cards(control)
        return control.list_review()

    return _call(_combine_and_list)


@app.get("/review/{ref}", tags=["review"])
def review_detail(
    ref: str,
    control: Annotated[ProposalService, Depends(service)],
) -> Any:
    """Trader-safe review detail."""
    return _call(lambda: control.get_review(ref))


@app.post("/review/{ref}/approve", tags=["review"])
def review_approve(
    ref: str,
    actor: Annotated[Actor, Depends(authenticated_actor)],
    control: Annotated[ProposalService, Depends(service)],
) -> Any:
    """Approve via opaque review ref."""
    return _call(lambda: control.approve_review(ref, actor))


@app.post("/review/{ref}/reject", tags=["review"])
def review_reject(
    ref: str,
    body: ReviewActionRequest,
    actor: Annotated[Actor, Depends(authenticated_actor)],
    control: Annotated[ProposalService, Depends(service)],
) -> Any:
    """Reject via opaque review ref."""
    return _call(lambda: control.reject_review(ref, actor, body.comment))


@app.post("/review/{ref}/request-changes", tags=["review"])
def review_request_changes(
    ref: str,
    body: ReviewActionRequest,
    actor: Annotated[Actor, Depends(authenticated_actor)],
    control: Annotated[ProposalService, Depends(service)],
) -> Any:
    """Request changes via opaque review ref."""
    return _call(lambda: control.request_changes_review(ref, actor, body.comment))


register_console_routes(
    app,
    authenticated_actor=authenticated_actor,
    service=service,
    call=_call,
)


@app.post("/proposals", tags=["proposals"])
def propose(
    body: ProposeRequest,
    actor: Annotated[Actor, Depends(authenticated_actor)],
    control: Annotated[ProposalService, Depends(service)],
) -> Any:
    """Create an idempotent proposal."""
    return _call(lambda: control.propose(body, actor))


@app.post("/proposals/{proposal_id}/validate", tags=["proposals"])
def validate(
    proposal_id: str,
    actor: Annotated[Actor, Depends(authenticated_actor)],
    control: Annotated[ProposalService, Depends(service)],
) -> Any:
    """Build and dry-run a candidate immutable snapshot."""
    return _call(lambda: control.validate(proposal_id, actor))


@app.post("/proposals/{proposal_id}/approve", tags=["proposals"])
def approve(
    proposal_id: str,
    actor: Annotated[Actor, Depends(authenticated_actor)],
    control: Annotated[ProposalService, Depends(service)],
) -> Any:
    """Approve with maker/checker and test-only service activation."""
    return _call(lambda: control.approve(proposal_id, actor))


@app.post("/proposals/{proposal_id}/reject", tags=["proposals"])
def reject_proposal(
    proposal_id: str,
    body: ReviewActionRequest,
    actor: Annotated[Actor, Depends(authenticated_actor)],
    control: Annotated[ProposalService, Depends(service)],
) -> Any:
    """Reject a proposal (automation / M3a path)."""
    return _call(lambda: control.reject(proposal_id, actor, body.comment))


@app.post("/proposals/{proposal_id}/request-changes", tags=["proposals"])
def request_changes_proposal(
    proposal_id: str,
    body: ReviewActionRequest,
    actor: Annotated[Actor, Depends(authenticated_actor)],
    control: Annotated[ProposalService, Depends(service)],
) -> Any:
    """Request changes (automation / M3a path)."""
    return _call(lambda: control.request_changes(proposal_id, actor, body.comment))


@app.get("/proposals", tags=["proposals"])
def proposals(control: Annotated[ProposalService, Depends(service)]) -> Any:
    """List proposals."""
    return control.list_proposals()


@app.get("/proposals/{proposal_id}", tags=["proposals"])
def proposal(
    proposal_id: str,
    control: Annotated[ProposalService, Depends(service)],
) -> Any:
    """Read one proposal."""
    return _call(lambda: control.get_proposal(proposal_id))


@app.get("/rules", tags=["rules"])
def rules(
    control: Annotated[ProposalService, Depends(service)],
    at: str | None = None,
) -> Any:
    """Read latest shadow or test-activated entity rules (optional as-of timestamp)."""
    return control.list_rules(at=at)


@app.get("/rule-sets/{rule_set_id}/diff", tags=["rules"])
def diff(
    rule_set_id: str,
    control: Annotated[ProposalService, Depends(service)],
) -> Any:
    """Diff a candidate rule set against its parent."""
    return _call(lambda: control.diff_rule_set(rule_set_id))


if _STATIC_DIR is not None:
    # Mount last so API routes (/healthz, /meta, /entry, …) take precedence.
    app.mount("/", SPAStaticFiles(directory=str(_STATIC_DIR), html=True), name="spa")
