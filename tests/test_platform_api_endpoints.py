from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from starlette.requests import Request

from backend.src.platform import api_service


class _FakeQueue:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def publish(self, stream: str, payload: dict) -> str:
        self.events.append((stream, payload))
        return "1-0"


class _FakeDB:
    pass


class _CursorStub:
    def __init__(self, db: "_OutboxDBStub") -> None:
        self._db = db
        self._rows: list[tuple[int, str, str]] = []

    def __enter__(self) -> "_CursorStub":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, query: str, params=None) -> None:
        if "SELECT outbox_id, stream, payload::text" in query:
            limit = int(params[0]) if params else len(self._db.rows)
            self._rows = list(self._db.rows)[:limit]
            return
        if "DELETE FROM event_outbox WHERE outbox_id = ANY(%s)" in query:
            ids = list(params[0]) if params else []
            self._db.deleted_ids.extend(int(v) for v in ids)

    def fetchall(self) -> list[tuple[int, str, str]]:
        return list(self._rows)


class _ConnStub:
    def __init__(self, db: "_OutboxDBStub") -> None:
        self._db = db

    def __enter__(self) -> "_ConnStub":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def cursor(self) -> _CursorStub:
        return _CursorStub(self._db)


class _OutboxDBStub:
    def __init__(self, rows: list[tuple[int, str, str]]) -> None:
        self.rows = rows
        self.deleted_ids: list[int] = []

    def connection(self) -> _ConnStub:
        return _ConnStub(self)


class _FailingQueue:
    def __init__(self, fail_stream: str) -> None:
        self.fail_stream = fail_stream
        self.published: list[tuple[str, dict]] = []

    def publish(self, stream: str, payload: dict) -> str:
        if stream == self.fail_stream:
            raise RuntimeError("simulated_publish_failure")
        self.published.append((stream, payload))
        return "1-0"


def _request_with_state(db: _FakeDB, queue: _FakeQueue) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(db=db, queue=queue))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "app": app,
    }
    return Request(scope)


def test_health_endpoint_contract() -> None:
    payload = api_service.health()
    assert payload["status"] == "ok"
    assert payload["service"] == "api-service"


def test_strategy_status_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(api_service, "is_strategy_enabled", lambda _db, _name: True)
    req = _request_with_state(_FakeDB(), _FakeQueue())

    status = api_service.strategy_status("default", req)
    assert status["enabled"] is True


def test_publish_market_tick_endpoint(monkeypatch) -> None:
    captured_outbox: list[tuple[str, dict]] = []
    captured_flush: list[int] = []

    def _capture_outbox(_db, event, stream: str) -> None:
        captured_outbox.append((stream, event.to_dict()))

    def _capture_flush(_db, queue, max_rows: int = 100) -> int:
        captured_flush.append(max_rows)
        if captured_outbox:
            stream, payload = captured_outbox[-1]
            queue.publish(stream, payload)
        return 1

    monkeypatch.setattr(api_service, "_persist_event_to_outbox", _capture_outbox)
    monkeypatch.setattr(api_service, "_flush_outbox", _capture_flush)

    fake_db = _FakeDB()
    fake_queue = _FakeQueue()
    req = _request_with_state(fake_db, fake_queue)
    payload = api_service.MarketTickRequest(symbol="BTCUSDT", price=60000.0, volume=10.0)

    result = api_service.publish_market_tick(payload, req)

    assert result["status"] == "accepted"
    assert len(fake_queue.events) == 1
    assert fake_queue.events[0][0] == "events.trading"
    assert len(captured_outbox) == 1
    assert len(captured_flush) == 1


def test_portfolio_latest_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        api_service,
        "get_latest_portfolio",
        lambda _db: {"cash": 100000.0, "exposure": 0.0, "realized_pnl": 123.0},
    )
    req = _request_with_state(_FakeDB(), _FakeQueue())

    latest = api_service.portfolio_latest(req)
    assert latest["cash"] == 100000.0
    assert latest["realized_pnl"] == 123.0


def test_strategy_start_and_stop_use_outbox_and_flush(monkeypatch) -> None:
    captured_set: list[tuple[str, bool, str]] = []
    captured_flush: list[int] = []

    def _capture_set(_db, strategy_name: str, enabled: bool, event) -> None:
        captured_set.append((strategy_name, enabled, str(event.event_type.value)))

    def _capture_flush(_db, _queue, max_rows: int = 100) -> int:
        captured_flush.append(max_rows)
        return 1

    monkeypatch.setattr(api_service, "_set_strategy_and_persist_event", _capture_set)
    monkeypatch.setattr(api_service, "_flush_outbox", _capture_flush)

    req = _request_with_state(_FakeDB(), _FakeQueue())
    payload = api_service.StrategyControlRequest(strategy_name="default")

    start_result = api_service.start_strategy(payload, req)
    stop_result = api_service.stop_strategy(payload, req)

    assert start_result["status"] == "queued"
    assert stop_result["status"] == "queued"
    assert start_result["event_id"]
    assert stop_result["event_id"]

    assert captured_set == [
        ("default", True, "strategy.start"),
        ("default", False, "strategy.stop"),
    ]
    assert captured_flush == [100, 100]


def test_flush_outbox_partial_failure_deletes_only_delivered_rows() -> None:
    rows = [
        (1, "events.trading", '{"event_id":"evt-1"}'),
        (2, "events.fail", '{"event_id":"evt-2"}'),
    ]
    db = _OutboxDBStub(rows=rows)
    queue = _FailingQueue(fail_stream="events.fail")

    delivered = api_service._flush_outbox(cast(Any, db), cast(Any, queue), max_rows=100)

    assert delivered == 1
    assert len(queue.published) == 1
    assert queue.published[0][0] == "events.trading"
    assert db.deleted_ids == [1]
