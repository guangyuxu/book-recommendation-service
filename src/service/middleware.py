"""Correlation-id middleware (TODO D).

Reads an inbound `X-Request-Id` (or generates one), stores it in a contextvar so logs and error
envelopes can reference it, and echoes it on the response. The same id is forwarded to the agent
via the SDK client headers so a turn can be traced across both services.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .logging import request_id_var

REQUEST_ID_HEADER = "X-Request-Id"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
