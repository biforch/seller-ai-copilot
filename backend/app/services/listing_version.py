"""Domain service for manual listing version imports."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import IDEMPOTENCY_CONFLICT, LISTING_NOT_FOUND, AppException
from app.models.listing_version import ListingVersion, ListingVersionSource
from app.models.product import Product
from app.schemas.listing import ListingSnapshot
from app.services.idempotency import canonical_request_hash, require_idempotency_key


@dataclass(frozen=True)
class ImportListingResult:
    version: ListingVersion
    replay: bool


def _import_request_hash(
    snapshot: ListingSnapshot,
    *,
    marketplace: str | None = None,
    language: str = "en-US",
    include_marketplace: bool = True,
) -> str:
    payload: dict[str, object] = {
        **snapshot.canonical_dict(),
        "language": language,
    }
    if include_marketplace and marketplace is not None:
        payload["marketplace"] = marketplace
    return canonical_request_hash(payload)


def import_api_request_hash(
    snapshot: ListingSnapshot,
    *,
    language: str = "en-US",
) -> str:
    """Hash for HTTP Import idempotency: client snapshot only (no derived marketplace)."""
    return _import_request_hash(
        snapshot,
        language=language,
        include_marketplace=False,
    )


def _lock_product_for_user(
    db: Session,
    product_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Product:
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.user_id == user_id)
        .with_for_update()
        .one_or_none()
    )
    if product is None:
        raise AppException(
            message="Product not found",
            code=status.HTTP_404_NOT_FOUND,
        )
    return product


def _find_idempotent_version(
    db: Session,
    product_id: uuid.UUID,
    idempotency_key: str,
) -> ListingVersion | None:
    return (
        db.query(ListingVersion)
        .filter(
            ListingVersion.product_id == product_id,
            ListingVersion.operation_idempotency_key == idempotency_key,
        )
        .one_or_none()
    )


def _finalize_import_replay(db: Session, version: ListingVersion) -> ImportListingResult:
    db.commit()
    db.refresh(version)
    return ImportListingResult(version=version, replay=True)


def _resolve_idempotency_conflict(
    db: Session,
    product_id: uuid.UUID,
    idempotency_key: str,
    request_hash: str,
) -> ImportListingResult:
    existing = _find_idempotent_version(db, product_id, idempotency_key)
    if existing is None:
        raise AppException(
            message="Idempotency conflict",
            code=status.HTTP_409_CONFLICT,
            error_code=IDEMPOTENCY_CONFLICT,
        )
    if existing.request_hash == request_hash:
        return _finalize_import_replay(db, existing)
    raise AppException(
        message="Idempotency conflict",
        code=status.HTTP_409_CONFLICT,
        error_code=IDEMPOTENCY_CONFLICT,
    )


def set_product_current_listing_version(
    product: Product,
    version: ListingVersion,
) -> None:
    if version.product_id != product.id:
        raise AppException(
            message="Version does not belong to product",
            code=status.HTTP_400_BAD_REQUEST,
        )
    product.current_listing_version_id = uuid.UUID(str(version.id))  # type: ignore[assignment]


def _get_owned_product(
    db: Session,
    product_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Product | None:
    return (
        db.query(Product)
        .filter(Product.id == product_id, Product.user_id == user_id)
        .one_or_none()
    )


def get_current_listing_version(
    db: Session,
    *,
    product_id: uuid.UUID,
    current_user_id: uuid.UUID,
) -> tuple[Product, ListingVersion]:
    """Return the product and its current listing version for an owned product."""
    product = _get_owned_product(db, product_id, current_user_id)
    if product is None:
        raise AppException(
            message="Product not found",
            code=status.HTTP_404_NOT_FOUND,
        )
    if product.current_listing_version_id is None:
        raise AppException(
            message="Current listing not found",
            code=status.HTTP_404_NOT_FOUND,
            error_code=LISTING_NOT_FOUND,
        )
    version = (
        db.query(ListingVersion)
        .filter(
            ListingVersion.id == product.current_listing_version_id,
            ListingVersion.product_id == product_id,
        )
        .one_or_none()
    )
    if version is None:
        raise AppException(
            message="Current listing not found",
            code=status.HTTP_404_NOT_FOUND,
            error_code=LISTING_NOT_FOUND,
        )
    return product, version


def list_listing_versions(
    db: Session,
    *,
    product_id: uuid.UUID,
    current_user_id: uuid.UUID,
    page: int,
    page_size: int,
) -> tuple[Product, list[ListingVersion], int]:
    """List listing versions for an owned product with fixed stable ordering."""
    product = _get_owned_product(db, product_id, current_user_id)
    if product is None:
        raise AppException(
            message="Product not found",
            code=status.HTTP_404_NOT_FOUND,
        )

    total = (
        db.query(func.count(ListingVersion.id))
        .filter(ListingVersion.product_id == product_id)
        .scalar()
        or 0
    )
    items = (
        db.query(ListingVersion)
        .filter(ListingVersion.product_id == product_id)
        .order_by(ListingVersion.version_number.desc(), ListingVersion.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return product, items, total


def import_listing_version(
    db: Session,
    *,
    product_id: uuid.UUID,
    current_user_id: uuid.UUID,
    snapshot: ListingSnapshot,
    idempotency_key: str,
    marketplace: str | None = None,
    language: str = "en-US",
    request_hash: str | None = None,
) -> ImportListingResult:
    """Import a manual listing version with idempotent replay semantics."""
    normalized_key = require_idempotency_key(idempotency_key)

    product = _lock_product_for_user(db, product_id, current_user_id)
    resolved_marketplace = marketplace if marketplace is not None else str(product.platform)
    resolved_request_hash = request_hash
    if resolved_request_hash is None:
        resolved_request_hash = _import_request_hash(
            snapshot,
            marketplace=resolved_marketplace,
            language=language,
            include_marketplace=True,
        )

    existing = _find_idempotent_version(db, product_id, normalized_key)
    if existing is not None:
        if existing.request_hash == resolved_request_hash:
            return _finalize_import_replay(db, existing)
        raise AppException(
            message="Idempotency conflict",
            code=status.HTTP_409_CONFLICT,
            error_code=IDEMPOTENCY_CONFLICT,
        )

    next_version_number = (
        db.query(func.coalesce(func.max(ListingVersion.version_number), 0))
        .filter(ListingVersion.product_id == product_id)
        .scalar()
        or 0
    ) + 1

    savepoint = db.begin_nested()
    try:
        version = ListingVersion(
            product_id=product_id,
            version_number=next_version_number,
            source=ListingVersionSource.MANUAL,
            title=snapshot.title,
            bullets=snapshot.bullets,
            description=snapshot.description,
            backend_keywords=snapshot.backend_keywords,
            marketplace=resolved_marketplace,
            language=language,
            parent_version_id=product.current_listing_version_id,
            operation_idempotency_key=normalized_key,
            request_hash=resolved_request_hash,
            created_by=current_user_id,
        )
        db.add(version)
        db.flush()
        set_product_current_listing_version(product, version)
        db.flush()
    except IntegrityError:
        savepoint.rollback()
        return _resolve_idempotency_conflict(
            db,
            product_id,
            normalized_key,
            resolved_request_hash,
        )

    db.commit()
    db.refresh(version)
    return ImportListingResult(version=version, replay=False)
