"""Detect stale processing generation requests (no automatic LLM retry)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.services.generation_executor import (
    STALE_PROCESSING_MINUTES,
    find_stale_processing_requests,
)


def main() -> int:
    db: Session = SessionLocal()
    try:
        stale = find_stale_processing_requests(db, older_than_minutes=STALE_PROCESSING_MINUTES)
        if not stale:
            print("No stale processing generation requests found.")
            return 0

        print(f"Found {len(stale)} stale processing request(s):")
        for request in stale:
            print(
                f"- id={request.id} user_id={request.user_id} "
                f"type={request.request_type} started_at={request.started_at}"
            )
        print("Manual reconciliation required; LLM calls are not retried automatically.")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
