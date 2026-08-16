from __future__ import annotations

from typing import Any
from uuid import uuid4

from mira.models import ServerEnvelope, utc_now


PROTOCOL_VERSION = "0.1"


def make_server_envelope(
    *,
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
    requires_ack: bool = False,
    correlation_id: str | None = None,
) -> ServerEnvelope:
    return ServerEnvelope(
        protocol_version=PROTOCOL_VERSION,
        event_id=f"evt-{uuid4().hex}",
        session_id=session_id,
        type=event_type,
        timestamp=utc_now(),
        correlation_id=correlation_id,
        requires_ack=requires_ack,
        payload=payload,
    )

