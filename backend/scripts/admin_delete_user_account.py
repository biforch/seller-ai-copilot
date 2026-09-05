"""Administrative user-account deletion CLI for verified support requests."""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime

from app.core.config import settings
from app.database.session import SessionLocal
from app.integrations.amazon.token_encryption_loader import build_token_encryption_service
from app.services.user_account_deletion_service import UserAccountDeletionService


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete a Listnara user account and associated data after a verified support request.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--user-id", type=uuid.UUID, help="User UUID to delete")
    target.add_argument("--email", help="Account email to delete (exact match, case-insensitive)")
    parser.add_argument(
        "--request-reference",
        help="Support ticket or request identifier (logged without sensitive content)",
    )
    parser.add_argument(
        "--request-date",
        help="ISO date the deletion request was received (for operator records only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without modifying the database",
    )
    parser.add_argument(
        "--confirm",
        choices=("DELETE",),
        help="Required safety latch; must be DELETE for a live deletion",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.dry_run and args.confirm != "DELETE":
        print("Refusing to delete without --confirm DELETE or --dry-run.", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        service = UserAccountDeletionService(db, build_token_encryption_service(settings))
        if args.user_id is not None:
            result = service.delete_user_account(
                user_id=args.user_id,
                request_reference=args.request_reference,
                dry_run=args.dry_run,
            )
        else:
            result = service.delete_user_by_email(
                email=args.email,
                request_reference=args.request_reference,
                dry_run=args.dry_run,
            )

        completed_at = datetime.now(UTC).isoformat()
        print(
            "user_account_deletion_result "
            f"already_deleted={result.already_deleted} "
            f"user_id={result.user_id} "
            f"amazon_accounts_removed={result.amazon_accounts_removed} "
            f"deleted_at={result.deleted_at.isoformat() if result.deleted_at else None} "
            f"request_reference={result.request_reference or 'unspecified'} "
            f"request_date={args.request_date or 'unspecified'} "
            f"completed_at={completed_at} "
            f"dry_run={args.dry_run}"
        )
        return 0 if result.already_deleted or result.deleted_at is not None or args.dry_run else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
