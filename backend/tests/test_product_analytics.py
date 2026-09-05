import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.product_analytics_service import build_analytics_summary


class _Query:
    def __init__(self, events):
        self.events = events

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def all(self):
        return self.events


class _Db:
    def __init__(self, events):
        self.events = events

    def query(self, *_args):
        return _Query(self.events)


def test_summary_counts_events_users_success_rate_and_daily_series():
    user_id = uuid.uuid4()
    today = datetime.now(UTC)
    events = [
        SimpleNamespace(event_type="registration_completed", user_id=user_id, occurred_at=today),
        SimpleNamespace(event_type="audit_started", user_id=user_id, occurred_at=today),
        SimpleNamespace(event_type="audit_completed", user_id=user_id, occurred_at=today),
        SimpleNamespace(event_type="amazon_connect_started", user_id=user_id, occurred_at=today),
    ]
    summary = build_analytics_summary(_Db(events), days=7)

    assert summary["counts"]["audit_started"] == 1
    assert summary["unique_users"]["audit_completed"] == 1
    assert summary["audit_success_rate"] == 100.0
    assert len(summary["daily"]) == 7
    assert summary["daily"][-1]["registration_completed"] == 1
