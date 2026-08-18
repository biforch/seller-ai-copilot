"""Credential-free production runtime smoke checks for backend container images."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SUCCESS_MESSAGE = "backend production smoke validation passed"

CANARY_HS256_SECRET = "runtime-smoke-canary-secret"
CANARY_JWT_SUBJECT = "runtime-smoke-subject"
CANARY_AES_KEY = b"01234567890123456789012345678901"


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


def validate_backend_production_smoke() -> None:
    _prepare_import_environment()

    import psycopg2  # noqa: F401
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    aesgcm = AESGCM(CANARY_AES_KEY)
    nonce = b"012345678901"
    ciphertext = aesgcm.encrypt(nonce, b"smoke", None)
    if aesgcm.decrypt(nonce, ciphertext, None) != b"smoke":
        raise RuntimeError("CRYPTO_SMOKE_FAILED")

    from jose import jwt

    token = jwt.encode({"sub": CANARY_JWT_SUBJECT}, CANARY_HS256_SECRET, algorithm="HS256")
    claims = jwt.decode(token, CANARY_HS256_SECRET, algorithms=["HS256"])
    if claims.get("sub") != CANARY_JWT_SUBJECT:
        raise RuntimeError("JOSE_SMOKE_FAILED")

    from alembic.config import Config

    config = Config("alembic.ini")
    if not config.get_main_option("script_location"):
        raise RuntimeError("ALEMBIC_CONFIG_INVALID")


def main() -> int:
    try:
        validate_backend_production_smoke()
    except Exception:
        print("PRODUCTION_SMOKE_VALIDATION_FAILED", file=sys.stderr)
        return 1
    print(SUCCESS_MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
