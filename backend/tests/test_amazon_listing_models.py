from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.amazon import listings_items as listings_items_module
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus, new_account_key
from app.models.amazon_listing import AmazonListing, _empty_status_codes
from app.models.product import Product
from app.models.project import Project

FAKE_SELLING_PARTNER_ID = "FAKESELLER1234"


def _encrypt_stub() -> tuple[bytes, str]:
    return secrets.token_bytes(48), secrets.token_hex(32)


def _make_account(
    user_id: uuid.UUID,
    *,
    selling_partner_id: str | None = None,
) -> AmazonAccount:
    ciphertext, fingerprint = _encrypt_stub()
    return AmazonAccount(
        user_id=user_id,
        account_key=new_account_key(),
        region="na",
        endpoint_mode="sandbox",
        status=AmazonAccountStatus.ACTIVE,
        refresh_token_ciphertext=ciphertext,
        refresh_token_key_version=1,
        refresh_token_fingerprint=fingerprint,
        selling_partner_id=selling_partner_id,
    )


def _make_listing(
    *,
    amazon_account_id: uuid.UUID,
    marketplace_id: str = "ATVPDKIKX0DER",
    seller_sku: str = "SKU-001",
    asin: str | None = "B012345678",
    product_id: uuid.UUID | None = None,
) -> AmazonListing:
    now = datetime.now(UTC)
    return AmazonListing(
        amazon_account_id=amazon_account_id,
        marketplace_id=marketplace_id,
        seller_sku=seller_sku,
        asin=asin,
        product_id=product_id,
        status_codes=["BUYABLE"],
        product_type="PRODUCT",
        upstream_created_at=now,
        upstream_last_updated_at=now,
        first_seen_at=now,
        last_seen_at=now,
    )


def test_different_accounts_same_marketplace_and_sku_allowed(
    db_session: Session,
    user_factory,
) -> None:
    user_a = user_factory("listing-user-a@example.com")
    user_b = user_factory("listing-user-b@example.com")
    account_a = _make_account(user_a.id)
    account_b = _make_account(user_b.id)
    db_session.add_all([account_a, account_b])
    db_session.flush()

    db_session.add_all(
        [
            _make_listing(amazon_account_id=account_a.id, seller_sku="SHARED-SKU"),
            _make_listing(amazon_account_id=account_b.id, seller_sku="SHARED-SKU"),
        ]
    )
    db_session.commit()


def test_same_account_marketplace_sku_duplicate_rejected(
    db_session: Session,
    user_factory,
) -> None:
    user = user_factory("listing-dup@example.com")
    account = _make_account(user.id)
    db_session.add(account)
    db_session.flush()

    db_session.add(_make_listing(amazon_account_id=account.id, seller_sku="DUP-SKU"))
    db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.add(_make_listing(amazon_account_id=account.id, seller_sku="DUP-SKU"))
        db_session.flush()


def test_same_account_same_sku_different_marketplace_allowed(
    db_session: Session,
    user_factory,
) -> None:
    user = user_factory("listing-marketplace@example.com")
    account = _make_account(user.id)
    db_session.add(account)
    db_session.flush()

    db_session.add_all(
        [
            _make_listing(
                amazon_account_id=account.id,
                marketplace_id="ATVPDKIKX0DER",
                seller_sku="SKU-MULTI",
            ),
            _make_listing(
                amazon_account_id=account.id,
                marketplace_id="A2EUQ1WTGCTBG2",
                seller_sku="SKU-MULTI",
            ),
        ]
    )
    db_session.commit()


def test_asin_repeatable_across_accounts_and_marketplaces(
    db_session: Session,
    user_factory,
) -> None:
    user_a = user_factory("listing-asin-a@example.com")
    user_b = user_factory("listing-asin-b@example.com")
    account_a = _make_account(user_a.id)
    account_b = _make_account(user_b.id)
    db_session.add_all([account_a, account_b])
    db_session.flush()

    shared_asin = "B099999999"
    db_session.add_all(
        [
            _make_listing(
                amazon_account_id=account_a.id,
                marketplace_id="ATVPDKIKX0DER",
                seller_sku="SKU-A",
                asin=shared_asin,
            ),
            _make_listing(
                amazon_account_id=account_b.id,
                marketplace_id="ATVPDKIKX0DER",
                seller_sku="SKU-B",
                asin=shared_asin,
            ),
            _make_listing(
                amazon_account_id=account_a.id,
                marketplace_id="A2EUQ1WTGCTBG2",
                seller_sku="SKU-C",
                asin=shared_asin,
            ),
        ]
    )
    db_session.commit()


def test_asin_nullable(db_session: Session, user_factory) -> None:
    user = user_factory("listing-asin-null@example.com")
    account = _make_account(user.id)
    db_session.add(account)
    db_session.flush()

    listing = _make_listing(amazon_account_id=account.id, asin=None)
    db_session.add(listing)
    db_session.commit()
    assert listing.asin is None


def test_product_id_nullable(db_session: Session, user_factory) -> None:
    user = user_factory("listing-product-null@example.com")
    account = _make_account(user.id)
    db_session.add(account)
    db_session.flush()

    listing = _make_listing(amazon_account_id=account.id, product_id=None)
    db_session.add(listing)
    db_session.commit()
    assert listing.product_id is None


def test_product_delete_sets_listing_product_id_null(
    db_session: Session,
    user_factory,
) -> None:
    user = user_factory("listing-product-delete@example.com")
    project = Project(user_id=user.id, name="Listing Project")
    db_session.add(project)
    db_session.flush()
    product = Product(user_id=user.id, project_id=project.id, name="Widget")
    account = _make_account(user.id)
    db_session.add_all([project, product, account])
    db_session.flush()

    listing = _make_listing(amazon_account_id=account.id, product_id=product.id)
    db_session.add(listing)
    db_session.commit()

    listing_id = listing.id
    db_session.delete(product)
    db_session.commit()

    refreshed = db_session.get(AmazonListing, listing_id)
    assert refreshed is not None
    assert refreshed.product_id is None


