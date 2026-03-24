# Alpha Engine Upgrade (1H/4H)

## Scope

This upgrade focuses only on alpha quality and execution decisioning. Infrastructure remains unchanged.

## Phase 1: Edge Discovery Rules

Signals are accepted only when all are true on rolling historical tests:

- positive expectancy
- win rate >= 54%
- profit factor > 1.2
- t-stat > 2.0
- minimum 100 samples

Edge families evaluated:

- order_book_imbalance (proxy from candle microstructure and signed volume, scoring modifier unless it independently passes full primary-signal filters)
- volume_delta spikes
- volatility compression then expansion breakouts
- trend continuation with 1H/4H alignment
- liquidity sweep reversals

## Phase 2: Production Signals

Only three primary signals are used:

1. trend_continuation

- entry: 1H EMA fast/slow aligns with 4H trend and positive volume delta z-score
- exit: opposite signal or risk-engine/execution controls

2. vol_compression_expansion

- entry: ATR compression and breakout of 20-bar range
- exit: opposite signal or risk controls

3. liquidity_sweep_reversal

- entry: sweep of rolling high/low and strong wick rejection
- exit: opposite signal or risk controls

A fourth support feature, order_book_imbalance proxy, is used in scoring by default.
order_book_imbalance is promoted to a primary signal only if it passes the same statistical filters as primary signals; otherwise it remains a scoring modifier.

## Phase 3: Meta Alpha

`MetaAlphaEngine` now uses:

- regime-aware weights (`trend` vs `range`)
- weighted score fusion
- confidence calibration from score magnitude, signal agreement, and edge quality

Output contract:

```json
{
  "score": 0.31,
  "confidence": 0.64,
  "regime": "trend",
  "decision": "long"
}
```

Backward-compatible keys (`signal`, `alpha_score`, `probability`) are still emitted for existing callers.

## Phase 4: Validation Stack

Validation module:

- `backend/src/research/alpha_validation.py`

Runner:

- `scripts/run_alpha_validation.py`

Includes:

- cost-aware backtest (fees + slippage)
- warmup-aware walk-forward slicing (training segment warms alpha state before each test window)
- Monte Carlo stress test via `MonteCarloEngine`

Parameter search utility:

- `scripts/tune_alpha_parameters.py`
- writes structured output with `best` and `top_candidates` to `alpha_tuning_result.json` (or custom `--output`)
- evaluates short horizon (`--period`) and medium horizon (`--medium-period`) simultaneously
- applies staged objective: drawdown containment first, then PF/Sharpe optimization under trade-count constraints
- includes regime-segmented acceptance checks (`trend`, `range`, `high_volatility`) to reject unstable candidates
- uses two-stage runtime control: prefilter all combos, then run full checks on a shortlist (`--shortlist-size`)
- runtime controls: `--max-combos`, `--wf-windows`, `--medium-eval-bars`, optional `--medium-wf`

## Phase 5: Profitability Targets

Hard pass gate:

- Profit Factor > 1.5
- Sharpe > 1.5
- Max Drawdown < 10%
- Trades >= 100

`AlphaValidationEngine.passes_targets()` enforces this.

Phase 1 is exploratory (candidate generation under strict but broader coverage constraints), while Phase 5 is the production deployment gate.
Fallback when no Phase 5 candidates survive: keep signals in shadow mode, retune parameters with explicit target constraints, and only relax for research runs (never production) through a separately flagged validation path.

## Phase 6: Microservice Integration

Trading worker now emits only vetted alpha events:

- file: `backend/src/platform/workers/trading_engine.py`
- flow: market tick -> alpha engine (1H bar close) -> meta score -> sized `signal.generated`
- no random side generation remains

## Phase 7: Timeframe Migration

All strategy logic is based on:

- primary: 1H bars
- context: 4H bars

5m-style noise logic is not used.

## Phase 8: Sizing and Risk Inputs

Implemented in alpha engine:

- capped Kelly fraction (`<= 15%`)
- volatility scalar on recent 1H returns
- dynamic stop distance from ATR and price floor

Price floor is the minimum allowable executable price used to prevent oversized quantity calculations when price inputs are stale or malformed.
Sizing flow: capped Kelly fraction -> confidence scaling -> volatility scalar -> notional and quantity.
Risk placement flow: dynamic stop distance = ATR component + price floor guard, then stop_loss/take_profit are derived from that distance.
Alpha outputs influence this flow as follows: confidence scales Kelly, score gates and scales size tiering, and regime selects risk profile/volatility scaling behavior.

Order payload includes:

- `quantity`
- `notional`
- `stop_loss`
- `take_profit`
- `confidence`
- `score`
- `regime`

## Phase 9: Live Validation Protocol

For paper trading over 5-7 days:

1. run stack with existing queue + workers
2. track daily PF, Sharpe proxy, realized drawdown, and fill quality
3. disable symbols/time windows where edge filters fail persistently
4. promote only after stable rolling metrics and low execution drift
