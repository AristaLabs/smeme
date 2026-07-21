"""Security regressions for global exception handling."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from smeme.core.exception_handlers import validation_error_handler

pytestmark = pytest.mark.asyncio(loop_scope="session")


class _ValidationPayload(BaseModel):
    count: int


async def test_validation_error_logging_redacts_json_values(caplog):
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.post("/validate")
    async def validate_payload(payload: _ValidationPayload):
        return payload

    caplog.set_level(logging.ERROR, logger="smeme.core.exception_handlers")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/validate",
            json={"count": "secret-value-that-must-not-be-logged"},
        )

    assert response.status_code == 422
    assert "count" in caplog.text
    assert "secret-value-that-must-not-be-logged" not in caplog.text
