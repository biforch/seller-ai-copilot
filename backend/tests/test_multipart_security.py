"""Framework-level multipart parsing regressions (isolated from production app)."""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.testclient import TestClient

CANARY_BODY = "CANARY_MULTIPART_BODY_SECRET_MARKER"
CANARY_FILENAME = "CANARY_FILENAME\x7fSECRET"


@pytest.fixture
def multipart_app() -> FastAPI:
    app = FastAPI()

    @app.post("/form")
    async def accept_form(name: str = Form(...), note: str = Form(default="")) -> dict[str, str]:
        return {"name": name, "note": note}

    @app.post("/upload")
    async def accept_upload(file: UploadFile = File(...)) -> dict[str, str | int]:
        content = await file.read()
        return {"filename": file.filename or "", "size": len(content)}

    return app


@pytest.fixture
def multipart_client(multipart_app: FastAPI) -> TestClient:
    return TestClient(multipart_app)


def test_valid_small_multipart_form_parses(multipart_client: TestClient) -> None:
    response = multipart_client.post(
        "/form",
        data={"name": "seller", "note": "ok"},
    )
    assert response.status_code == 200
    assert response.json() == {"name": "seller", "note": "ok"}


def test_valid_multipart_file_upload_parses(multipart_client: TestClient) -> None:
    response = multipart_client.post(
        "/upload",
        files={"file": ("sample.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["filename"] == "sample.txt"
    assert response.json()["size"] == 5


def test_missing_boundary_is_rejected(multipart_client: TestClient) -> None:
    response = multipart_client.post(
        "/form",
        content=CANARY_BODY.encode(),
        headers={"Content-Type": "multipart/form-data"},
    )
    assert response.status_code == 400
    assert CANARY_BODY not in response.text


def test_malformed_boundary_is_rejected(multipart_client: TestClient) -> None:
    payload = (
        "--broken-boundary\r\n"
        'Content-Disposition: form-data; name="name"\r\n\r\n'
        "seller\r\n"
        "--broken-boundary--\r\n"
    )
    response = multipart_client.post(
        "/form",
        content=payload,
        headers={"Content-Type": 'multipart/form-data; boundary="other-boundary"'},
    )
    assert response.status_code == 400
    assert CANARY_BODY not in response.text


def test_parser_error_does_not_echo_body_canary(
    multipart_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR):
        response = multipart_client.post(
            "/form",
            content=f"name={CANARY_BODY}".encode(),
            headers={"Content-Type": "multipart/form-data; boundary=----missing"},
        )
    assert response.status_code == 400
    assert CANARY_BODY not in response.text
    assert CANARY_BODY not in caplog.text


def test_excessive_multipart_parts_are_bounded(multipart_client: TestClient) -> None:
    parts = []
    for index in range(64):
        parts.append(
            f'------limit\r\nContent-Disposition: form-data; name="f{index}"\r\n\r\nx\r\n'
        )
    parts.append("------limit--\r\n")
    response = multipart_client.post(
        "/form",
        content="".join(parts),
        headers={"Content-Type": "multipart/form-data; boundary=----limit"},
    )
    assert response.status_code in {400, 413, 422}
    assert response.status_code != 500


def test_control_characters_in_filename_are_not_logged(
    multipart_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        response = multipart_client.post(
            "/upload",
            files={"file": (CANARY_FILENAME, b"data", "text/plain")},
        )
    assert response.status_code == 200
    assert CANARY_FILENAME not in caplog.text
