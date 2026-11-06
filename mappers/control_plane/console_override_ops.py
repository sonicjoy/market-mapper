"""Console override orchestration: publish → async job → read-back (G5)."""

from __future__ import annotations

import logging
import os
from typing import Any

from google.cloud import bigquery

from mappers.control_plane.console_oom_catalog import (
    lookup_rfq_key,
    preflight_fixture_materialisation,
)
from mappers.control_plane.console_override_jobs import (
    get_job,
    job_to_dict,
    start_override_job,
)
from mappers.control_plane.console_override_publish import (
    build_console_override_message,
    publish_console_override,
)
from mappers.control_plane.console_override_readers import override_unread_reason
from mappers.control_plane.console_override_lane import lane_venue, lookup_lane_key, reshape_message
from mappers.control_plane.console_sportsbook import sportsbook_lower
from mappers.control_plane.models import Actor, ForbiddenError, ValidationFailedError

logger = logging.getLogger(__name__)

_WRITE_ROLES = frozenset({"proposer", "approver", "admin", "service"})


def _project() -> str:
    return os.environ.get("GCP_PROJECT") or os.environ.get("BQ_PROJECT") or "marketmaking-test"


def _validate_override_body(body: dict[str, Any]) -> None:
    missing = [
        name
        for name, key in (
            ("game_id", "game_id"),
            ("market_id", "market_id"),
            ("selection", "selection"),
            ("source_market_id", "source_market_id"),
        )
        if not str(body.get(key) or "").strip()
    ]
    if missing:
        raise ValidationFailedError(
            f"missing required fields: {', '.join(missing)}",
            reason_code="bad_request",
            dry_run={},
        )


def _override_message_from_body(body: dict[str, Any], active: bool) -> dict[str, Any]:
    try:
        message = build_console_override_message(
            game_id=str(body.get("game_id") or ""),
            market_id=str(body.get("market_id") or ""),
            sportsbook=str(body.get("sportsbook") or ""),
            selection=str(body.get("selection") or ""),
            source_market_id=str(body.get("source_market_id") or ""),
            source_selection_id=str(body.get("source_selection_id") or ""),
            selection_line=str(body.get("selection_line") or ""),
            points=float(body.get("points") or 0.0),
            selection_points=float(body.get("selection_points") or 0.0),
            grouping_key=str(body.get("grouping_key") or "default"),
            active=active,
            mapping_source=str(body.get("mapping_source") or ""),
        )
        return reshape_message(
            message,
            str(body.get("sportsbook") or ""),
            str(body.get("source_market_id") or ""),
            str(body.get("source_selection_id") or ""),
        )
    except ValueError as exc:
        raise ValidationFailedError(
            str(exc),
            reason_code="bad_request",
            dry_run={},
        ) from exc


def _preflight_active_override(
    project: str,
    game_id: str,
    *,
    client: bigquery.Client | None = None,
) -> None:
    bq_client = client or bigquery.Client(project=project)
    preflight_reason = preflight_fixture_materialisation(bq_client, project, game_id)
    if preflight_reason:
        raise ValidationFailedError(
            f"override preflight failed: {preflight_reason}",
            reason_code="not_materialised",
            dry_run={},
        )


def _require_override_publish_access(body: dict[str, Any], actor: Actor) -> str:
    if actor.role.value not in _WRITE_ROLES:
        raise ForbiddenError("role cannot publish mapping overrides")
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise ValidationFailedError(
            "reason is required",
            reason_code="bad_request",
            dry_run={},
        )
    _validate_override_body(body)
    return reason


