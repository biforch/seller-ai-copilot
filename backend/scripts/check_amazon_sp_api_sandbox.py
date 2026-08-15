"""Manual Amazon SP-API Sandbox safety check. Not collected by pytest.

Default mode is dry-run (no network). Live Sandbox requires explicit flags.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_backend_root_str = str(_BACKEND_ROOT)
if _backend_root_str not in sys.path:
    sys.path.insert(0, _backend_root_str)

# ruff: noqa: E402

from app.integrations.amazon.client import SpApiClient
from app.integrations.amazon.config import AmazonEndpointMode, AmazonSettings
from app.integrations.amazon.constants import (
    DEFAULT_LWA_TOKEN_URL,
    resolve_sp_api_base_url,
)
from app.integrations.amazon.exceptions import (
    AMAZON_RESPONSE_INVALID,
    AmazonError,
)
from app.integrations.amazon.lwa import CachingRefreshTokenProvider, LwaTokenClient
from app.integrations.amazon.sellers import (
    MARKETPLACE_PARTICIPATIONS_PATH,
    SellerMarketplaceParticipation,
    map_marketplace_participations,
)
from app.integrations.amazon.token_cache import InMemoryTokenCache
from app.integrations.amazon.transport import HttpTransport, HttpxTransport

CONFIRM_PHRASE = "LIVE_SANDBOX_ONLY"
SANDBOX_ACCOUNT_KEY = "sandbox-check"
SANDBOX_MARKETPLACE_PATH = MARKETPLACE_PARTICIPATIONS_PATH
SANDBOX_NA_HOST = "sandbox.sellingpartnerapi-na.amazon.com"
OFFICIAL_LWA_TOKEN_URL = DEFAULT_LWA_TOKEN_URL
ALLOWED_LWA_HOSTS = frozenset({"api.amazon.com"})
CANONICAL_ENV_RELATIVE = Path("backend") / ".env.amazon.sandbox"
GIT_COMMAND_TIMEOUT_SECONDS = 5
MAX_SANDBOX_ENV_BYTES = 16 * 1024
ENV_READ_CHUNK_SIZE = 512

REQUIRED_ENV_KEYS = (
    "AMAZON_SP_API_ENABLED",
    "AMAZON_SP_API_ENDPOINT_MODE",
    "AMAZON_SP_API_REGION",
    "AMAZON_LWA_CLIENT_ID",
    "AMAZON_LWA_CLIENT_SECRET",
    "AMAZON_SANDBOX_REFRESH_TOKEN",
    "AMAZON_LWA_TOKEN_URL",
    "AMAZON_SP_API_USER_AGENT",
)
ALLOWED_ENV_KEYS = frozenset(REQUIRED_ENV_KEYS)

PLACEHOLDER_MARKERS = (
    re.compile(r"^TEST_", re.IGNORECASE),
    re.compile(r"^REPLACE_", re.IGNORECASE),
    re.compile(r"placeholder", re.IGNORECASE),
    re.compile(r"change-me", re.IGNORECASE),
    re.compile(r"^your-", re.IGNORECASE),
    re.compile(r"<local value>", re.IGNORECASE),
)

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]


class SandboxCheckError(Exception):
    """Raised when a sandbox safety check fails before or during live execution."""

    def __init__(
        self,
        *,
        stage: str,
        error_code: str,
        message: str,
        http_status: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.error_code = error_code
        self.message = message
        self.http_status = http_status
        self.request_id = request_id


@dataclass(frozen=True)
class SandboxEnvConfig:
    lwa_client_id: str
    lwa_client_secret: str
    sandbox_refresh_token: str
    lwa_token_url: str
    user_agent: str


@dataclass(frozen=True)
class MarketplaceParticipationSummary:
    country_code: str
    marketplace_id: str
    is_participating: bool
    has_suspended_listings: bool


def _to_participation_summary(
    participation: SellerMarketplaceParticipation,
) -> MarketplaceParticipationSummary:
    return MarketplaceParticipationSummary(
        country_code=participation.country_code,
        marketplace_id=participation.marketplace_id,
        is_participating=participation.participating,
        has_suspended_listings=participation.suspended_listings,
    )


@dataclass(frozen=True)
class SandboxCheckSuccess:
    http_status: int
    request_id: str | None
    payload_type: str
    participation_count: int
    participations: tuple[MarketplaceParticipationSummary, ...]


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or SCRIPT_PATH).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").is_dir():
            return candidate
    raise SandboxCheckError(
        stage="config",
        error_code="SANDBOX_CONFIG_INVALID",
        message="Could not locate repository root",
    )


def resolve_canonical_env_path(repo_root: Path) -> Path:
    return (repo_root / CANONICAL_ENV_RELATIVE).resolve()


def _repo_relative_posix_path(path: Path, repo_root: Path) -> str:
    resolved = path.resolve()
    root = repo_root.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Env file must be located within the repository",
        ) from None


def _run_git_command(args: list[str], *, repo_root: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=GIT_COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Git is required for Sandbox env file safety checks",
        ) from None
    except subprocess.TimeoutExpired:
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Git safety check timed out",
        ) from None


def _git_tracked(relative_posix_path: str, repo_root: Path) -> bool:
    result = _run_git_command(["ls-files", "--error-unmatch", relative_posix_path], repo_root=repo_root)
    if result.returncode not in (0, 1):
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Git tracked-file check failed",
        )
    return result.returncode == 0


def _git_ignored(relative_posix_path: str, repo_root: Path) -> bool:
    result = _run_git_command(["check-ignore", "-q", relative_posix_path], repo_root=repo_root)
    if result.returncode not in (0, 1):
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Git ignore check failed",
        )
    return result.returncode == 0


def _open_env_file_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _strip_outer_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_dotenv_content(content: bytes) -> dict[str, str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Env file must be valid UTF-8",
        ) from None

    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            raise SandboxCheckError(
                stage="config",
                error_code="SANDBOX_CONFIG_INVALID",
                message="Env file contains an invalid entry",
            )
        key, _, raw_value = line.partition("=")
        key = key.strip()
        if not key:
            raise SandboxCheckError(
                stage="config",
                error_code="SANDBOX_CONFIG_INVALID",
                message="Env file contains an empty key",
            )
        if key in values:
            raise SandboxCheckError(
                stage="config",
                error_code="SANDBOX_CONFIG_INVALID",
                message="Env file contains duplicate keys",
            )
        if key not in ALLOWED_ENV_KEYS:
            raise SandboxCheckError(
                stage="config",
                error_code="SANDBOX_CONFIG_INVALID",
                message="Env file contains unsupported settings",
            )
        if "\n" in raw_value or "\r" in raw_value:
            raise SandboxCheckError(
                stage="config",
                error_code="SANDBOX_CONFIG_INVALID",
                message="Env file does not support multi-line values",
            )
        values[key] = _strip_outer_quotes(raw_value.strip())
    return values


def _is_placeholder(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return True
    return any(pattern.search(stripped) for pattern in PLACEHOLDER_MARKERS)


def validate_env_file_argument(env_file: Path, *, repo_root: Path) -> Path:
    canonical_literal = repo_root / CANONICAL_ENV_RELATIVE
    if canonical_literal.is_symlink():
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Env file must not be a symlink",
        )

    candidate = env_file.expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()

    canonical = canonical_literal.resolve()
    if candidate != canonical:
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Live Sandbox mode requires the canonical Sandbox env file",
        )
    return canonical


def _read_env_file_content(fd: int, file_stat: os.stat_result) -> bytes:
    file_size = file_stat.st_size
    if file_size <= 0:
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Env file must not be empty",
        )
    if file_size > MAX_SANDBOX_ENV_BYTES:
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Env file exceeds allowed size",
        )

    if hasattr(os, "getuid") and file_stat.st_uid != os.getuid():
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Env file must be owned by the current user",
        )

    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            chunk = os.read(fd, ENV_READ_CHUNK_SIZE)
        except OSError:
            raise SandboxCheckError(
                stage="config",
                error_code="SANDBOX_CONFIG_INVALID",
                message="Env file could not be read safely",
            ) from None
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_SANDBOX_ENV_BYTES:
            raise SandboxCheckError(
                stage="config",
                error_code="SANDBOX_CONFIG_INVALID",
                message="Env file exceeds allowed size",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def load_sandbox_env_file(env_file: Path, *, repo_root: Path) -> dict[str, str]:
    canonical = validate_env_file_argument(env_file, repo_root=repo_root)
    relative_path = _repo_relative_posix_path(canonical, repo_root)

    if _git_tracked(relative_path, repo_root):
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Env file must not be tracked by Git",
        )
    if not _git_ignored(relative_path, repo_root):
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Env file must be ignored by .gitignore",
        )

    try:
        fd = os.open(str(canonical), _open_env_file_flags())
    except OSError:
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Env file is missing or not a regular file",
        ) from None

    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise SandboxCheckError(
                stage="config",
                error_code="SANDBOX_CONFIG_INVALID",
                message="Env file must be a regular file",
            )
        if file_stat.st_mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH):
            raise SandboxCheckError(
                stage="config",
                error_code="SANDBOX_CONFIG_INVALID",
                message="Env file permissions must not allow group/other access",
            )
        content = _read_env_file_content(fd, file_stat)
    finally:
        os.close(fd)

    return parse_dotenv_content(content)


def validate_sandbox_env_values(env: dict[str, str]) -> SandboxEnvConfig:
    missing = [key for key in REQUIRED_ENV_KEYS if not env.get(key, "").strip()]
    if missing:
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Env file is missing required Amazon Sandbox settings",
        )

    enabled = env["AMAZON_SP_API_ENABLED"].strip().lower()
    endpoint_mode = env["AMAZON_SP_API_ENDPOINT_MODE"].strip().lower()
    region = env["AMAZON_SP_API_REGION"].strip().lower()
    lwa_token_url = env["AMAZON_LWA_TOKEN_URL"].strip()

    if enabled != "true":
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="AMAZON_SP_API_ENABLED must be true for Sandbox checks",
        )
    if endpoint_mode != "sandbox":
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Only sandbox endpoint mode is allowed for this script",
        )
    if region != "na":
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Only NA region is allowed for A2.1 Sandbox checks",
        )

    parsed_lwa = urlparse(lwa_token_url)
    if parsed_lwa.scheme != "https" or parsed_lwa.hostname not in ALLOWED_LWA_HOSTS:
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="AMAZON_LWA_TOKEN_URL must use the official Amazon LWA host",
        )
    if lwa_token_url.rstrip("/") != OFFICIAL_LWA_TOKEN_URL:
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Custom LWA hosts are not allowed for Sandbox checks",
        )

    expected_base = resolve_sp_api_base_url(region="na", endpoint_mode="sandbox")
    if expected_base != f"https://{SANDBOX_NA_HOST}":
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Sandbox NA endpoint mapping is invalid",
        )

    secret_fields = {
        "AMAZON_LWA_CLIENT_ID": env["AMAZON_LWA_CLIENT_ID"],
        "AMAZON_LWA_CLIENT_SECRET": env["AMAZON_LWA_CLIENT_SECRET"],
        "AMAZON_SANDBOX_REFRESH_TOKEN": env["AMAZON_SANDBOX_REFRESH_TOKEN"],
    }
    for field_name, value in secret_fields.items():
        if _is_placeholder(value):
            raise SandboxCheckError(
                stage="config",
                error_code="SANDBOX_CONFIG_INVALID",
                message=f"{field_name} must not use placeholder values",
            )

    user_agent = env["AMAZON_SP_API_USER_AGENT"].strip()
    if _is_placeholder(user_agent):
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="AMAZON_SP_API_USER_AGENT must not use placeholder values",
        )

    return SandboxEnvConfig(
        lwa_client_id=env["AMAZON_LWA_CLIENT_ID"].strip(),
        lwa_client_secret=env["AMAZON_LWA_CLIENT_SECRET"].strip(),
        sandbox_refresh_token=env["AMAZON_SANDBOX_REFRESH_TOKEN"].strip(),
        lwa_token_url=OFFICIAL_LWA_TOKEN_URL,
        user_agent=user_agent,
    )


def build_amazon_settings(config: SandboxEnvConfig) -> AmazonSettings:
    return AmazonSettings(
        enabled=True,
        lwa_client_id=config.lwa_client_id,
        lwa_client_secret=config.lwa_client_secret,
        lwa_token_url=config.lwa_token_url,
        sp_api_region="na",
        endpoint_mode=AmazonEndpointMode.SANDBOX,
        user_agent=config.user_agent,
        environment="development",
    )


def _response_invalid_sandbox_error(*, request_id: str | None = None) -> SandboxCheckError:
    return SandboxCheckError(
        stage="response",
        error_code=AMAZON_RESPONSE_INVALID,
        message="Marketplace participations payload failed schema validation",
        request_id=request_id,
    )


def validate_live_cli(*, live_sandbox: bool, confirm: str | None, env_file: Path | None) -> None:
    if not live_sandbox:
        return
    if confirm != CONFIRM_PHRASE:
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Live Sandbox mode requires explicit confirmation phrase",
        )
    if env_file is None:
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Live Sandbox mode requires --env-file",
        )


def print_safe_failure(error: SandboxCheckError | AmazonError, *, stage: str) -> None:
    if isinstance(error, SandboxCheckError):
        print(f"stage: {error.stage}")
        print(f"error_code: {error.error_code}")
        if error.http_status is not None:
            print(f"HTTP status: {error.http_status}")
        print(f"request_id: {error.request_id or '-'}")
        print(f"message: {error.message}")
        return

    print(f"stage: {stage}")
    print(f"error_code: {error.error_code}")
    if error.status_code is not None:
        print(f"HTTP status: {error.status_code}")
    print(f"request_id: {error.request_id or '-'}")
    print(f"message: {error.message}")


def print_safe_internal_failure() -> None:
    print("stage: internal")
    print("error_code: SANDBOX_CHECK_FAILED")
    print("message: Sandbox check failed safely")


def print_safe_success(result: SandboxCheckSuccess) -> None:
    print("Sandbox safety checks passed")
    print("LWA token exchange: succeeded")
    print("SP-API sandbox request: succeeded")
    print(f"HTTP status: {result.http_status}")
    print(f"request_id: {result.request_id or '-'}")
    print(f"payload_type: {result.payload_type}")
    print(f"marketplace_participations: {result.participation_count}")
    for item in result.participations:
        print(
            "  - "
            f"{item.country_code} ({item.marketplace_id}) "
            f"participating={item.is_participating} "
            f"suspended_listings={item.has_suspended_listings}"
        )


def _amazon_error_stage(error: AmazonError) -> str:
    if error.error_code.startswith("AMAZON_LWA"):
        return "lwa"
    if error.error_code == AMAZON_RESPONSE_INVALID:
        return "response"
    return "sp_api"


async def execute_sandbox_check(
    *,
    settings: AmazonSettings,
    refresh_token: str,
    transport: HttpTransport | None = None,
) -> SandboxCheckSuccess:
    if settings.endpoint_mode is not AmazonEndpointMode.SANDBOX:
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Only sandbox endpoint mode is allowed",
        )
    if settings.sp_api_region != "na":
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Only NA region is allowed",
        )

    base_url = resolve_sp_api_base_url(region="na", endpoint_mode="sandbox")
    if base_url != f"https://{SANDBOX_NA_HOST}":
        raise SandboxCheckError(
            stage="config",
            error_code="SANDBOX_CONFIG_INVALID",
            message="Sandbox endpoint must remain fixed to NA Sandbox host",
        )

    effective_transport = transport or HttpxTransport()
    lwa_client = LwaTokenClient(settings=settings, transport=effective_transport)

    async def refresh_resolver(_account_key: str) -> str:
        return refresh_token

    token_provider = CachingRefreshTokenProvider(
        client=lwa_client,
        cache=InMemoryTokenCache(),
        refresh_token_resolver=refresh_resolver,
    )
    sp_client = SpApiClient(
        settings=settings,
        transport=effective_transport,
        token_provider=token_provider,
    )

    response = await sp_client.request(
        "GET",
        SANDBOX_MARKETPLACE_PATH,
        account_key=SANDBOX_ACCOUNT_KEY,
    )
    request_id = response.headers.get("x-amzn-requestid")
    try:
        domain_participations = map_marketplace_participations(response.payload)
    except AmazonError as exc:
        if exc.error_code == AMAZON_RESPONSE_INVALID:
            raise _response_invalid_sandbox_error(request_id=request_id) from None
        raise

    participations = tuple(_to_participation_summary(item) for item in domain_participations)
    payload_type = type(response.payload).__name__
    return SandboxCheckSuccess(
        http_status=response.status_code,
        request_id=request_id,
        payload_type=payload_type,
        participation_count=len(participations),
        participations=participations,
    )


async def run_dry_run() -> int:
    print("Sandbox safety checks passed")
    print("mode: dry-run")
    print("network: disabled")
    return 0


async def run_live_sandbox(env_file: Path) -> int:
    repo_root = find_repo_root()
    env_values = load_sandbox_env_file(env_file, repo_root=repo_root)
    config = validate_sandbox_env_values(env_values)
    settings = build_amazon_settings(config)
    result = await execute_sandbox_check(
        settings=settings,
        refresh_token=config.sandbox_refresh_token,
    )
    print_safe_success(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Amazon SP-API Sandbox safety check (dry-run by default)",
    )
    parser.add_argument(
        "--live-sandbox",
        action="store_true",
        help="Enable live Sandbox requests (requires confirmation and env file)",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=f"Required confirmation phrase: {CONFIRM_PHRASE}",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Path to canonical Sandbox env file (backend/.env.amazon.sandbox)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        validate_live_cli(
            live_sandbox=args.live_sandbox,
            confirm=args.confirm,
            env_file=args.env_file,
        )
        if args.live_sandbox:
            if args.env_file is None:
                raise SandboxCheckError(
                    stage="config",
                    error_code="SANDBOX_CONFIG_INVALID",
                    message="Live Sandbox mode requires --env-file",
                )
            return asyncio.run(run_live_sandbox(args.env_file))
        return asyncio.run(run_dry_run())
    except SandboxCheckError as exc:
        print_safe_failure(exc, stage=exc.stage)
        return 1
    except AmazonError as exc:
        print_safe_failure(exc, stage=_amazon_error_stage(exc))
        return 1
    except Exception:
        print_safe_internal_failure()
        return 1


if __name__ == "__main__":
    sys.exit(main())
