import pandas as pd
import numpy as np
import warnings
import sys
import os
warnings.filterwarnings('ignore')

# Add project root to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.src.data.fetcher import DataFetcher
from backend.src.features.indicators import FeatureEngineer
from backend.src.features.alpha_features import compute_alpha_features

def main():
    print("Initializing Edge Discovery Engine...")
    fetcher = DataFetcher()
    engineer = FeatureEngineer()
    
    # Fetch a massive sample to find truth
    df = fetcher.fetch("BTC/USDT", timeframe="5m", limit=10000)
    
    print("Computing Institutional Features...")
    df = engineer.add_all_indicators(df, add_target=False)
    df = compute_alpha_features(df)
    df = df.dropna()
    
    # 10 bar forward return (50 minutes)
    df['fwd_ret_10'] = df['close'].pct_change(10).shift(-10)
    df = df.dropna(subset=['fwd_ret_10'])
    
    print("\n--- EDGE DISCOVERY MINING ---")
    print(f"Total valid bars analyzed: {len(df)}")
    print(f"Base Win Rate (>0%): {(df['fwd_ret_10'] > 0).mean():.2%}")
    print(f"Base Average Return: {df['fwd_ret_10'].mean():.4%}")
    print("-----------------------------------")
    
    def eval_edge(name, mask, direction=1):
        if mask.sum() == 0:
            print(f"[{name}] No setups found in sample.")
            return
            
        sub = df[mask]
        count = len(sub)
        
        if direction == 1:
            wr = (sub['fwd_ret_10'] > 0).mean()
            wr_big = (sub['fwd_ret_10'] > 0.005).mean()  # > 50 bps edge
            avg_ret = sub['fwd_ret_10'].mean()
        else:
            wr = (sub['fwd_ret_10'] < 0).mean()
            wr_big = (sub['fwd_ret_10'] < -0.005).mean() # < -50 bps edge
            avg_ret = -sub['fwd_ret_10'].mean()          # Invert for short
            
        print(f"[{'LONG' if direction==1 else 'SHORT'} | {name}]")
        print(f"  Count: {count} trades")
        print(f"  Win Rate: {wr:.2%} | High Conviction (>50bps): {wr_big:.2%}")
        print(f"  Average Return: {avg_ret:.4%}")
        print()

    # Define thresholds
    z_volatility = 1.5  # High volatility breakout
    z_accumulation = 1.0  # Accumulation threshold
    
    # LONG CONDITIONS
    l_vol = df['of_volume_delta_zscore'] > z_accumulation
    l_imb = df['of_ob_imbalance_zscore'] > z_accumulation
    breakout_up = (df['rg_vol_regime_change'] > z_volatility) & (df['close'] > df['open'])
    
    eval_edge("Volume Delta Spike", l_vol, 1)
    eval_edge("Imbalance Spike", l_imb, 1)
    eval_edge("Vol Breakout Up", breakout_up, 1)
    eval_edge("Breakout + Volume Delta", breakout_up & l_vol, 1)
    eval_edge("Breakout + Imbalance", breakout_up & l_imb, 1)
    eval_edge("THE GOD SETUP (Breakout+Vol+Imb)", breakout_up & l_vol & l_imb, 1)
    
    # SHORT CONDITIONS
    s_vol = df['of_volume_delta_zscore'] < -z_accumulation
    s_imb = df['of_ob_imbalance_zscore'] < -z_accumulation
    breakout_down = (df['rg_vol_regime_change'] > z_volatility) & (df['close'] < df['open'])

    eval_edge("Volume Delta Dump", s_vol, -1)
    eval_edge("Imbalance Dump", s_imb, -1)
    eval_edge("Vol Breakout Down", breakout_down, -1)
    eval_edge("Breakout + Volume Dump", breakout_down & s_vol, -1)
    eval_edge("Breakout + Imbalance Dump", breakout_down & s_imb, -1)
    eval_edge("THE GOD SETUP (Breakout+Vol+Imb)", breakout_down & s_vol & s_imb, -1)

if __name__ == "__main__":
    main()
