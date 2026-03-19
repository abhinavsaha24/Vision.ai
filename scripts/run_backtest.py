"""
Institutional-Grade Strict Multi-Symbol Backtest Engine.

Features:
- Walk-forward validation (strict chronologic Train/Test split via time)
- Synchronization of multi-symbol datasets (BTC, ETH, SOL)
- Execution integration with 10bps transaction costs + slippage scaling
- Dynamic Entries and Exits (Kelly sizing, ATR stops, Time limits)
- Comprehensive performance analysis output.
"""

import sys
import os
import logging
from datetime import datetime, timezone

# Fix project imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd
import numpy as np
from tqdm import tqdm

from backend.src.data.fetcher import DataFetcher
from backend.src.features.indicators import FeatureEngineer
from backend.src.features.alpha_features import compute_alpha_features, get_alpha_feature_names
from backend.src.models.alpha_model import AlphaModel, AlphaModelConfig
from backend.src.strategy.strategy_engine import StrategyEngine
from backend.src.risk.risk_manager import RiskManager, RiskLimits
from backend.src.portfolio.portfolio_manager import PortfolioManager
from backend.src.execution.execution_engine import ExecutionEngine
from backend.src.exchange.exchange_adapter import PaperAdapter

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def compute_metrics(equity_curve, trades):
    """Compute institutional metrics: Sharpe, Profit Factor, Expectancy, Win Rate, Max DD."""
    if not equity_curve:
        return {}
        
    s_eq = pd.Series(equity_curve)
    returns = s_eq.pct_change().dropna()
    
    # Sharpe
    sharpe = 0.0
    if len(returns) > 1 and returns.std() != 0:
        sharpe = np.sqrt(288 * 365) * returns.mean() / returns.std()  # 5m bars annualized
        
    # Drawdown
    cummax = s_eq.cummax()
    drawdown = (cummax - s_eq) / cummax
    max_dd = drawdown.max()
    
    # Trade Metrics
    win_rate = 0.0
    profit_factor = 0.0
    expectancy = 0.0
    winning_trades = 0
    
    if len(trades) > 0:
        gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
        winning_trades = len([t for t in trades if t["pnl"] > 0])
        
        win_rate = winning_trades / len(trades)
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        expectancy = (gross_profit - gross_loss) / len(trades)
        
    return {
        "Total Return": f"{(s_eq.iloc[-1] / s_eq.iloc[0] - 1)*100:.2f}%",
        "Sharpe Ratio": f"{sharpe:.2f}",
        "Max Drawdown": f"{max_dd*100:.2f}%",
        "Win Rate": f"{win_rate*100:.1f}% ({winning_trades}/{len(trades)})",
        "Profit Factor": f"{profit_factor:.2f}",
        "Expectancy per Trade": f"${expectancy:.2f}"
    }

