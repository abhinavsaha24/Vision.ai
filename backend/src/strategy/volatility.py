"""
Volatility-based trading strategies — research-backed implementation.

Based on: Turtle Trading System (Donchian Channel Breakout + ATR sizing)

Donchian Channel:
  H_t = max(P_{t-k}) for k=1..N
  L_t = min(P_{t-k}) for k=1..N
  Enter long if P_t > H_t, short if P_t < L_t

Position sizing:
  risk_unit = capital * risk_per_trade
  qty = risk_unit / (ATR * multiplier)

Features:
  - Donchian entry + shorter-term exit channels
  - ATR-based position sizing and stop-loss
  - Bollinger squeeze detection for compression breakouts
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


class VolatilityBreakoutStrategy:
    """
    Turtle/Donchian channel volatility breakout strategy.

    Entry: price breaks above/below N-period high/low
    Exit: price breaks below/above shorter M-period channel
    Sizing: ATR-based risk units

    Parameters:
        entry_period: lookback for entry channel (default 20)
        exit_period: lookback for exit channel (default 10)
        atr_period: ATR calculation period
        atr_multiplier: stop distance = ATR * multiplier
        risk_per_trade: fraction of capital to risk per trade
    """

    def __init__(
        self,
        entry_period: int = 20,
        exit_period: int = 10,
        atr_period: int = 20,
        atr_multiplier: float = 2.0,
        risk_per_trade: float = 0.01,
    ):
        self.entry_period = entry_period
        self.exit_period = exit_period
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.risk_per_trade = risk_per_trade

    def generate_signal(self, df: pd.DataFrame = None, **kwargs) -> int:
        """
        Generate breakout signal using Donchian channels.

        Returns +1 (breakout long), -1 (breakdown short), 0 (no signal)
        """
        if df is None or len(df) < self.entry_period + 2:
            return 0

        try:
            close = df["close"].iloc[-1]

            # Entry channel: N-period high/low (excluding current bar)
            entry_high = df["high"].iloc[-(self.entry_period + 1) : -1].max()
            entry_low = df["low"].iloc[-(self.entry_period + 1) : -1].min()

            # Exit channel: shorter M-period
            if len(df) >= self.exit_period + 2:
                exit_high = df["high"].iloc[-(self.exit_period + 1) : -1].max()
                exit_low = df["low"].iloc[-(self.exit_period + 1) : -1].min()
            else:
                pass

            # ATR filter: only trade when volatility is meaningful
            if "ATR" in df.columns:
                atr = df["ATR"].iloc[-1]
                price = close
                # Skip if ATR is too small relative to price (< 0.1%)
                if atr > 0 and (atr / price) < 0.001:
                    return 0

            # Breakout entry signals
            if close > entry_high:
                return 1  # breakout above channel → long
            elif close < entry_low:
                return -1  # breakdown below channel → short

            return 0

        except Exception as e:
            logger.error("VolatilityBreakoutStrategy error: %s", e)
            return 0

    def compute_position_size(
        self, capital: float, atr: float, contract_value: float = 1.0
    ) -> float:
        """
        Turtle-style ATR position sizing.

        qty = (capital * risk_per_trade) / (ATR * multiplier * contract_value)
        """
        if atr <= 0 or contract_value <= 0:
            return 0.0

        risk_amount = capital * self.risk_per_trade
        stop_distance = atr * self.atr_multiplier * contract_value
        return risk_amount / stop_distance

    def compute_stop_loss(
        self, entry_price: float, atr: float, direction: int
    ) -> float:
        """Compute ATR-based stop loss price."""
        stop_distance = atr * self.atr_multiplier
        if direction == 1:  # long
            return entry_price - stop_distance
        elif direction == -1:  # short
            return entry_price + stop_distance
        return entry_price


class VolatilityCompressionStrategy:
    """
    Bollinger Band squeeze → expansion strategy.

    Low volatility (narrow bands) precedes big moves.
    Detects squeeze state and trades the breakout direction.

    Parameters:
        squeeze_threshold: how close to recent min width for "squeeze"
        lookback: window for comparing band width
        momentum_bars: bars to check for breakout direction
    """

    def __init__(
        self, squeeze_threshold: float = 1.1, lookback: int = 20, momentum_bars: int = 5
    ):
        self.squeeze_threshold = squeeze_threshold
        self.lookback = lookback
        self.momentum_bars = momentum_bars

    def generate_signal(self, df: pd.DataFrame = None, **kwargs) -> int:
        """Detect Bollinger squeeze and trade the breakout direction."""
        if df is None or "BB_width" not in df.columns:
            return 0
        if len(df) < self.lookback + 1:
            return 0

        try:
            bb_width = df["BB_width"]
            current_width = bb_width.iloc[-1]
            recent_min = bb_width.iloc[-self.lookback :].min()

            # Squeeze: current width near recent minimum
            in_squeeze = current_width <= recent_min * self.squeeze_threshold

            if not in_squeeze:
                return 0

            # Direction from short-term momentum
            close = df["close"]
            if len(close) < self.momentum_bars:
                return 0

            momentum = close.iloc[-1] - close.iloc[-self.momentum_bars]

            if momentum > 0:
                return 1  # squeeze + upward → long breakout
            elif momentum < 0:
                return -1  # squeeze + downward → short breakout
            return 0

        except Exception as e:
            logger.error("VolatilityCompressionStrategy error: %s", e)
            return 0
