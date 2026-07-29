"""Unit tests for H-03 upload/parser resource-exhaustion controls."""

from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from smeme.decision_tree.generation.agentic import ingestion
from smeme.decision_tree.generation.agentic.file_limits import (
    MAX_DOCX_COMPRESSION_RATIO,
    MAX_DOCX_ZIP_ENTRIES,
    MAX_REQUEST_BODY_BYTES,
)
from smeme.decision_tree.generation.agentic.ingestion import (
    assert_docx_zip_bounds,
    parse_uploaded_file,
)
from smeme.decision_tree.generation.agentic.request_limits import read_form_with_body_limit


def _zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def _zip_bomb_like_bytes() -> bytes:
    """Small ZIP whose uncompressed/compressed ratio exceeds the DOCX limit."""
    payload = b"0" * (int(MAX_DOCX_COMPRESSION_RATIO) * 2000)
    return _zip_bytes([("word/document.xml", payload)])


def _sleepy_parse_entry(path_str: str, ext: str, conn) -> None:
    """Picklable child target that ignores the file and hangs (for kill tests)."""
    import time

    time.sleep(30)
    conn.send(("ok", "never"))
    conn.close()


class TestDocxZipBounds:
    def test_rejects_too_many_entries(self, tmp_path: Path):
        entries = [(f"e{i}.txt", b"x") for i in range(MAX_DOCX_ZIP_ENTRIES + 1)]
        path = tmp_path / "many.docx"
        path.write_bytes(_zip_bytes(entries))
        with pytest.raises(ValueError, match="too many entries"):
            assert_docx_zip_bounds(path)

    def test_rejects_high_compression_ratio(self, tmp_path: Path):
        path = tmp_path / "bomb.docx"
        path.write_bytes(_zip_bomb_like_bytes())
        with pytest.raises(ValueError, match="compression ratio"):
            assert_docx_zip_bounds(path)

    def test_accepts_normal_docx_zip(self, tmp_path: Path):
        path = tmp_path / "ok.docx"
        path.write_bytes(
            _zip_bytes(
                [
                    ("[Content_Types].xml", b"<Types/>"),
                    ("word/document.xml", b"<w:document>hello</w:document>"),
                ]
            )
        )
        assert_docx_zip_bounds(path)


class TestRequestBodyLimit:
    @pytest.mark.asyncio
    async def test_content_length_over_limit_returns_413(self):
        async def endpoint(request: Request):
            await read_form_with_body_limit(request, max_body_bytes=1024)
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route("/", endpoint, methods=["POST"])])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                content=b"x=1",
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "content-length": str(MAX_REQUEST_BODY_BYTES + 1),
                },
            )
        assert response.status_code == 413

    @pytest.mark.asyncio
    async def test_body_over_limit_returns_413(self):
        async def endpoint(request: Request):
            await read_form_with_body_limit(request, max_body_bytes=64)
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route("/", endpoint, methods=["POST"])])
        transport = ASGITransport(app=app)
        boundary = "----smemeboundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="f"; filename="a.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n" + ("y" * 200) + f"\r\n--{boundary}--\r\n"
        ).encode()
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                content=body,
                headers={"content-type": f"multipart/form-data; boundary={boundary}"},
            )
        assert response.status_code == 413

    @pytest.mark.asyncio
    async def test_valid_small_form_accepted(self):
        async def endpoint(request: Request):
            form = await read_form_with_body_limit(request, max_body_bytes=10_000)
            return JSONResponse({"title": form.get("title")})

        app = Starlette(routes=[Route("/", endpoint, methods=["POST"])])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/", data={"title": "ok"})
        assert response.status_code == 200
        assert response.json()["title"] == "ok"


@pytest.mark.asyncio
async def test_invalid_content_length_returns_400():
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"content-length", b"not-a-number")],
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(scope, receive)
    with pytest.raises(HTTPException) as exc_info:
        await read_form_with_body_limit(request, max_body_bytes=100)
    assert exc_info.value.status_code == 400


class TestIsolatedParseTimeout:
    @pytest.mark.asyncio
    async def test_timeout_surfaces_as_parse_failure(self, tmp_path: Path):
        from pypdf import PdfWriter

        path = tmp_path / "hang.pdf"
        with path.open("wb") as f:
            writer = PdfWriter()
            writer.add_blank_page(72, 72)
            writer.write(f)

        def _hang(_path: Path, _ext: str, _timeout: float) -> str:
            raise TimeoutError("Parse timed out after 1s")

        with patch.object(ingestion, "_parse_file_in_process", side_effect=_hang):
            result = await parse_uploaded_file(path, "hang.pdf")
        assert result.success is False
        assert "timed out" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_hung_child_process_is_killed(self, tmp_path: Path):
        path = tmp_path / "slow.pdf"
        path.write_bytes(b"%PDF-1.4\n")

        with (
            patch.object(ingestion, "_parse_file_process_entry", _sleepy_parse_entry),
            pytest.raises(TimeoutError, match="timed out"),
        ):
            await asyncio.to_thread(ingestion._parse_file_in_process, path, ".pdf", 1.0)
