from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from app.integrations.amazon.config import AmazonEndpointMode, AmazonSettings
from app.integrations.amazon.exceptions import (
    AMAZON_LWA_UNAVAILABLE,
    AMAZON_RESPONSE_INVALID,
    AMAZON_SP_API_FORBIDDEN,
    AMAZON_SP_API_RATE_LIMITED,
    AMAZON_SP_API_SERVER_ERROR,
    AMAZON_SP_API_UNAUTHORIZED,
    AmazonError,
)
from app.integrations.amazon.transport import HttpxTransport
from scripts import check_amazon_sp_api_sandbox as sandbox_script

FAKE_CLIENT_ID = "amzn1.application-oa2-client.fake-client-id"
FAKE_CLIENT_SECRET = "amzn1.oa2-cs.v1.fake|secret=part"
FAKE_REFRESH_TOKEN = "Atzr|fake|refresh=token"
FAKE_ACCESS_TOKEN = "Atza|fake-sandbox-access-token-value"
SENSITIVE_MARKERS = (
    FAKE_CLIENT_ID,
    FAKE_CLIENT_SECRET,
    FAKE_REFRESH_TOKEN,
    FAKE_ACCESS_TOKEN,
)


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


@pytest.fixture
def backend_dir(repo_root: Path) -> Path:
    return repo_root / "backend"