def test_account_delete_cascades_listings(db_session: Session, user_factory) -> None:
    user = user_factory("listing-account-cascade@example.com")
    account = _make_account(user.id)
    db_session.add(account)
    db_session.flush()

    listing = _make_listing(amazon_account_id=account.id)
    db_session.add(listing)
    db_session.commit()

    listing_id = listing.id
    db_session.delete(account)
    db_session.commit()
    assert db_session.get(AmazonListing, listing_id) is None


def test_status_codes_default_not_shared_between_instances() -> None:
    first = _empty_status_codes()
    second = _empty_status_codes()
    assert first == []
    assert second == []
    assert first is not second
    first.append("BUYABLE")
    assert second == []


def test_status_codes_orm_default_not_shared(db_session: Session, user_factory) -> None:
    user = user_factory("listing-status-default@example.com")
    account = _make_account(user.id)
    db_session.add(account)
    db_session.flush()

    first = AmazonListing(
        amazon_account_id=account.id,
        marketplace_id="ATVPDKIKX0DER",
        seller_sku="SKU-DEFAULT-1",
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    second = AmazonListing(
        amazon_account_id=account.id,
        marketplace_id="ATVPDKIKX0DER",
        seller_sku="SKU-DEFAULT-2",
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    db_session.add_all([first, second])
    db_session.flush()
    assert first.status_codes == []
    assert second.status_codes == []
    first.status_codes.append("DISCOVERABLE")
    db_session.flush()
    db_session.refresh(second)
    assert second.status_codes == []


def test_amazon_listing_repr_excludes_status_payload(db_session: Session, user_factory) -> None:
    user = user_factory("listing-repr@example.com")
    account = _make_account(user.id)
    db_session.add(account)
    db_session.flush()

    listing = _make_listing(amazon_account_id=account.id, seller_sku="REPR-SKU")
    listing.status_codes = ["BUYABLE", "DISCOVERABLE"]
    db_session.add(listing)
    db_session.commit()

    rendered = repr(listing)
    assert "REPR-SKU" in rendered
    assert "BUYABLE" not in rendered
    assert "DISCOVERABLE" not in rendered
    assert "status_codes" not in rendered


def test_amazon_account_listing_relationship(db_session: Session, user_factory) -> None:
    user = user_factory("listing-rel@example.com")
    account = _make_account(user.id)
    db_session.add(account)
    db_session.flush()

    listing = _make_listing(amazon_account_id=account.id)
    db_session.add(listing)
    db_session.commit()

    db_session.refresh(account)
    assert len(account.amazon_listings) == 1
    assert account.amazon_listings[0].id == listing.id


def test_selling_partner_id_nullable_on_existing_account_pattern(
    db_session: Session,
    user_factory,
) -> None:
    user = user_factory("account-spid-null@example.com")
    account = _make_account(user.id, selling_partner_id=None)
    db_session.add(account)
    db_session.commit()
    assert account.selling_partner_id is None


def test_timestamps_are_timezone_aware(db_session: Session, user_factory) -> None:
    user = user_factory("listing-tz@example.com")
    account = _make_account(user.id)
    db_session.add(account)
    db_session.flush()

    listing = _make_listing(amazon_account_id=account.id)
    db_session.add(listing)
    db_session.commit()

    assert listing.first_seen_at.tzinfo is not None
    assert listing.last_seen_at.tzinfo is not None
    assert listing.created_at.tzinfo is not None
    assert listing.updated_at.tzinfo is not None


def test_cross_layer_length_constants_locked() -> None:
    from app.models import amazon_listing as amazon_listing_module

    assert amazon_listing_module.SELLER_SKU_MAX_LENGTH == listings_items_module.SELLER_SKU_MAX_LENGTH
    assert amazon_listing_module.ASIN_MAX_LENGTH == listings_items_module.ASIN_MAX_LENGTH


def test_amazon_listing_metadata_indexes_match_migration() -> None:
    table = AmazonListing.__table__
    index_names = {index.name for index in table.indexes}
    expected = {
        "ix_amazon_listings_account_marketplace_updated",
        "ix_amazon_listings_product_id",
        "ix_amazon_listings_account_marketplace_last_seen_sync",
        "ix_amazon_listings_asin",
    }
    assert expected.issubset(index_names)

    updated_index = next(
        index for index in table.indexes if index.name == "ix_amazon_listings_account_marketplace_updated"
    )
    assert [column.name for column in updated_index.columns] == [
        "amazon_account_id",
        "marketplace_id",
        "updated_at",
        "id",
    ]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        pytest.param("marketplace_id", "", id="marketplace_empty"),
        pytest.param("marketplace_id", "   ", id="marketplace_whitespace"),
        pytest.param("seller_sku", "", id="seller_sku_empty"),
        pytest.param("seller_sku", "   ", id="seller_sku_whitespace"),
    ],
)
def test_blank_identity_fields_rejected_by_db_check(
    db_session: Session,
    user_factory,
    field_name: str,
    value: str,
) -> None:
    user = user_factory(f"listing-blank-{field_name}@example.com")
    account = _make_account(user.id)
    db_session.add(account)
    db_session.flush()

    listing = _make_listing(amazon_account_id=account.id)
    setattr(listing, field_name, value)
    db_session.add(listing)
    with pytest.raises(IntegrityError):
        db_session.flush()
