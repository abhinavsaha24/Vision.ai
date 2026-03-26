"""
Script to run anchored walk-forward validation on the new Alpha Engine.
"""

import sys
import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

# Configure path so we can import backend
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.data.fetcher import DataFetcher
from backend.src.features.indicators import FeatureEngineer
from backend.src.features.alpha_features import compute_alpha_features, get_alpha_feature_names
from backend.src.models.alpha_model import walk_forward_alpha, AlphaModelConfig
from backend.src.research.signal_engine import QuantSignalEngine

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def main():
    print("=" * 60)
    print("VISION-AI: ALPHA ENGINE WALK-FORWARD VALIDATION")
    print("=" * 60)

    # 1. Fetch 30 days of 5m data (~8,600 bars)
    fetcher = DataFetcher()
    symbol = "BTC/USDT"
    print(f"\n1. Fetching historical data for {symbol}...")
    df = fetcher.fetch(symbol, timeframe="5m", limit=3000) # Fetch recent max limit
    
    if df is None or len(df) < 1000:
        print("Failed to fetch sufficient data.")
        return
        
    print(f"   ✓ Fetched {len(df)} 5-minute bars")

    # 2. Engineer Features
    print("\n2. Computing Alpha Features (Microstructure, Volatility, Stats)...")
    engineer = FeatureEngineer()
    
    # Base indicators
    df = engineer.add_candle_structure(df)
    df = engineer.add_volume_features(df)
    df = engineer.add_momentum_features(df)
    df = engineer.add_returns(df)
    df = engineer.add_moving_averages(df)  # REQUIRED for regime features
    df = engineer.add_statistical_features(df)
    df = engineer.add_microstructure_features(df)
    df = engineer.add_regime_features(df)
    
    # Advanced Alpha Features
    df = compute_alpha_features(df)
    
    # Add Targets (5-bar horizon)
    df = engineer.add_target(df, horizon=5, threshold_bps=15)
    
    # Clean up NaNs
    df = df.dropna()
    print(f"   ✓ Generated {len(df.columns)} features. Active bars: {len(df)}")
    
    # 3. Get feature columns
    alpha_cols = get_alpha_feature_names(df)
    print(f"   ✓ Identified {len(alpha_cols)} pure alpha features")

    # 4. Run Anchored Walk-Forward Validation
    print("\n3. Running strict out-of-sample walk-forward validation...")
    print("   - Strategy: XGBoost + LightGBM Ensemble")
    print("   - Calibration: Isotonic Regression")
    print("   - Anchored splits: 5 folds (Train expanding, Test rolling)")
    print("   - Costs: 10bps fee + 10bps slippage per trade")
    print("-" * 60)
    
    config = AlphaModelConfig(
        calibrate=True,
        long_threshold=0.60,
        short_threshold=0.40,
    )
    
    # Disable LGBM/XGB verbose logs for clean output
    import warnings
    warnings.filterwarnings('ignore')
    
    results = walk_forward_alpha(
        df=df,
        feature_cols=alpha_cols,
        n_splits=5,
        train_ratio=0.5,
        fee_bps=10,
        slippage_bps=10,
        config=config
    )
    
    if "error" in results:
        print(f"ERROR: {results['error']}")
        return

    # 5. Output Results
    print("\n" + "=" * 60)
    print("WALK-FORWARD VALIDATION RESULTS")
    print("=" * 60)
    
    for f in results["folds"]:
        print(f"\nFold {f['fold']} ({f['test_period']}):")
        print(f"  • Model Accuracy: {f['accuracy'] * 100:.1f}%")
        print(f"  • Strategy Sharpe: {f['sharpe']:.2f}")
        print(f"  • Total Return: {f['return'] * 100:.2f}%")
        print(f"  • Win Rate: {f['win_rate'] * 100:.1f}% (N={f['trades']})")
        print(f"  • Max Drawdown: {f['max_dd'] * 100:.2f}%")

    agg = results["aggregate"]
    print("\n" + "=" * 60)
    print("AGGREGATE METRICS (Out-of-Sample)")
    print("=" * 60)
    print(f"🏆 Average Accuracy:  {agg['avg_accuracy'] * 100:.2f}%")
    print(f"📈 Total OOS Sharpe:  {agg['total_oos_sharpe']:.2f}")
    print(f"💰 Average Return:    {agg['avg_return'] * 100:.2f}%")
    print(f"🎯 Average Win Rate:  {agg['avg_win_rate'] * 100:.2f}%")
    print(f"⚖️ Profit Factor:     {agg['avg_profit_factor']:.2f}")
    print(f"🛡️ Avg Max Drawdown: {agg['avg_max_drawdown'] * 100:.2f}%")
    print(f"🔄 Total Trades:      {agg['total_trades']}")
    print("=" * 60)
    
    print("\nDone.")

if __name__ == "__main__":
    main()
