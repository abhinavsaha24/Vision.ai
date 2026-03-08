"""Backtesting module for strategy evaluation."""

from .engine import BacktestEngine, BacktestResult, Trade, probabilities_to_signals

__all__ = ["BacktestEngine", "BacktestResult", "Trade", "probabilities_to_signals"]
