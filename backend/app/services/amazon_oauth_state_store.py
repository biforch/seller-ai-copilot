"""PostgreSQL-backed OAuth state issuance and single-use consumption."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.amazon.exceptions import (
    amazon_account_not_found_error,
    amazon_oauth_intent_invalid_error,
    amazon_oauth_state_expired_error,
    amazon_oauth_state_invalid_error,
    amazon_oauth_state_replay_error,
    amazon_oauth_user_not_found_error,
)
from app.integrations.amazon.oauth_urls import (
    MARKETPLACE_TO_REGION,
    normalize_oauth_marketplace_code,
    validate_oauth_state_token,
)
from app.models.amazon_account import AmazonAccount
from app.models.amazon_oauth_state import (
    STATE_TOKEN_HASH_UNIQUE_CONSTRAINT,
    AmazonOAuthState,
    OAuthStateIntent,
    OAuthStateStatus,
)
from app.models.user import User

MAX_STATE_HASH_COLLISION_RETRIES = 3

TokenGenerator = Callable[[], str]
Clock = Callable[[], datetime]


def _default_token_generator() -> str:
    return secrets.token_urlsafe(32)


def hash_oauth_state_token(raw_state: str) -> str:
    return hashlib.sha256(raw_state.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OAuthStateIssue:
    raw_state_token: str = field(repr=False)
    expires_at: datetime
    marketplace_code: str
    region: str
    intent: str
    target_account_id: uuid.UUID | None


@dataclass(frozen=True)
class ConsumedOAuthState:
    state_id: uuid.UUID
    user_id: uuid.UUID
    marketplace_code: str
    region: str
    intent: str
    target_account_id: uuid.UUID | None
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime


class AmazonOAuthStateStore:
    def __init__(
        self,
        db: Session,
        *,
        ttl_seconds: int,
        clock: Clock | None = None,
        token_generator: TokenGenerator | None = None,
    ) -> None:
        if ttl_seconds < 300 or ttl_seconds > 900:
            raise ValueError("OAuth state TTL must be between 300 and 900 seconds")
        self._db = db
        self._ttl_seconds = ttl_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._token_generator = token_generator or _default_token_generator

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=UTC)
        return now

    @staticmethod
    def _is_state_hash_unique_violation(exc: IntegrityError) -> bool:
        orig = exc.orig
        if orig is None:
            return STATE_TOKEN_HASH_UNIQUE_CONSTRAINT in str(exc)
        diag = getattr(orig, "diag", None)
        constraint_name = getattr(diag, "constraint_name", None) if diag is not None else None
        if constraint_name == STATE_TOKEN_HASH_UNIQUE_CONSTRAINT:
            return True
        return STATE_TOKEN_HASH_UNIQUE_CONSTRAINT in str(orig)

    @staticmethod
    def _validate_intent(*, intent: str, target_account_id: uuid.UUID | None) -> str:
        normalized = intent.strip().lower()
        if normalized not in OAuthStateIntent.ALL:
            raise amazon_oauth_intent_invalid_error()
        if normalized == OAuthStateIntent.CONNECT and target_account_id is not None:
            raise amazon_oauth_intent_invalid_error()
        if normalized == OAuthStateIntent.REAUTHORIZE and target_account_id is None:
            raise amazon_oauth_intent_invalid_error()
        return normalized

    def _resolve_reauthorize_account(
        self,
        *,
        user_id: uuid.UUID,
        target_account_id: uuid.UUID,
    ) -> None:
        account = (
            self._db.query(AmazonAccount)
            .filter(
                AmazonAccount.id == target_account_id,
                AmazonAccount.user_id == user_id,
            )
            .one_or_none()
        )
        if account is None:
            raise amazon_account_not_found_error()

    def create_state(
        self,
        *,
        user_id: uuid.UUID,
        marketplace_code: str,
        intent: str,
        target_account_id: uuid.UUID | None = None,
    ) -> OAuthStateIssue:
        user = self._db.get(User, user_id)
        if user is None:
            raise amazon_oauth_user_not_found_error()

        normalized_marketplace = normalize_oauth_marketplace_code(marketplace_code)
        region = MARKETPLACE_TO_REGION[normalized_marketplace]
        normalized_intent = self._validate_intent(
            intent=intent,
            target_account_id=target_account_id,
        )
        if normalized_intent == OAuthStateIntent.REAUTHORIZE:
            assert target_account_id is not None
            self._resolve_reauthorize_account(
                user_id=user_id,
                target_account_id=target_account_id,
            )

        now = self._now()
        expires_at = now + timedelta(seconds=self._ttl_seconds)

        for _attempt in range(MAX_STATE_HASH_COLLISION_RETRIES):
            raw_state = self._token_generator()
            validate_oauth_state_token(raw_state)
            state_hash = hash_oauth_state_token(raw_state)
            savepoint = self._db.begin_nested()
            try:
                row = AmazonOAuthState(
                    state_token_hash=state_hash,
                    user_id=user_id,
                    marketplace_code=normalized_marketplace,
                    region=region,
                    intent=normalized_intent,
                    target_account_id=target_account_id,
                    status=OAuthStateStatus.PENDING,
                    created_at=now,
                    expires_at=expires_at,
                )
                self._db.add(row)
                self._db.flush()
            except IntegrityError as exc:
                savepoint.rollback()
                if self._is_state_hash_unique_violation(exc):
                    continue
                raise
            else:
                return OAuthStateIssue(
                    raw_state_token=raw_state,
                    expires_at=expires_at,
                    marketplace_code=normalized_marketplace,
                    region=region,
                    intent=normalized_intent,
                    target_account_id=target_account_id,
                )

        raise amazon_oauth_state_invalid_error()

    def consume_state(self, raw_state: str) -> ConsumedOAuthState:
        validated_state = validate_oauth_state_token(raw_state)
        state_hash = hash_oauth_state_token(validated_state)
        now = self._now()

        update_stmt = (
            update(AmazonOAuthState)
            .where(
                AmazonOAuthState.state_token_hash == state_hash,
                AmazonOAuthState.status == OAuthStateStatus.PENDING,
                AmazonOAuthState.expires_at > now,
            )
            .values(
                status=OAuthStateStatus.CONSUMED,
                consumed_at=now,
            )
            .returning(AmazonOAuthState)
        )
        row = self._db.execute(update_stmt).scalars().one_or_none()
        if row is not None:
            consumed_at = row.consumed_at
            if consumed_at is None:
                raise amazon_oauth_state_invalid_error()
            return ConsumedOAuthState(
                state_id=row.id,
                user_id=row.user_id,
                marketplace_code=row.marketplace_code,
                region=row.region,
                intent=row.intent,
                target_account_id=row.target_account_id,
                created_at=row.created_at,
                expires_at=row.expires_at,
                consumed_at=consumed_at,
            )

        existing = (
            self._db.query(AmazonOAuthState)
            .filter(AmazonOAuthState.state_token_hash == state_hash)
            .one_or_none()
        )
        if existing is None:
            raise amazon_oauth_state_invalid_error()
        if existing.status == OAuthStateStatus.CONSUMED:
            raise amazon_oauth_state_replay_error()
        if existing.expires_at <= now:
            raise amazon_oauth_state_expired_error()
        raise amazon_oauth_state_invalid_error()
