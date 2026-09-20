"""
Per-request user context. The frontend sends the current user's UID in the
'X-User-Id' header on every request. A FastAPI middleware copies that value
into a ContextVar so any data-layer function can scope reads/writes to the
current user without changing every endpoint signature.

Conventions:
  * Guests use the literal user_id "guest" (matches the demo seed tags).
  * Authenticated users use their stable UID (Firebase UID or similar).
  * Legacy documents that have no user_id field are treated as guest data
    so demo content keeps working for guests.
"""
from contextvars import ContextVar
from typing import Awaitable, Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

GUEST_UID = "guest"
_MAX_UID_LEN = 128

current_user_id_var: ContextVar[str] = ContextVar("current_user_id", default=GUEST_UID)


def get_uid() -> str:
    """Return the user_id for the current request (defaults to 'guest')."""
    return current_user_id_var.get()


def is_guest(uid: str | None = None) -> bool:
    return (uid if uid is not None else get_uid()) == GUEST_UID


def belongs_to_current_user(doc: dict) -> bool:
    """True if the document's user_id matches the current request's user.

    Checks both `user_id` and the legacy camelCase `userId` field that the
    capture pipeline writes. Untagged legacy docs fall back to guest ownership
    so demo content still surfaces for guests.
    """
    if not isinstance(doc, dict):
        return False
    owner = doc.get("user_id") or doc.get("userId") or GUEST_UID
    return owner == get_uid()


def stamp(doc: dict) -> dict:
    """Tag a doc with the current user_id (in place) and return it.

    Writes both snake_case and camelCase variants so legacy code that reads
    `userId` keeps working alongside the new scoping logic.
    """
    if isinstance(doc, dict):
        uid = get_uid()
        doc["user_id"] = uid
        doc["userId"] = uid
    return doc


class UserContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        raw = request.headers.get("x-user-id", "") or ""
        uid = raw.strip()[:_MAX_UID_LEN] or GUEST_UID
        token = current_user_id_var.set(uid)
        try:
            return await call_next(request)
        finally:
            current_user_id_var.reset(token)
