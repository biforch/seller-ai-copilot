"""Credential-free hardened Alpine candidate runtime smoke checks."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SUCCESS_MESSAGE = "alpine hardened smoke validation passed"

SMOKE_HOST = "127.0.0.1"
SMOKE_PORT = 8765
STARTUP_TIMEOUT_SECONDS = 30
POLL_INTERVAL_SECONDS = 0.25


class AlpineHardenedSmokeError(Exception):
    reason_code: str

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _prepare_import_environment() -> None:
    app_root = str(Path(__file__).resolve().parent.parent)
    if app_root not in sys.path:
        sys.path.insert(0, app_root)
    os.environ.setdefault("ENVIRONMENT", "testing")
    os.environ.setdefault("AMAZON_SP_API_ENDPOINT_MODE", "mock")
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql://localhost:5432/sellerai_test",
    )
    os.environ.setdefault("OPENAI_API_KEY", "runtime-smoke-not-used")


def _poll_health_endpoint() -> None:
    url = f"http://{SMOKE_HOST}:{SMOKE_PORT}/health"
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status != 200:
                    last_error = f"HTTP_{response.status}"
                else:
                    payload = response.read(4096).decode("utf-8", errors="replace")
                    if '"healthy"' in payload or '"status"' in payload:
                        return
                    last_error = "HEALTH_PAYLOAD_INVALID"
        except urllib.error.URLError as exc:
            last_error = type(exc).__name__
        except Exception:
            last_error = "HEALTH_PROBE_FAILED"
        time.sleep(POLL_INTERVAL_SECONDS)
    raise AlpineHardenedSmokeError(f"UVICORN_HEALTH_TIMEOUT:{last_error or 'UNKNOWN'}")


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def validate_alpine_hardened_smoke() -> None:
    if os.getuid() == 0:
        raise AlpineHardenedSmokeError("RUNNING_AS_ROOT")

    _prepare_import_environment()

    from scripts.validate_backend_production_smoke import validate_backend_production_smoke
    from scripts.validate_backend_runtime_environment import validate_backend_runtime_environment

    validate_backend_production_smoke()
    validate_backend_runtime_environment(prepare_import_environment=_prepare_import_environment)

    from scripts.validate_backend_alpine_os_packages import validate_backend_alpine_os_packages

    validate_backend_alpine_os_packages()

    import app.main  # noqa: F401

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            SMOKE_HOST,
            "--port",
            str(SMOKE_PORT),
            "--workers",
            "1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        _poll_health_endpoint()
    finally:
        _terminate_process(process)

    if process.returncode not in (None, 0, -15):
        raise AlpineHardenedSmokeError("UVICORN_EXIT_NONZERO")


def main() -> int:
    try:
        validate_alpine_hardened_smoke()
    except AlpineHardenedSmokeError as exc:
        print(exc.reason_code, file=sys.stderr)
        return 1
    except Exception:
        print("ALPINE_HARDENED_SMOKE_VALIDATION_FAILED", file=sys.stderr)
        return 1
    print(SUCCESS_MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
