import base64

import pytest
from cryptography.exceptions import InvalidTag

from app.services.mfa_service import MfaService

TEST_KEY = base64.b64encode(b"m" * 32).decode("ascii")


def test_totp_known_vector_and_window() -> None:
    service = MfaService(TEST_KEY)
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert service.matching_totp_counter(secret, "287082", now=59) == 1
    assert service.matching_totp_counter(secret, "287083", now=59) is None


def test_secret_envelope_is_bound_to_user_and_detects_tampering() -> None:
    service = MfaService(TEST_KEY)
    ciphertext = service.encrypt_secret("ABCDEF", user_id="user-1")
    assert ciphertext.startswith(b"MFA1")
    assert b"ABCDEF" not in ciphertext
    assert service.decrypt_secret(ciphertext, user_id="user-1") == "ABCDEF"
    with pytest.raises(InvalidTag):
        service.decrypt_secret(ciphertext, user_id="user-2")
    tampered = ciphertext[:-1] + bytes([ciphertext[-1] ^ 1])
    with pytest.raises(InvalidTag):
        service.decrypt_secret(tampered, user_id="user-1")


def test_secret_envelope_rejects_unknown_format() -> None:
    service = MfaService(TEST_KEY)
    with pytest.raises(ValueError, match="Unsupported MFA secret envelope"):
        service.decrypt_secret(b"legacy-value", user_id="user-1")


def test_recovery_codes_are_high_entropy_unique_and_keyed() -> None:
    service = MfaService(TEST_KEY)
    other = MfaService(base64.b64encode(b"n" * 32).decode("ascii"))
    codes = service.generate_recovery_codes()
    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(len(code) >= 24 for code in codes)
    assert service.hash_recovery_code(codes[0]) != other.hash_recovery_code(codes[0])
    candidate = service.hash_recovery_code(codes[0])
    assert service.find_recovery_hash(candidate, [candidate]) == candidate
    assert service.find_recovery_hash(service.hash_recovery_code("wrong"), [candidate]) is None


@pytest.mark.parametrize("count", [0, 21])
def test_recovery_code_count_is_bounded(count: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 20"):
        MfaService(TEST_KEY).generate_recovery_codes(count)
