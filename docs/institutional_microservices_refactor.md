# Vision AI Institutional Refactor

## Final Folder Structure

```text
backend/src/platform/
  __init__.py
  api_service.py
  config.py
  db.py
  events.py
  logging.py
  queue.py
  repository.py
  risk_policy.py
  workers/
    __init__.py
    trading_engine.py
    risk_engine.py
    execution_engine.py

deployment/
  Dockerfile.quant
  docker-compose.quant.yml

fly.toml
```

## Service Boundaries

- api-service: Stateless control plane for strategy control, health, and portfolio queries.
- trading-engine: Generates signals from market tick events only when strategy is enabled.
- risk-engine: Evaluates position size, drawdown, and exposure limits before execution.
- execution-engine: Idempotent order execution with retries and persistence.
- legacy API safety: in-process paper-trading autostart is now disabled by default via `paper_trading_api_autostart=false`.

## Event-Driven Flow

1. API publishes `market.tick` or strategy control events into `events.trading` Redis Stream.
2. Trading engine consumes and emits `signal.generated`.
3. Risk engine consumes `signal.generated` and emits `signal.approved` or `risk.rejected` into `events.execution`.
4. Execution engine consumes `signal.approved` and emits `order.filled` or `order.failed`.

## Data Layer

PostgreSQL tables introduced:

- `strategy_control`: authoritative strategy run state
- `trading_events`: immutable event log
- `orders`: idempotent execution ledger
- `portfolio_snapshots_v2`: portfolio snapshots for reads and risk checks

## Local Run

```bash
docker compose -f deployment/docker-compose.quant.yml up --build
```

API examples:

```bash
curl -X POST http://localhost:8080/strategy/start \
  -H "Content-Type: application/json" \
  -d '{"strategy_name":"default"}'

curl -X POST http://localhost:8080/events/market \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","price":68000,"volume":12.4}'

curl http://localhost:8080/portfolio/latest
```

## Fly.io Deployment

1. Provision managed Redis and Postgres.
2. Set secrets:

```bash
fly secrets set REDIS_URL=redis://... DATABASE_URL=postgres://...
```

3. Deploy:

```bash
fly launch --no-deploy
fly deploy
```

4. Scale process groups:

```bash
fly scale count api=2 trading=2 risk=2 execution=3
```

## Scaling Recommendations

- API: scale horizontally behind Fly proxy, no sticky sessions needed.
- Trading/risk/execution workers: scale independently by queue lag and throughput.
- Redis Streams: use consumer groups and dead-letter streams for failed events.
- PostgreSQL: use managed service with read replicas for analytics queries.

## Future Upgrade Path

- Replace Redis Streams with Kafka for replay retention and partition parallelism.
- Introduce schema registry for event contracts.
- Add Kubernetes HPA/KEDA on queue depth.
- Add OpenTelemetry traces for end-to-end event lineage.
- Add exactly-once semantics with outbox/inbox pattern and dedupe keys.
