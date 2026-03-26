# Vision AI Event Contracts (v1.0.0)

All events use the EventEnvelope schema:

- event_id
- correlation_id
- timestamp
- schema_version
- source
- event_name
- payload

Implementation: backend/src/contracts/events.py

## Event Names

1. market.bar.closed

- Stream: market.bar.closed
- Source: market-data-service
- Payload: symbol, timeframe, open, high, low, close, volume, close_time

2. feature.vector.ready

- Stream: feature.vector.ready
- Source: feature-service
- Payload: symbol, vector (latest feature row)

3. model.inference.completed

- Stream: model.inference.completed
- Source: model-service
- Payload: symbol, horizon, predictions

4. signal.generated

- Stream: signal.generated
- Source: signal-service
- Payload: symbol, direction, score, confidence, signals, weights, regime

5. order.intent.created

- Stream: order.intent.created
- Source: execution-gateway
- Payload: intent_id, symbol, side, quantity, order_type, limit_price

6. risk.decision

- Stream: risk.decision
- Source: risk-service
- Payload: symbol, decision, trade_value

7. order.executed

- Stream: order.executed
- Source: execution-gateway
- Payload: intent_id, order_id, status, symbol, side, quantity, filled_price

8. portfolio.updated

- Stream: portfolio.updated
- Source: portfolio-service
- Payload: performance, state

## Idempotency and Exactly-Once Notes

- Producer idempotency is enforced using deterministic intent keys in execution-gateway.
- Consumer dedupe support exists in RedisStreamsBus with processed-event key cache.
- For hard exactly-once semantics, extend with durable consumer checkpoints and transactional outbox in each transactional service.