def _start_catalog_override_job(
    *,
    body: dict[str, Any],
    resolved_body: dict[str, Any],
    actor: Actor,
    active: bool,
    reason: str,
    project: str,
    client: bigquery.Client,
) -> dict[str, Any]:
    message = _override_message_from_body(resolved_body, active)
    if active:
        _preflight_active_override(
            project,
            str(body.get("game_id") or ""),
            client=client,
        )
    try:
        publish_message_id = publish_console_override(
            project,
            message,
            operator=actor.subject,
            reason=reason,
        )
    except Exception as exc:
        logger.exception("console override publish failed")
        raise ValidationFailedError(
            f"override publish failed: {exc}",
            reason_code="publish_failed",
            dry_run={},
        ) from exc
    job = start_override_job(
        message=message,
        operator=actor.subject,
        reason=reason,
        active=active,
        sportsbook=sportsbook_lower(str(body.get("sportsbook") or "")),
        source_market_id=str(resolved_body["source_market_id"] or ""),
        source_selection_id=str(resolved_body["source_selection_id"] or ""),
        publish_message_id=publish_message_id,
    )
    payload = job_to_dict(job)
    payload["poll_url"] = f"/console/catalog/override/jobs/{job.job_id}"
    return payload


def _resolved_override_body(
    body: dict[str, Any],
    *,
    client: bigquery.Client,
    project: str,
) -> dict[str, Any]:
    typed_market = str(body.get("source_market_id") or "").strip()
    typed_selection = str(body.get("source_selection_id") or "").strip()
    if lane_venue(str(body.get("sportsbook") or "")):
        # Lane venues are keyed exactly as typed (symbol / symbol + side); no opticodds_mapping resolve.
        return {**body, "source_market_id": typed_market, "source_selection_id": typed_selection}
    try:
        lookup_hit = lookup_rfq_key(
            client,
            sportsbook=str(body.get("sportsbook") or ""),
            source_market_id=typed_market,
            source_selection_id=typed_selection,
            project=project,
        )
    except Exception:
        logger.warning("catalog override lookup failed; using typed source ids", exc_info=True)
        return {
            **body,
            "source_market_id": typed_market,
            "source_selection_id": typed_selection,
        }
    if not lookup_hit.get("candidate_count"):
        return {
            **body,
            "source_market_id": typed_market,
            "source_selection_id": typed_selection,
        }
    return {
        **body,
        "source_market_id": lookup_hit["resolved_source_market_id"],
        "source_selection_id": lookup_hit["resolved_source_selection_id"],
    }


class ConsoleOverrideOpsMixin:
    """Catalog lookup and mapping_override publish for ProposalService."""

    def console_catalog_lookup(
        self,
        *,
        sportsbook: str,
        source_market_id: str,
        source_selection_id: str = "",
    ) -> dict[str, Any]:
        if not sportsbook.strip():
            raise ValidationFailedError(
                "sportsbook is required",
                reason_code="bad_request",
                dry_run={},
            )
        if not source_market_id.strip():
            raise ValidationFailedError(
                "source_market_id is required",
                reason_code="bad_request",
                dry_run={},
            )
        client = bigquery.Client(project=_project())
        if lane_venue(sportsbook):
            return lookup_lane_key(
                client,
                sportsbook=sportsbook,
                source_market_id=source_market_id,
                source_selection_id=source_selection_id,
                project=_project(),
            )
        return lookup_rfq_key(
            client,
            sportsbook=sportsbook,
            source_market_id=source_market_id,
            source_selection_id=source_selection_id,
        )

    def console_catalog_override(
        self,
        body: dict[str, Any],
        actor: Actor,
    ) -> dict[str, Any]:
        reason = _require_override_publish_access(body, actor)
        active = bool(body.get("active", True))
        unread = override_unread_reason(str(body.get("sportsbook") or "")) if active else None
        if unread:
            raise ValidationFailedError(unread, reason_code="override_not_read", dry_run={})
        project = _project()
        client = bigquery.Client(project=project)
        resolved_body = _resolved_override_body(body, client=client, project=project)
        return _start_catalog_override_job(
            body=body,
            resolved_body=resolved_body,
            actor=actor,
            active=active,
            reason=reason,
            project=project,
            client=client,
        )

    def console_catalog_override_job(self, job_id: str) -> dict[str, Any]:
        job = get_job(job_id)
        if job is None:
            raise KeyError(f"override job {job_id}")
        return job_to_dict(job)
