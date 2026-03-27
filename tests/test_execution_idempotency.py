from __future__ import annotations

from backend.src.platform import repository


class _FakeDb:
    def __init__(self) -> None:
        self.execution: dict[str, dict[str, str]] = {}

    def fetchone(self, query: str, params=None):
        q = " ".join(str(query).split()).lower()
        if q.startswith("insert into execution_idempotency"):
            key = str(params[0])
            source_event_id = str(params[1])
            if key in self.execution:
                return None
            self.execution[key] = {
                "source_event_id": source_event_id,
                "status": "processing",
                "order_id": "",
            }
            return (key,)
        if q.startswith("select status from execution_idempotency"):
            key = str(params[0])
            rec = self.execution.get(key)
            if rec is None:
                return None
            return (rec["status"],)
        return None

    def execute(self, query: str, params=None) -> None:
        q = " ".join(str(query).split()).lower()
        if q.startswith("update execution_idempotency"):
            status = str(params[0])
            order_id = params[1]
            key = str(params[2])
            if key not in self.execution:
                self.execution[key] = {
                    "source_event_id": "",
                    "status": status,
                    "order_id": str(order_id or ""),
                }
                return
            self.execution[key]["status"] = status
            if order_id:
                self.execution[key]["order_id"] = str(order_id)


def test_execution_idempotency_blocks_duplicates() -> None:
    db = _FakeDb()
    first_claimed, first_status = repository.claim_execution_idempotency(
        db,
        idempotency_key="exec:key:1",
        source_event_id="evt-1",
    )
    second_claimed, second_status = repository.claim_execution_idempotency(
        db,
        idempotency_key="exec:key:1",
        source_event_id="evt-1-duplicate",
    )

    assert first_claimed is True
    assert first_status == "processing"
    assert second_claimed is False
    assert second_status == "processing"


def test_execution_idempotency_status_transition() -> None:
    db = _FakeDb()
    repository.claim_execution_idempotency(db, "exec:key:2", "evt-2")
    repository.mark_execution_idempotency(
        db,
        idempotency_key="exec:key:2",
        status="filled",
        order_id="order-123",
    )

    assert db.execution["exec:key:2"]["status"] == "filled"
    assert db.execution["exec:key:2"]["order_id"] == "order-123"
