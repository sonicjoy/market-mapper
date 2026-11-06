"""Operator identity from the IAP gateway for the M3a control plane.

We do not reinvent authentication. Like mm-trading-dash, every request reaches
this app through Identity-Aware Proxy, which injects the signed
``X-Goog-Authenticated-User-Email`` header (format
``accounts.google.com:user@domain``). We trust that header for the caller's
identity rather than a client-supplied actor field.

Authorization (who may administer) is resolved server-side from the
admin allow-list, never from the request — the plan requires the actor on
``rule_approved`` to come from authentication so maker/checker cannot be forged.
The ``service`` role is internal (test-only activation) and is never derived
from a request.
"""

from __future__ import annotations

from fastapi import Request

from mappers.control_plane.models import Actor, ActorRole, ForbiddenError
from mappers.control_plane.settings import Settings

_IAP_EMAIL_HEADER = "X-Goog-Authenticated-User-Email"
UNKNOWN_OPERATOR = "unknown"


def operator_email(request: Request) -> str:
    """Return the IAP-authenticated caller email (or ``unknown``)."""
    raw = request.headers.get(_IAP_EMAIL_HEADER, "").strip()
    if not raw:
        return UNKNOWN_OPERATOR
    # Strip the "accounts.google.com:" identity-namespace prefix if present.
    return raw.split(":", 1)[1] if ":" in raw else raw


def resolve_role(email: str, settings: Settings) -> ActorRole:
    """Map an authenticated email to a control-plane role."""
    if email == UNKNOWN_OPERATOR:
        return ActorRole.VIEWER
    if email.lower() in settings.admin_emails:
        return ActorRole.ADMIN
    # IAP already gates console access (traders@); any authenticated caller may approve.
    return ActorRole.APPROVER


def resolve_actor(request: Request, settings: Settings) -> Actor:
    """Build the authenticated actor from the IAP email and role allow-lists."""
    email = operator_email(request)
    return Actor(subject=email, role=resolve_role(email, settings))


def require_admin(actor: Actor) -> Actor:
    """Raise when the caller is not an admin (Parity / API docs)."""
    if actor.role != ActorRole.ADMIN:
        raise ForbiddenError("admin only", reason_code="forbidden")
    return actor
