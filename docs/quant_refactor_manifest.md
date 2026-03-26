# Quant Architecture Refactor Manifest

## Target Layering

- `backend/src/research/`: offline edge discovery and validation only
- `backend/src/models/`: pure model computations and signal composition
- `backend/src/platform/`: runtime alpha consumption, registry lifecycle, flow/context, allocator, risk gate
- `backend/src/execution/`: order manager and slippage/execution mechanics
- `backend/src/data/`: market and flow data clients/fetching
- `backend/src/ops/`: diagnostics and runtime observability (progressively migrated)
- `scripts/`: deterministic orchestration entrypoints
- `registry/`: versioned edge registry outputs for deployment selection

## Deterministic Runtime Data Flow

`data -> features -> alpha_engine -> meta_alpha -> portfolio_allocator -> risk_engine -> execution`

## Classification Summary (Current Module Paths Pre-Migration)

Note: Ops entries remain transitional until the planned migration from `backend/src/monitoring/` to `backend/src/ops/` is completed.

- Research:
  - `backend/src/research/edge_discovery.py`
  - `backend/src/research/alpha_validation.py`
- Models:
  - `backend/src/models/meta_alpha_engine.py`
  - `backend/src/models/regime_detector.py`
- Platform:
  - `backend/src/platform/alpha_engine.py`
  - `backend/src/platform/api_service.py`
  - `backend/src/platform/edge_registry.py`
  - `backend/src/platform/registry_versioning.py`
  - `backend/src/platform/flow_features.py`
  - `backend/src/platform/market_context.py`
  - `backend/src/platform/portfolio_allocator.py`
  - `backend/src/platform/risk_engine.py`
  - `backend/src/platform/workers/execution_engine.py`
  - `backend/src/platform/workers/trading_engine.py`
- Execution:
  - `backend/src/execution/order_manager.py`
  - `backend/src/execution/slippage_model.py`
- Data:
  - `backend/src/data/binance_flow.py`
- Ops:
  - `backend/src/monitoring/failure_diagnostics.py`
  - `backend/src/monitoring/shadow_live_tracker.py`

## What Was Refactored

1. Runtime alpha is now registry-driven:
   - `backend/src/platform/alpha_engine.py` no longer performs online edge discovery.
   - It reloads and consumes `EDGE_REGISTRY_PATH` snapshots and selects matching runtime edges.

2. Validation discovery boundary fixed:
   - `backend/src/research/alpha_validation.py` now discovers top edges via `EdgeDiscoveryEngine` in research layer.

3. Missing institutional modules added:
   - `backend/src/platform/portfolio_allocator.py`
   - `backend/src/platform/risk_engine.py`
   - `scripts/run_shadow_trading.py`

4. Trading worker uses allocator contract before risk/execution handoff:
   - `backend/src/platform/workers/trading_engine.py`

5. Registry lifecycle output standardized:
   - `scripts/run_capital_readiness_pipeline.py` writes versioned snapshots to `registry/versions/`.

6. Artifact hygiene hardened:
   - `.gitignore` updated for generated tuning artifacts/logs, cache, and registry version outputs.

## Interface Contracts

### Signal Schema (alpha -> trading)

- Required:
  - `symbol: str`
  - `side: "buy" | "sell"`
  - `price: float`
  - `confidence: float`
  - `score: float`
  - `selected_edge: str`
  - `edge_stats: dict[str, dict]`

- Optional:
  - `stop_loss: float`
  - `take_profit: float`
  - `regime: str`
  - `meta: dict`

### Registry Edge Format (research -> runtime)

- Required fields:
  - `edge_id`
  - `conditions.regime`
  - `conditions.volatility_state`
  - `conditions.session`
  - `direction`
  - `stats.expectancy`
  - `stats.t_stat`
  - `stats.profit_factor`

- Runtime filters:
  - `active = true`
  - `state != retired`

### Allocator I/O

- Input:
  - `edges: list[dict]` with `edge_id`, `direction`, `confidence_score`, `sample_size`, `asset_coverage`, `in_sample_metrics.t_stat`
- Output:
  - `positions: dict[symbol, exposure]`
  - `meta: dict` with concentration/exposure diagnostics

## Migration Notes

- Runtime behavior change:
  - Alpha now requires a registry file; without one, no trades are emitted.
- Compatibility:
  - `AlphaEngine.discover_edges` remains as a backward-compatible registry reload method.
- Potential breakpoints:
  - Incomplete registry rows (missing conditions/stats) will be ignored by runtime.

## Remaining Move Matrix

- `backend/src/workers/trading_loop.py`:
  - Current role: legacy monolithic runtime loop (alpha + execution + persistence side effects).
  - Target ownership: split responsibilities into `backend/src/platform/workers/` plus thin compatibility adapter.
  - Action: keep as compatibility entrypoint for now, progressively route internals to platform worker modules.

- `backend/src/api/main.py`:
  - Current role: legacy API with optional in-process worker startup.
  - Target ownership: stateless control plane in `backend/src/platform/api_service.py`.
  - Action: retain for backward compatibility, but treat as transitional path only.

- `backend/src/execution/execution_engine.py`:
  - Current role: execution logic used by legacy loop.
  - Target ownership: canonical execution worker flow in `backend/src/platform/workers/execution_engine.py`.
  - Action: maintain during migration; avoid adding new business logic outside platform worker path.

- `backend/src/monitoring/failure_diagnostics.py` and `backend/src/monitoring/shadow_live_tracker.py`:
  - Current role: diagnostics/runtime telemetry implementations.
  - Target ownership: `backend/src/ops/`.
  - Action: migrate imports to `backend/src/ops/diagnostics.py` facade first, then physically move implementations when import graph is clean.

- `scripts/run_alpha_validation.py` and `scripts/tune_alpha_parameters.py`:
  - Current role: research/validation orchestration.
  - Target ownership: `scripts/` is correct.
  - Action: no move required; keep strictly offline and research-scoped.

- `scripts/run_capital_readiness_pipeline.py` and `scripts/discover_edge.py`:
  - Current role: registry lifecycle and deployment readiness orchestration.
  - Target ownership: `scripts/` plus `registry/versions/` outputs.
  - Action: no move required; enforce output-only artifacts under ignored generated paths.

## Phase Gate For Physical Moves

- Phase 1:
  - Route all new call sites to canonical `backend/src/platform/*` and `backend/src/ops/*` facades.
  - Confirm tests and scripts pass with compatibility adapters still present.

- Phase 2:
  - Move implementation bodies from legacy modules into canonical locations.
  - Leave import shims in old paths to avoid runtime breakage.

- Phase 3:
  - Remove shims only after full suite and deployment stack pass in CI.

## How To Run

1. Discover registry:
   - `python scripts/discover_edge.py --symbols BTC-USD ETH-USD --period 180d --interval 1h --output-dir data`

2. Shadow run:
   - `python scripts/run_shadow_trading.py --symbol BTC-USD --period 60d --interval 1h --registry data/edge_registry.json --output-dir data`

3. Capital readiness:
   - `python scripts/run_capital_readiness_pipeline.py --period 30d --interval 1h --symbol BTC-USD --output-dir data`