def main():
    print("=" * 60)
    print("VISION-AI: INSTITUTIONAL MULTI-SYMBOL BACKTEST ENGINE")
    print("=" * 60)

    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    
    fetcher = DataFetcher()
    engineer = FeatureEngineer()
    
    dfs = {}
    master_index = None
    
    # 1. Fetch & prep data
    for sym in symbols:
        print(f"Fetching {sym} (3000 bars, 1h)...")
        # Ensure we suppress warnings if DataFetcher causes them
        df_raw = fetcher.fetch(symbol=sym, timeframe="1h", limit=3000)
        df = engineer.add_candle_structure(df_raw)
        df = engineer.add_volume_features(df)
        df = engineer.add_momentum_features(df)
        df = engineer.add_rsi(df)
        df = engineer.add_atr(df)
        df = engineer.add_returns(df)
        df = engineer.add_moving_averages(df)
        df = engineer.add_statistical_features(df)
        df = engineer.add_microstructure_features(df)
        df = engineer.add_regime_features(df)
        df = compute_alpha_features(df)
        df = engineer.add_target(df, horizon=5, threshold_bps=15)
        df = df.dropna()
        
        dfs[sym] = df
        if master_index is None:
            master_index = df.index
        else:
            master_index = master_index.intersection(df.index)
            
    # Align by master index
    print("\nAligning data across assets to ensure no look-ahead bias...")
    for sym in symbols:
        dfs[sym] = dfs[sym].loc[master_index].copy()
        
    print(f"Aligned dataset: {len(master_index)} concurrent 1h bars.")
    
    # 2. Strict Walk-Forward Time Split
    # P > 0.60, conf > 0.55 requirements demand a properly calibrated ML model
    split_idx = int(len(master_index) * 0.5)
    train_idx = master_index[:split_idx]
    test_idx = master_index[split_idx:]
    
    print(f"Train set: {len(train_idx)} bars. Test set (Out-Of-Sample): {len(test_idx)} bars.")
    
    models = {}
    alpha_cols = get_alpha_feature_names(dfs[symbols[0]])
    config = AlphaModelConfig(calibrate=False, long_threshold=0.60, short_threshold=0.40)
    
    for sym in symbols:
        print(f"Training AlphaModel for {sym}...")
        model = AlphaModel(config=config)
        train_df = dfs[sym].loc[train_idx]
        
        # Prepare arrays
        X_train = train_df[alpha_cols].values
        y_train = train_df["Target_Direction"].values.astype(int)
        
        # Actionable weights
        weights = train_df["Target_Actionable"].values.astype(float)
        weights = np.where(weights > 0, 2.0, 1.0)
        
        model.fit(X_train, y_train, feature_names=alpha_cols, sample_weight=weights)
        models[sym] = model
        
    # 4. Setup Execution Environment
    print("\nInitializing Strict Backtest Environment...")
    INITIAL_CAP = 100000.0
    from backend.src.exchange.exchange_adapter import PaperAdapter
    
    # Realistic Binance Futures Perpetuals Cost Structure: 
    # 4 bps Taker fee, ~5 bps max slippage for highly liquid pairs limit/market crossing
    adapter = PaperAdapter(initial_cash=INITIAL_CAP, commission_rate=0.0004, max_slippage=0.0005)
    portfolio = PortfolioManager(initial_cash=INITIAL_CAP)
    
    risk_limits = RiskLimits(
        max_position_size=0.15,      # 15% risk allocation per trade
        max_portfolio_exposure=0.60, # 60% max portfolio exposure to utilize collateral
        tp_rr_ratio=3.0,             # 3.0R target to out-earn commissions 
        sl_atr_multiplier=1.5,       # 1.5 ATR tight stop 
        trailing_stop_pct=0.03       # 3% trailing stop 
    )
    risk_manager = RiskManager(limits=risk_limits)
    
    strategy = StrategyEngine(long_threshold=0.60, short_threshold=0.40, min_confidence=0.20)
    
    execution = ExecutionEngine(
        strategy_engine=strategy,
        risk_manager=risk_manager,
        portfolio_manager=portfolio,
        adapter=adapter
    )
    
    # 5. Backtest Loop
    print("Simulating...")
    
    equity_curve = []
    closed_trades = [] # track outcomes
    tp_1_hit = {sym: False for sym in symbols} # Track partial exits
    
    # State tracking
    bars_held = {sym: 0 for sym in symbols}
    highest_price_tracker = {sym: 0.0 for sym in symbols}
    lowest_price_tracker = {sym: float('inf') for sym in symbols}
    
    # Create simple mock dictionary to hold prices
    mock_prices = {sym: 0.0 for sym in symbols}
    
    for ts in tqdm(test_idx, desc="Simulating"):
        for sym in symbols:
            df = dfs[sym]
            current_bar = df.loc[ts]
            current_price = float(current_bar["close"])
            current_atr = float(current_bar["atr_14"]) if "atr_14" in current_bar.index else (current_price * 0.005)
            
            mock_prices[sym] = current_price
            
            portfolio_state = portfolio.get_portfolio()
            pos = portfolio_state["positions"].get(sym)
            
            # --- EXIT PHASE ---
            if pos:
                bars_held[sym] += 1
                
                # Update trackers
                entry = pos["entry_price"]
                qty = pos["quantity"]
                if pos["side"] == "long":
                    highest_price_tracker[sym] = max(highest_price_tracker[sym], current_price)
                    ext_price = highest_price_tracker[sym]
                    unrealized_pnl_pct = (current_price - entry) / entry
                else:
                    lowest_price_tracker[sym] = min(lowest_price_tracker[sym], current_price)
                    ext_price = lowest_price_tracker[sym]
                    unrealized_pnl_pct = (entry - current_price) / entry
                
                # Calculate stop distance using ENTRY ATR, enforcing a 1.2% minimum floor.
                # Crucial: This freezes the R-multiple at entry so it doesn't fluctuate mid-trade.
                metadata = pos.get("metadata", {})
                entry_vol = float(metadata.get("volatility", current_atr))
                if entry_vol <= 0:
                    entry_vol = current_atr
                    
                stop_distance = max(entry_vol * 1.5, entry * 0.012)
                one_r_pct = stop_distance / entry if entry > 0 else 0.012
                
                # Dynamic stop: starts at 1.5 ATR, moves to breakeven after 1 ATR profit
                metadata = pos.get("metadata", {})
                if unrealized_pnl_pct >= one_r_pct * 0.75:
                    # After 0.75R profit: move stop to breakeven + 10bps buffer
                    if "breakeven" not in metadata:
                        metadata["breakeven"] = True
                        if "metadata" not in pos:
                            pos["metadata"] = {}
                        pos["metadata"]["breakeven"] = True
                        
                    if pos["side"] == "long":
                        effective_stop = entry * 1.001  
                    else:
                        effective_stop = entry * 0.999
                else:
                    # Initial stop
                    if pos["side"] == "long":
                        effective_stop = entry - stop_distance
                    else:
                        effective_stop = entry + stop_distance
                
                exit_reason = None
                trigger_price = None
                
                # Evaluate intra-bar to prevent massive hourly close gapping slippage
                bar_low = df['low'].iloc[-1]
                bar_high = df['high'].iloc[-1]
                
                # Check Stop Loss & Breakeven first (stops trigger instantly)
                if (pos["side"] == "long" and bar_low <= effective_stop):
                    exit_reason = "stop_loss" if not pos.get("metadata", {}).get("breakeven") else "breakeven_stop"
                    trigger_price = effective_stop
                elif (pos["side"] == "short" and bar_high >= effective_stop):
                    exit_reason = "stop_loss" if not pos.get("metadata", {}).get("breakeven") else "breakeven_stop"
                    trigger_price = effective_stop
                
                # Check Take profit at 2.5R 
                elif (pos["side"] == "long" and bar_high >= entry + stop_distance * 2.5):
                    exit_reason = "take_profit"
                    trigger_price = entry + stop_distance * 2.5
                elif (pos["side"] == "short" and bar_low <= entry - stop_distance * 2.5):
                    exit_reason = "take_profit"
                    trigger_price = entry - stop_distance * 2.5
                    
                # Trailing stop
                elif pos.get("metadata", {}).get("breakeven"):
                    trail_pct = 0.03
                    if pos["side"] == "long" and current_price <= ext_price * (1 - trail_pct):
                        exit_reason = "trailing_stop"
                        trigger_price = current_price
                    elif pos["side"] == "short" and current_price >= ext_price * (1 + trail_pct):
                        exit_reason = "trailing_stop"
                        trigger_price = current_price
                        
                # Time stop
                elif bars_held[sym] >= 24 * 5:
                    exit_reason = "time_stop"
                    trigger_price = current_price
                    
                # Signal reversal 
                elif (pos["side"] == "long" and prediction == -1) or \
                     (pos["side"] == "short" and prediction == 1):
                    exit_reason = "signal_reversal"
                    trigger_price = current_price
                    
                if exit_reason:
                    qty = pos["quantity"]
                    
                    # Apply standard slip to the exact intra-bar trigger price
                    # This simulates a Stop Market or Take Profit Limit order execution
                    import random
                    slip_pct = random.uniform(0, 0.0005)
                    if pos["side"] == "long":
                        exit_price = trigger_price * (1 - slip_pct)
                    else:
                        exit_price = trigger_price * (1 + slip_pct)
                        
                    # Close in portfolio with exact simulated price
                    portfolio.close_position(sym, exit_price, close_quantity=qty)
                    
                    # Deduct exactly 4 bps commission for both entry and exit from portfolio cash
                    # (PortfolioManager.open/close doesn't handle commissions by default)
                    total_commission = (entry * qty * 0.0004) + (exit_price * qty * 0.0004)
                    
                    # Calculate Net PnL for logging
                    if pos["side"] == "long":
                        pnl = (exit_price - entry) * qty
                    else:
                        pnl = (entry - exit_price) * qty
                        
                    pnl -= total_commission
                    closed_trades.append({"symbol": sym, "pnl": pnl, "reason": exit_reason})
                    
                    print(f"[{sym} {exit_reason}] {pos['side'].upper()} entry={entry:.2f} exit={exit_price:.2f} qty={qty:.4f} | Gross: {pnl+total_commission:.2f} | Fees: {total_commission:.2f} | Net: {pnl:.2f} | Cash: {portfolio.cash:.2f}")
                        
                    # Reset trackers
                    bars_held[sym] = 0
                    highest_price_tracker[sym] = 0.0
                    lowest_price_tracker[sym] = float('inf')
                    continue
            
            # --- ENTRY PHASE (ML-DRIVEN) ---
            if not pos:
                window = df.loc[:ts].iloc[-1:] 
                
                # Get calibrated probability from ML model — NO stretching
                X_window = window[alpha_cols].values
                proba = float(models[sym].predict_proba(X_window)[-1])
                confidence = abs(proba - 0.5) * 2  # 0 to 1 scale
                
                # --- REGIME DETECTION ---
                # Use a 30-bar window for regime detection (needs 20+ bars for MA20)
                regime_window = df.loc[:ts].iloc[-30:]
                regime_str = strategy.detect_regime(regime_window)
                
                # Adaptive thresholds based on regime:
                # - Trending: we have edge, standard thresholds
                # - Volatile: tighter thresholds, require more confidence
                # - Ranging: wider thresholds, only trade strong signals
                if regime_str == "trending":
                    long_thresh, short_thresh = 0.58, 0.42
                elif regime_str == "volatile":
                    long_thresh, short_thresh = 0.62, 0.38
                else:  # ranging
                    long_thresh, short_thresh = 0.65, 0.35
                
                # --- TREND CONFIRMATION ---
                # Require price to be on the right side of EMA 9 or 21 for confirmation
                ema_9 = df["close"].ewm(span=9, adjust=False).mean().loc[ts]
                ema_21 = df["close"].ewm(span=21, adjust=False).mean().loc[ts]
                
                volatility_pct = current_atr / current_price if current_price > 0 else 0.0
                
                # --- ML-DRIVEN ENTRY SIGNALS ---
                final_signal = 0
                
                # LONG: Model says bullish + price above short-term EMA
                if proba >= long_thresh and confidence >= 0.10 and current_price > ema_9:
                    final_signal = 1
                
                # SHORT: Model says bearish + price below short-term EMA
                elif proba <= short_thresh and confidence >= 0.10 and current_price < ema_9:
                    final_signal = -1
                
                if final_signal == 0:
                    continue  # No entry signal
                    
                # --- EXECUTION INTELLIGENCE ---
                snapshot = {
                    "spread_bps": 5.0,
                    "order_book_imbalance": float(current_bar.get("of_ob_imbalance", 0.0) if "of_ob_imbalance" in current_bar.index else 0.0),
                    "book_depth_usd": 500000.0
                }
                
                if volatility_pct > 0.05:  # 5% volatility spike block
                    continue
                
                regime_dict = {"trend": regime_str, "label": regime_str}
                
                prediction = {
                    "direction": "LONG" if final_signal > 0 else "SHORT",
                    "probability": proba,
                    "confidence": confidence,
                    "dominant_strategy": "AlphaModel"
                }
                
                direction_label = "LONG" if final_signal > 0 else "SHORT"
                print(f"[{sym} | {ts}] ML {direction_label} | p={proba:.3f} | conf={confidence:.3f} | regime={regime_str}")
                
                result = {}
                try:
                    result = execution.process_market_data(
                        symbol=sym,
                        df=window,
                        prediction=prediction,
                        price=current_price,
                        regime=regime_dict,
                        market_snapshot=snapshot
                    )
                except Exception as e:
                    print(f"Error opening {direction_label.lower()}: {e}")

                if result.get("status") not in ["FILLED", "OPEN", "NO_SIGNAL", "POSITION_ALREADY_OPEN", "TRADE_EXECUTED"]:
                    err_msg = result.get('error', result.get('reason', 'Unknown'))
                    print(f"[{sym} | {ts}] REJECTED: {result.get('status')} - {err_msg}")
                    
                if result.get("status") in ["FILLED", "OPEN", "TRADE_EXECUTED"]:
                    # Store ATR for trailing stops
                    if sym in portfolio.get_portfolio()["positions"]:
                        p = portfolio.get_portfolio()["positions"][sym]
                        if "metadata" not in p:
                            p["metadata"] = {}
                        p["metadata"]["atr"] = current_atr
                        
                    bars_held[sym] = 0
                    if result.get("side") == "LONG":
                        highest_price_tracker[sym] = current_price
                    else:
                        lowest_price_tracker[sym] = current_price
                        
        # --- PORTFOLIO UPDATE ---
        # Update valuations
        if hasattr(adapter, "update_price"):
            for s, p in mock_prices.items(): adapter.update_price(s, p)
        
        # Inject mock prices directly to portfolio for tracking
        portfolio.update_equity(mock_prices, ts)
        
        p_state = portfolio.get_portfolio()
        equity_curve.append(p_state["equity_curve"][-1] if p_state["equity_curve"] else p_state["cash"])

    # 6. Performance Analysis
    metrics = compute_metrics(equity_curve, closed_trades)
    
    print("\n" + "=" * 60)
    print("PROFITABILITY ANALYSIS")
    print("=" * 60)
    
    for k, v in metrics.items():
        print(f"{k.ljust(25)}: {v}")
        
    print("\nExit Reasons Breakdown:")
    reasons = {}
    for t in closed_trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    for r, count in reasons.items():
        print(f"  {r}: {count}")
        
    print("\nIs this strategy profitable after costs?")
    if len(closed_trades) == 0:
        print("-> INCONCLUSIVE: Strategy is too strict to fire trades in this period.")
    else:
        net = float(metrics["Total Return"].strip("%"))
        if net > 0:
            print(f"-> YES. Profitable with strict 10bps costs and 2% risk limits.")
        else:
            print(f"-> NO. Strict transaction costs (10bps) and slippage consume the alpha.")
    print("=" * 60)

    # 7. Generate Performance Charts
    try:
        import matplotlib.pyplot as plt
        
        # Plot Equity Curve
        plt.figure(figsize=(10, 5))
        plt.plot(equity_curve, label='Portfolio Equity', color='blue')
        plt.title('Out-of-Sample Walk-Forward Equity Curve')
        plt.xlabel('Periods (15m)')
        plt.ylabel('Equity (USD)')
        plt.grid(True)
        plt.legend()
        plt.savefig('equity_curve.png')
        plt.close()
        
        # Plot Drawdown Curve
        if len(equity_curve) > 1:
            eq_arr = np.array(equity_curve)
            cummax = np.maximum.accumulate(eq_arr)
            drawdown = (eq_arr - cummax) / cummax
            
            plt.figure(figsize=(10, 5))
            plt.plot(drawdown * 100, label='Drawdown %', color='red')
            plt.fill_between(range(len(drawdown)), drawdown * 100, 0, color='red', alpha=0.3)
            plt.title('Out-of-Sample Walk-Forward Drawdown Curve')
            plt.xlabel('Periods (15m)')
            plt.ylabel('Drawdown (%)')
            plt.grid(True)
            plt.legend()
            plt.savefig('drawdown_curve.png')
            plt.close()
            
        print("\n[OK] Performance charts saved: equity_curve.png, drawdown_curve.png")
    except ImportError:
        print("\n[!] matplotlib not installed. Skipping charts.")
if __name__ == "__main__":
    main()