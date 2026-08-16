"""Tenant-scoped read-only Amazon marketplace participation access."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation
from app.services.amazon_account_read_service import AmazonAccountReadService


@dataclass(frozen=True)
class AmazonMarketplaceParticipationSummary:
    marketplace_id: str
    marketplace_name: str
    country_code: str
    default_currency_code: str | None
    default_language_code: str | None
    domain_name: str | None
    participating: bool
    suspended_listings: bool
    is_active: bool
    sync_eligible: bool
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class AmazonMarketplaceReadService(AmazonAccountReadService):
    """Read marketplace snapshots without token or network dependencies."""

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def list_marketplaces_for_user(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> list[AmazonMarketplaceParticipationSummary]:
        # Preserve tenant-safe not-found behavior before returning an empty list.
        self.get_account_for_user(user_id=user_id, account_id=account_id)
        rows = (
            self._db.query(AmazonMarketplaceParticipation)
            .filter(AmazonMarketplaceParticipation.amazon_account_id == account_id)
            .order_by(
                AmazonMarketplaceParticipation.country_code.asc(),
                AmazonMarketplaceParticipation.marketplace_id.asc(),
            )
            .all()
        )
        return [
            AmazonMarketplaceParticipationSummary(
                marketplace_id=row.marketplace_id,
                marketplace_name=row.marketplace_name,
                country_code=row.country_code,
                default_currency_code=row.default_currency_code,
                default_language_code=row.default_language_code,
                domain_name=row.domain_name,
                participating=row.participating,
                suspended_listings=row.suspended_listings,
                is_active=row.is_active,
                sync_eligible=row.is_active and row.sync_eligible,
                last_seen_at=row.last_seen_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]
