"""Streaming request-body limits for multipart generation uploads (H-03)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException
from starlette.datastructures import FormData

from smeme.decision_tree.generation.agentic.file_limits import (
    MAX_FORM_FIELDS,
    MAX_FORM_FILES,
    MAX_FORM_PART_SIZE_BYTES,
    MAX_REQUEST_BODY_BYTES,
)

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.types import Message


class RequestBodyTooLargeError(Exception):
    """Raised when streamed body bytes exceed the configured limit."""


async def read_form_with_body_limit(
    request: Request,
    *,
    max_body_bytes: int = MAX_REQUEST_BODY_BYTES,
    max_files: int = MAX_FORM_FILES,
    max_fields: int = MAX_FORM_FIELDS,
    max_part_size: int = MAX_FORM_PART_SIZE_BYTES,
) -> FormData:
    """
    Parse multipart/form-data with a hard body-byte ceiling.

    Starlette's max_part_size does not cap file parts, so Content-Length is
    checked first and the ASGI receive channel is wrapped to abort streaming
    once max_body_bytes is exceeded.
    """
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            length = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
        if length < 0:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")
        if length > max_body_bytes:
            raise HTTPException(status_code=413, detail="Request body too large")

    received = 0
    original_receive = request._receive

    async def limited_receive() -> Message:
        nonlocal received
        message = await original_receive()
        if message["type"] == "http.request":
            chunk = message.get("body", b"")
            received += len(chunk)
            if received > max_body_bytes:
                raise RequestBodyTooLargeError()
        return message

    request._receive = limited_receive
    try:
        return await request.form(
            max_files=max_files,
            max_fields=max_fields,
            max_part_size=max_part_size,
        )
    except RequestBodyTooLargeError as exc:
        raise HTTPException(status_code=413, detail="Request body too large") from exc
    finally:
        request._receive = original_receive