@pytest.fixture
def mini_repo(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    backend = tmp_path / "backend"
    backend.mkdir()
    env_path = backend / ".env.amazon.sandbox"
    return tmp_path, env_path


def _valid_env_lines(**overrides: str) -> dict[str, str]:
    values = {
        "AMAZON_SP_API_ENABLED": "true",
        "AMAZON_SP_API_ENDPOINT_MODE": "sandbox",
        "AMAZON_SP_API_REGION": "na",
        "AMAZON_LWA_CLIENT_ID": FAKE_CLIENT_ID,
        "AMAZON_LWA_CLIENT_SECRET": FAKE_CLIENT_SECRET,
        "AMAZON_SANDBOX_REFRESH_TOKEN": FAKE_REFRESH_TOKEN,
        "AMAZON_LWA_TOKEN_URL": "https://api.amazon.com/auth/o2/token",
        "AMAZON_SP_API_USER_AGENT": "SellerAI-Copilot/1.0.0 (Language=Python)",
    }
    values.update(overrides)
    return values


def _env_text(**overrides: str) -> str:
    return "\n".join(f"{key}={value}" for key, value in _valid_env_lines(**overrides).items()) + "\n"


def _write_env_file(path: Path, **overrides: str) -> None:
    path.write_text(_env_text(**overrides), encoding="utf-8")


def _patch_git_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox_script, "_git_tracked", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(sandbox_script, "_git_ignored", lambda *_args, **_kwargs: True)


def _sandbox_settings(**overrides: Any) -> AmazonSettings:
    defaults = {
        "enabled": True,
        "lwa_client_id": FAKE_CLIENT_ID,
        "lwa_client_secret": FAKE_CLIENT_SECRET,
        "lwa_token_url": "https://api.amazon.com/auth/o2/token",
        "sp_api_region": "na",
        "endpoint_mode": AmazonEndpointMode.SANDBOX,
        "user_agent": "SellerAI-Copilot/1.0.0 (Language=Python)",
        "environment": "development",
    }
    defaults.update(overrides)
    return AmazonSettings(**defaults)


def _participation_payload() -> dict[str, Any]:
    return {
        "payload": [
            {
                "marketplace": {
                    "id": "ATVPDKIKX0DER",
                    "countryCode": "US",
                    "name": "Amazon.com",
                    "defaultCurrencyCode": "USD",
                    "defaultLanguageCode": "en_US",
                    "domainName": "www.amazon.com",
                },
                "participation": {
                    "isParticipating": True,
                    "hasSuspendedListings": False,
                },
            }
        ]
    }


def _make_mock_transport(
    *,
    lwa_status: int = 200,
    sp_api_status: int = 200,
    sp_api_payload: Any | None = None,
    sp_api_body: bytes | None = None,
) -> HttpxTransport:
    payload = _participation_payload() if sp_api_payload is None else sp_api_payload
    request_urls: list[str] = []
    request_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_urls.append(str(request.url))
        request_paths.append(request.url.path)
        if "api.amazon.com" in str(request.url):
            return httpx.Response(
                lwa_status,
                json={
                    "access_token": FAKE_ACCESS_TOKEN,
                    "token_type": "bearer",
                    "expires_in": 3600,
                }
                if lwa_status == 200
                else {"error": "invalid_grant"},
            )
        if sp_api_body is not None:
            return httpx.Response(
                sp_api_status,
                content=sp_api_body,
                headers={"x-amzn-requestid": "mock-request-id"},
            )
        return httpx.Response(
            sp_api_status,
            json=payload,
            headers={"x-amzn-requestid": "mock-request-id"},
        )

    transport = HttpxTransport(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    transport._test_request_urls = request_urls  # type: ignore[attr-defined]
    transport._test_request_paths = request_paths  # type: ignore[attr-defined]
    return transport


def _combined_output(capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> str:
    captured = capsys.readouterr()
    return " ".join(
        [
            captured.out,
            captured.err,
            " ".join(record.message for record in caplog.records),
        ]
    )


def _assert_no_sensitive_leaks(text: str) -> None:
    for marker in SENSITIVE_MARKERS:
        assert marker not in text


def test_cli_dry_run_from_backend_directory(backend_dir: Path):
    result = subprocess.run(
        [sys.executable, "scripts/check_amazon_sp_api_sandbox.py"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0
    assert "dry-run" in result.stdout
    assert "network: disabled" in result.stdout
    assert "traceback" not in combined.lower()


def test_cli_dry_run_from_repository_root(repo_root: Path):
    result = subprocess.run(
        [sys.executable, "backend/scripts/check_amazon_sp_api_sandbox.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0
    assert "dry-run" in result.stdout
    assert "network: disabled" in result.stdout
    assert "traceback" not in combined.lower()


def test_backend_root_added_to_sys_path_before_app_import():
    source = (
        Path(__file__).resolve().parents[3] / "scripts" / "check_amazon_sp_api_sandbox.py"
    ).read_text(encoding="utf-8")
    app_import_index = source.index("from app.integrations.amazon.client")
    path_bootstrap_index = source.index("Path(__file__).resolve().parents[1]")
    assert path_bootstrap_index < app_import_index
    assert "parents[1]" in source


@pytest.mark.asyncio
async def test_run_dry_run_output(capsys):
    exit_code = await sandbox_script.run_dry_run()
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Sandbox safety checks passed" in captured.out
    assert "dry-run" in captured.out
    assert "network: disabled" in captured.out


def test_live_mode_requires_confirm_phrase():
    with pytest.raises(sandbox_script.SandboxCheckError, match="confirmation phrase"):
        sandbox_script.validate_live_cli(
            live_sandbox=True,
            confirm="WRONG",
            env_file=Path("backend/.env.amazon.sandbox"),
        )


def test_live_mode_requires_env_file():
    with pytest.raises(sandbox_script.SandboxCheckError, match="env-file"):
        sandbox_script.validate_live_cli(
            live_sandbox=True,
            confirm=sandbox_script.CONFIRM_PHRASE,
            env_file=None,
        )


def test_main_without_live_sandbox_never_reads_env_file():
    with patch("scripts.check_amazon_sp_api_sandbox.run_live_sandbox") as mock_live:
        exit_code = sandbox_script.main([])
    assert exit_code == 0
    mock_live.assert_not_called()


def test_main_live_without_confirm_exits_without_network():
    with patch("scripts.check_amazon_sp_api_sandbox.run_live_sandbox") as mock_live:
        exit_code = sandbox_script.main(
            ["--live-sandbox", "--env-file", "backend/.env.amazon.sandbox"]
        )
    assert exit_code == 1
    mock_live.assert_not_called()


def test_repo_relative_path_rejects_outside_repository(repo_root: Path, tmp_path: Path):
    outside = tmp_path / "outside.env"
    outside.write_text("x=1\n", encoding="utf-8")
    with pytest.raises(sandbox_script.SandboxCheckError, match="within the repository"):
        sandbox_script._repo_relative_posix_path(outside, repo_root)


def test_git_ignored_uses_repo_relative_path_for_canonical_env(repo_root: Path):
    relative = sandbox_script.CANONICAL_ENV_RELATIVE.as_posix()
    assert sandbox_script._git_ignored(relative, repo_root)


def test_git_tracked_check_rejects_unexpected_return_code(repo_root: Path):
    with patch.object(
        sandbox_script,
        "_run_git_command",
        return_value=subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr=""),
    ):
        with pytest.raises(sandbox_script.SandboxCheckError, match="tracked-file check failed"):
            sandbox_script._git_tracked("backend/.env.amazon.sandbox", repo_root)


def test_git_command_timeout_fails_safely(repo_root: Path):
    def raise_timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=["git"], timeout=1)

    with patch.object(sandbox_script.subprocess, "run", raise_timeout):
        with pytest.raises(sandbox_script.SandboxCheckError, match="timed out"):
            sandbox_script._run_git_command(
                ["check-ignore", "-q", "backend/.env.amazon.sandbox"],
                repo_root=repo_root,
            )


def test_git_command_missing_fails_safely(repo_root: Path):
    def raise_missing(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    with patch.object(sandbox_script.subprocess, "run", raise_missing):
        with pytest.raises(sandbox_script.SandboxCheckError, match="Git is required"):
            sandbox_script._run_git_command(
                ["check-ignore", "-q", "backend/.env.amazon.sandbox"],
                repo_root=repo_root,
            )


def test_validate_env_file_argument_requires_canonical_path(repo_root: Path, tmp_path: Path):
    other = tmp_path / "backend" / ".env.amazon.sandbox"
    other.parent.mkdir(parents=True)
    other.write_text("x=1\n", encoding="utf-8")
    with pytest.raises(sandbox_script.SandboxCheckError, match="canonical Sandbox env file"):
        sandbox_script.validate_env_file_argument(other, repo_root=repo_root)


def test_validate_env_file_argument_accepts_canonical_relative_path(
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.chdir(repo_root)
    canonical = sandbox_script.resolve_canonical_env_path(repo_root)
    assert sandbox_script.validate_env_file_argument(
        Path("backend/.env.amazon.sandbox"),
        repo_root=repo_root,
    ) == canonical


def test_load_sandbox_env_file_rejects_non_canonical_secure_file(
    mini_repo,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, env_path = mini_repo
    other = repo / "backend" / ".env"
    _write_env_file(other)
    os.chmod(other, stat.S_IRUSR | stat.S_IWUSR)
    _patch_git_checks(monkeypatch)
    with pytest.raises(sandbox_script.SandboxCheckError, match="canonical Sandbox env file"):
        sandbox_script.load_sandbox_env_file(other, repo_root=repo)


def test_load_sandbox_env_file_rejects_symlink(mini_repo, monkeypatch: pytest.MonkeyPatch):
    repo, env_path = mini_repo
    real_file = repo / "backend" / "real.env"
    _write_env_file(real_file)
    os.chmod(real_file, stat.S_IRUSR | stat.S_IWUSR)
    env_path.symlink_to(real_file)
    _patch_git_checks(monkeypatch)
    with pytest.raises(sandbox_script.SandboxCheckError, match="must not be a symlink"):
        sandbox_script.load_sandbox_env_file(env_path, repo_root=repo)


def test_load_sandbox_env_file_rejects_group_readable_permissions(
    mini_repo,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, env_path = mini_repo
    _write_env_file(env_path)
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    _patch_git_checks(monkeypatch)
    with pytest.raises(sandbox_script.SandboxCheckError, match="permissions"):
        sandbox_script.load_sandbox_env_file(env_path, repo_root=repo)


def test_load_sandbox_env_file_allows_owner_only_permissions(
    mini_repo,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, env_path = mini_repo
    _write_env_file(env_path)
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
    _patch_git_checks(monkeypatch)
    values = sandbox_script.load_sandbox_env_file(env_path, repo_root=repo)
    assert values["AMAZON_LWA_CLIENT_SECRET"] == FAKE_CLIENT_SECRET
    assert values["AMAZON_SANDBOX_REFRESH_TOKEN"] == FAKE_REFRESH_TOKEN


def test_load_sandbox_env_file_rejects_non_regular_file(
    mini_repo,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, env_path = mini_repo
    _write_env_file(env_path)
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
    _patch_git_checks(monkeypatch)

    with patch.object(sandbox_script.os, "fstat") as mock_fstat:
        mock_fstat.return_value = os.stat_result(
            (stat.S_IFIFO | stat.S_IRUSR, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        )
        with pytest.raises(sandbox_script.SandboxCheckError, match="regular file"):
            sandbox_script.load_sandbox_env_file(env_path, repo_root=repo)


def test_load_sandbox_env_file_closes_file_descriptor(
    mini_repo,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, env_path = mini_repo
    _write_env_file(env_path)
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
    _patch_git_checks(monkeypatch)
    closed: list[int] = []
    original_close = sandbox_script.os.close

    def track_close(fd: int) -> None:
        closed.append(fd)
        original_close(fd)

    with patch.object(sandbox_script.os, "close", side_effect=track_close):
        sandbox_script.load_sandbox_env_file(env_path, repo_root=repo)
    assert closed


def test_load_sandbox_env_file_rejects_empty_file(mini_repo, monkeypatch: pytest.MonkeyPatch):
    repo, env_path = mini_repo
    env_path.write_text("", encoding="utf-8")
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
    _patch_git_checks(monkeypatch)
    with pytest.raises(sandbox_script.SandboxCheckError, match="must not be empty"):
        sandbox_script.load_sandbox_env_file(env_path, repo_root=repo)


def test_load_sandbox_env_file_accepts_exactly_max_size_before_parse(
    mini_repo,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, env_path = mini_repo
    env_path.write_bytes(b"x" * sandbox_script.MAX_SANDBOX_ENV_BYTES)
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
    _patch_git_checks(monkeypatch)
    with pytest.raises(sandbox_script.SandboxCheckError, match="invalid entry"):
        sandbox_script.load_sandbox_env_file(env_path, repo_root=repo)


def test_load_sandbox_env_file_rejects_over_max_size(
    mini_repo,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
):
    repo, env_path = mini_repo
    env_path.write_bytes(b"x" * (sandbox_script.MAX_SANDBOX_ENV_BYTES + 1))
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
    _patch_git_checks(monkeypatch)
    with pytest.raises(sandbox_script.SandboxCheckError, match="exceeds allowed size"):
        sandbox_script.load_sandbox_env_file(env_path, repo_root=repo)
    output = capsys.readouterr().out
    assert "traceback" not in output.lower()
    _assert_no_sensitive_leaks(output)


def test_load_sandbox_env_file_joins_short_os_read_chunks(
    mini_repo,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, env_path = mini_repo
    _write_env_file(env_path)
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
    _patch_git_checks(monkeypatch)
    original_read = sandbox_script.os.read

    def short_read(fd: int, size: int) -> bytes:
        return original_read(fd, min(8, size))

    with patch.object(sandbox_script.os, "read", side_effect=short_read):
        values = sandbox_script.load_sandbox_env_file(env_path, repo_root=repo)
    assert values["AMAZON_LWA_CLIENT_SECRET"] == FAKE_CLIENT_SECRET


def test_load_sandbox_env_file_closes_fd_when_read_fails(
    mini_repo,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, env_path = mini_repo
    _write_env_file(env_path)
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
    _patch_git_checks(monkeypatch)
    closed: list[int] = []
    original_close = sandbox_script.os.close

    def track_close(fd: int) -> None:
        closed.append(fd)
        original_close(fd)

    def raise_read_error(_fd: int, _size: int) -> bytes:
        raise OSError("read failed")

    with (
        patch.object(sandbox_script.os, "read", side_effect=raise_read_error),
        patch.object(sandbox_script.os, "close", side_effect=track_close),
    ):
        with pytest.raises(sandbox_script.SandboxCheckError, match="could not be read safely"):
            sandbox_script.load_sandbox_env_file(env_path, repo_root=repo)
    assert closed


def test_load_sandbox_env_file_rejects_non_owner(
    mini_repo,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
):
    repo, env_path = mini_repo
    _write_env_file(env_path)
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
    _patch_git_checks(monkeypatch)
    real_fstat = sandbox_script.os.fstat
    current_uid = os.getuid() if hasattr(os, "getuid") else 1000

    def fake_fstat(fd: int) -> os.stat_result:
        original = real_fstat(fd)
        foreign_uid = current_uid + 1
        return os.stat_result(
            (
                original.st_mode,
                original.st_ino,
                original.st_dev,
                original.st_nlink,
                foreign_uid,
                original.st_gid,
                original.st_size,
                original.st_atime,
                original.st_mtime,
                original.st_ctime,
            )
        )

    with (
        patch.object(sandbox_script.os, "getuid", return_value=current_uid, create=True),
        patch.object(sandbox_script.os, "fstat", side_effect=fake_fstat),
    ):
        with pytest.raises(sandbox_script.SandboxCheckError, match="owned by the current user"):
            sandbox_script.load_sandbox_env_file(env_path, repo_root=repo)
    output = capsys.readouterr().out
    assert str(env_path) not in output
    assert "traceback" not in output.lower()


def test_load_sandbox_env_file_rejects_replaced_symlink_on_open(
    mini_repo,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, env_path = mini_repo
    _write_env_file(env_path)
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
    _patch_git_checks(monkeypatch)

    def failing_open(_path: str, _flags: int) -> int:
        raise OSError("symlink opened")

    with patch.object(sandbox_script.os, "open", side_effect=failing_open):
        with pytest.raises(sandbox_script.SandboxCheckError, match="missing or not a regular file"):
            sandbox_script.load_sandbox_env_file(env_path, repo_root=repo)


def test_parse_dotenv_content_rejects_invalid_utf8():
    with pytest.raises(sandbox_script.SandboxCheckError, match="UTF-8"):
        sandbox_script.parse_dotenv_content(b"\xff\xfe")


def test_parse_dotenv_content_rejects_line_without_equals():
    with pytest.raises(sandbox_script.SandboxCheckError, match="invalid entry"):
        sandbox_script.parse_dotenv_content(b"INVALID_LINE\n")


def test_parse_dotenv_content_rejects_empty_key():
    with pytest.raises(sandbox_script.SandboxCheckError, match="empty key"):
        sandbox_script.parse_dotenv_content(b"=value\n")


def test_parse_dotenv_content_rejects_duplicate_keys():
    content = b"AMAZON_SP_API_ENABLED=true\nAMAZON_SP_API_ENABLED=true\n"
    with pytest.raises(sandbox_script.SandboxCheckError, match="duplicate keys"):
        sandbox_script.parse_dotenv_content(content)


def test_parse_dotenv_content_rejects_unknown_keys():
    content = b"AMAZON_UNKNOWN=value\n"
    with pytest.raises(sandbox_script.SandboxCheckError, match="unsupported settings"):
        sandbox_script.parse_dotenv_content(content)


def test_parse_dotenv_content_preserves_pipe_and_equals_in_secrets():
    content = _env_text(
        AMAZON_LWA_CLIENT_SECRET=FAKE_CLIENT_SECRET,
        AMAZON_SANDBOX_REFRESH_TOKEN=FAKE_REFRESH_TOKEN,
    ).encode()
    values = sandbox_script.parse_dotenv_content(content)
    assert values["AMAZON_LWA_CLIENT_SECRET"] == FAKE_CLIENT_SECRET
    assert values["AMAZON_SANDBOX_REFRESH_TOKEN"] == FAKE_REFRESH_TOKEN


def test_parse_dotenv_content_strips_outer_quotes_only():
    content = b'AMAZON_SP_API_USER_AGENT="SellerAI-Copilot/1.0.0 (Language=Python)"\n'
    values = sandbox_script.parse_dotenv_content(content)
    assert values["AMAZON_SP_API_USER_AGENT"] == "SellerAI-Copilot/1.0.0 (Language=Python)"


@pytest.mark.parametrize(
    "missing_key",
    [
        "AMAZON_LWA_CLIENT_ID",
        "AMAZON_LWA_CLIENT_SECRET",
        "AMAZON_SANDBOX_REFRESH_TOKEN",
    ],
)
def test_validate_sandbox_env_values_rejects_missing_credentials(missing_key: str):
    env = _valid_env_lines()
    env[missing_key] = ""
    with pytest.raises(sandbox_script.SandboxCheckError, match="missing required"):
        sandbox_script.validate_sandbox_env_values(env)


@pytest.mark.parametrize(
    "field,value",
    [
        ("AMAZON_LWA_CLIENT_ID", "TEST_CLIENT_ID"),
        ("AMAZON_LWA_CLIENT_SECRET", "REPLACE_ME"),
        ("AMAZON_SANDBOX_REFRESH_TOKEN", "placeholder-token"),
    ],
)
def test_validate_sandbox_env_values_rejects_placeholders(field: str, value: str):
    env = _valid_env_lines(**{field: value})
    with pytest.raises(sandbox_script.SandboxCheckError, match="placeholder"):
        sandbox_script.validate_sandbox_env_values(env)


@pytest.mark.parametrize("endpoint_mode", ["production", "mock"])
def test_validate_sandbox_env_values_rejects_non_sandbox_mode(endpoint_mode: str):
    env = _valid_env_lines(AMAZON_SP_API_ENDPOINT_MODE=endpoint_mode)
    with pytest.raises(sandbox_script.SandboxCheckError, match="sandbox endpoint"):
        sandbox_script.validate_sandbox_env_values(env)


@pytest.mark.parametrize("region", ["eu", "fe"])
def test_validate_sandbox_env_values_rejects_non_na_region(region: str):
    env = _valid_env_lines(AMAZON_SP_API_REGION=region)
    with pytest.raises(sandbox_script.SandboxCheckError, match="NA region"):
        sandbox_script.validate_sandbox_env_values(env)


def test_validate_sandbox_env_values_rejects_custom_lwa_host():
    env = _valid_env_lines(AMAZON_LWA_TOKEN_URL="https://mock.lwa.local/auth/o2/token")
    with pytest.raises(sandbox_script.SandboxCheckError, match="official Amazon LWA host"):
        sandbox_script.validate_sandbox_env_values(env)


@pytest.mark.asyncio
async def test_execute_sandbox_check_uses_expected_lwa_form_and_single_sp_api_call():
    transport = _make_mock_transport()
    settings = _sandbox_settings()
    result = await sandbox_script.execute_sandbox_check(
        settings=settings,
        refresh_token=FAKE_REFRESH_TOKEN,
        transport=transport,
    )
    urls = transport._test_request_urls  # type: ignore[attr-defined]
    paths = transport._test_request_paths  # type: ignore[attr-defined]
    assert len(urls) == 2
    assert all("sandbox.sellingpartnerapi-na.amazon.com" in url for url in urls[1:])
    assert paths.count("/sellers/v1/marketplaceParticipations") == 1
    assert result.http_status == 200
    assert result.participation_count == 1


@pytest.mark.asyncio
async def test_execute_sandbox_check_validates_success_schema():
    transport = _make_mock_transport()
    settings = _sandbox_settings()
    result = await sandbox_script.execute_sandbox_check(
        settings=settings,
        refresh_token=FAKE_REFRESH_TOKEN,
        transport=transport,
    )
    assert result.payload_type == "dict"
    assert result.participations[0].country_code == "US"
    assert result.participations[0].marketplace_id == "ATVPDKIKX0DER"


MAPPER_CANARY = "SENSITIVE_RESPONSE_CANARY_7f3e"


@pytest.mark.asyncio
async def test_execute_sandbox_check_mapper_failure_does_not_leak_payload(
    caplog: pytest.LogCaptureFixture,
):
    transport = _make_mock_transport(
        sp_api_payload={
            "payload": [
                {
                    "marketplace": {
                        "id": "M1",
                        "countryCode": "US",
                        "name": MAPPER_CANARY,
                        "defaultCurrencyCode": "USD",
                        "defaultLanguageCode": "en_US",
                        "domainName": "www.amazon.com",
                    },
                    "participation": {
                        "isParticipating": MAPPER_CANARY,
                        "hasSuspendedListings": False,
                    },
                }
            ]
        }
    )
    settings = _sandbox_settings()
    with caplog.at_level("WARNING"):
        with pytest.raises(sandbox_script.SandboxCheckError) as exc_info:
            await sandbox_script.execute_sandbox_check(
                settings=settings,
                refresh_token=FAKE_REFRESH_TOKEN,
                transport=transport,
            )
    assert exc_info.value.stage == "response"
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID
    combined = " ".join(
        [
            str(exc_info.value),
            repr(exc_info.value),
            " ".join(record.message for record in caplog.records),
        ]
    )
    assert MAPPER_CANARY not in combined


@pytest.mark.asyncio
async def test_execute_sandbox_check_rejects_invalid_response_schema():
    transport = _make_mock_transport(sp_api_payload={"payload": [{"invalid": True}]})
    settings = _sandbox_settings()
    with pytest.raises(sandbox_script.SandboxCheckError) as exc_info:
        await sandbox_script.execute_sandbox_check(
            settings=settings,
            refresh_token=FAKE_REFRESH_TOKEN,
            transport=transport,
        )
    assert exc_info.value.stage == "response"
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lwa_status", "expected_code"),
    [(503, AMAZON_LWA_UNAVAILABLE), (401, "AMAZON_LWA_TOKEN_INVALID")],
)
async def test_execute_sandbox_check_maps_lwa_failures_safely(
    lwa_status: int,
    expected_code: str,
    capsys,
    caplog,
):
    transport = _make_mock_transport(lwa_status=lwa_status)
    settings = _sandbox_settings()
    with pytest.raises(AmazonError) as exc_info:
        await sandbox_script.execute_sandbox_check(
            settings=settings,
            refresh_token=FAKE_REFRESH_TOKEN,
            transport=transport,
        )
    assert exc_info.value.error_code == expected_code
    _assert_no_sensitive_leaks(_combined_output(capsys, caplog))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, AMAZON_SP_API_UNAUTHORIZED),
        (403, AMAZON_SP_API_FORBIDDEN),
        (429, AMAZON_SP_API_RATE_LIMITED),
        (500, AMAZON_SP_API_SERVER_ERROR),
    ],
)
async def test_execute_sandbox_check_maps_sp_api_failures_safely(
    status_code: int,
    expected_code: str,
    capsys,
    caplog,
):
    transport = _make_mock_transport(sp_api_status=status_code, sp_api_payload={"errors": []})
    settings = _sandbox_settings()
    with pytest.raises(AmazonError) as exc_info:
        await sandbox_script.execute_sandbox_check(
            settings=settings,
            refresh_token=FAKE_REFRESH_TOKEN,
            transport=transport,
        )
    assert exc_info.value.error_code == expected_code
    _assert_no_sensitive_leaks(_combined_output(capsys, caplog))


def test_main_live_failure_prints_safe_output_without_paths(capsys):
    exit_code = sandbox_script.main(
        [
            "--live-sandbox",
            "--confirm",
            sandbox_script.CONFIRM_PHRASE,
            "--env-file",
            "backend/.env.amazon.sandbox",
        ]
    )
    output = capsys.readouterr().out
    assert exit_code == 1
    assert output.startswith("stage: config")
    assert "traceback" not in output.lower()
    assert str(Path("/tmp")) not in output
    _assert_no_sensitive_leaks(output)


def test_main_unexpected_exception_prints_safe_internal_output(capsys):
    async def failing_dry_run() -> int:
        raise OSError("boom")

    with patch("scripts.check_amazon_sp_api_sandbox.run_dry_run", failing_dry_run):
        exit_code = sandbox_script.main([])
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "stage: internal" in output
    assert "error_code: SANDBOX_CHECK_FAILED" in output
    assert "Sandbox check failed safely" in output
    assert "traceback" not in output.lower()
    assert "boom" not in output
    _assert_no_sensitive_leaks(output)


def test_print_safe_success_whitelist(capsys):
    result = sandbox_script.SandboxCheckSuccess(
        http_status=200,
        request_id="req-123",
        payload_type="list",
        participation_count=1,
        participations=(
            sandbox_script.MarketplaceParticipationSummary(
                country_code="US",
                marketplace_id="ATVPDKIKX0DER",
                is_participating=True,
                has_suspended_listings=False,
            ),
        ),
    )
    sandbox_script.print_safe_success(result)
    output = capsys.readouterr().out
    assert "Sandbox safety checks passed" in output
    assert "LWA token exchange: succeeded" in output
    assert "SP-API sandbox request: succeeded" in output
    _assert_no_sensitive_leaks(output)


def test_script_source_has_no_production_endpoint_fallback():
    source = (
        Path(__file__).resolve().parents[3] / "scripts" / "check_amazon_sp_api_sandbox.py"
    ).read_text(encoding="utf-8")
    assert "SANDBOX_NA_HOST" in source
    assert "AmazonEndpointMode.PRODUCTION" not in source


def test_pytest_never_triggers_live_mode_by_default():
    with patch("scripts.check_amazon_sp_api_sandbox.run_live_sandbox") as mock_live:
        exit_code = sandbox_script.main([])
    assert exit_code == 0
    mock_live.assert_not_called()
