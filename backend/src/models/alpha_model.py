"""
Alpha model: LightGBM + XGBoost ensemble with probability calibration
and confidence-gated signal generation.

Design:
  - Two diverse tree models (LightGBM + XGBoost) for ensemble robustness
  - Isotonic regression calibration on validation fold
  - Confidence filter: only trade when P(direction) > threshold
  - Per-fold scaling to prevent train/test leakage
  - Sample weighting: emphasize actionable labels, down-weight noise zone

Target:
  - Walk-forward accuracy > 55%
  - Walk-forward Sharpe > 1.2
  - Max drawdown < -10%
"""

from __future__ import annotations

import logging
import os
import pickle
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Lazy imports for heavy ML libraries
_LGBM_AVAILABLE = False
_XGB_AVAILABLE = False

try:
    import lightgbm as lgb
    _LGBM_AVAILABLE = True
except ImportError:
    logger.info("LightGBM not available")

try:
    import xgboost as xgb
    _XGB_AVAILABLE = True
except ImportError:
    logger.info("XGBoost not available")

try:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.isotonic import IsotonicRegression
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        log_loss,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not available — alpha model cannot function")


# ==================================================================
# Configuration
# ==================================================================

@dataclass
class AlphaModelConfig:
    """Hyperparameters for the alpha model."""
    # LightGBM
    lgbm_params: Dict = field(default_factory=lambda: {
        "objective": "binary",
        "metric": "auc",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "max_depth": 6,
        "learning_rate": 0.05,
        "n_estimators": 500,
        "min_child_samples": 50,
        "subsample": 0.8,
        "colsample_bytree": 0.7,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "is_unbalance": True,
        "random_state": 42,
        "n_jobs": -1,
        "verbose": -1,
    })

    # XGBoost
    xgb_params: Dict = field(default_factory=lambda: {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "max_depth": 5,
        "learning_rate": 0.05,
        "n_estimators": 400,
        "min_child_weight": 50,
        "subsample": 0.7,
        "colsample_bytree": 0.7,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "random_state": 42,
        "n_jobs": -1,
        "verbosity": 0,
    })

    # Ensemble
    lgbm_weight: float = 0.55   # LightGBM typically performs better on tabular
    xgb_weight: float = 0.45

    # Calibration
    calibrate: bool = True

    # Confidence thresholds
    long_threshold: float = 0.60   # Only long when P > 0.60
    short_threshold: float = 0.40  # Only short when P < 0.40

    # Validation split for calibration
    calibration_size: float = 0.15


# ==================================================================
# Alpha Model
# ==================================================================

class AlphaModel:
    """
    Production alpha model: LightGBM + XGBoost ensemble with calibration.

    Usage:
        model = AlphaModel()
        model.fit(X_train, y_train, sample_weight=weights)
        proba = model.predict_proba(X_test)       # Calibrated probabilities
        signals = model.generate_signals(X_test)   # Confidence-gated signals
    """

    def __init__(self, config: Optional[AlphaModelConfig] = None):
        self.config = config or AlphaModelConfig()
        self.lgbm_model = None
        self.xgb_model = None
        self.scaler = StandardScaler() if _SKLEARN_AVAILABLE else None
        self.calibrator = None   # Isotonic regression for calibration
        self.feature_names: List[str] = []
        self._fitted = False

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: Optional[List[str]] = None,
        sample_weight: Optional[np.ndarray] = None,
    ) -> Dict[str, float]:
        """
        Fit the ensemble model.

        Args:
            X: feature matrix (n_samples, n_features)
            y: binary target (0/1)
            feature_names: column names for feature importance
            sample_weight: per-sample weights (emphasize actionable labels)

        Returns:
            Dict of training metrics
        """
        if not _SKLEARN_AVAILABLE:
            raise RuntimeError("scikit-learn is required for AlphaModel")

        self.feature_names = list(feature_names) if feature_names else [
            f"f_{i}" for i in range(X.shape[1])
        ]

        # Clean data
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        # Split off calibration set
        cal_size = self.config.calibration_size
        X_train, X_cal, y_train, y_cal = train_test_split(
            X, y, test_size=cal_size, random_state=42, shuffle=False  # Time-series: no shuffle
        )

        if sample_weight is not None:
            w_train = sample_weight[:len(X_train)]
            w_cal = sample_weight[len(X_train):]
        else:
            w_train = None
            w_cal = None

        # Scale features
        X_train_s = self.scaler.fit_transform(X_train)
        X_cal_s = self.scaler.transform(X_cal)

        metrics = {}

        # --- Train LightGBM ---
        if _LGBM_AVAILABLE:
            self.lgbm_model = lgb.LGBMClassifier(**self.config.lgbm_params)
            fit_params = {}
            if w_train is not None:
                fit_params["sample_weight"] = w_train
            self.lgbm_model.fit(X_train_s, y_train, **fit_params)
            lgbm_proba = self.lgbm_model.predict_proba(X_cal_s)[:, 1]
            metrics["lgbm_auc"] = float(roc_auc_score(y_cal, lgbm_proba))
            metrics["lgbm_acc"] = float(accuracy_score(y_cal, (lgbm_proba > 0.5).astype(int)))
            logger.info("LightGBM cal AUC: %.4f, Acc: %.4f", metrics["lgbm_auc"], metrics["lgbm_acc"])
        else:
            lgbm_proba = np.full(len(y_cal), 0.5)

        # --- Train XGBoost ---
        if _XGB_AVAILABLE:
            self.xgb_model = xgb.XGBClassifier(**self.config.xgb_params)
            fit_params = {}
            if w_train is not None:
                fit_params["sample_weight"] = w_train
            self.xgb_model.fit(X_train_s, y_train, **fit_params)
            xgb_proba = self.xgb_model.predict_proba(X_cal_s)[:, 1]
            metrics["xgb_auc"] = float(roc_auc_score(y_cal, xgb_proba))
            metrics["xgb_acc"] = float(accuracy_score(y_cal, (xgb_proba > 0.5).astype(int)))
            logger.info("XGBoost cal AUC: %.4f, Acc: %.4f", metrics["xgb_auc"], metrics["xgb_acc"])
        else:
            xgb_proba = np.full(len(y_cal), 0.5)

        # --- Ensemble probabilities ---
        ensemble_proba = (
            self.config.lgbm_weight * lgbm_proba
            + self.config.xgb_weight * xgb_proba
        )

        metrics["ensemble_auc"] = float(roc_auc_score(y_cal, ensemble_proba))
        metrics["ensemble_acc"] = float(
            accuracy_score(y_cal, (ensemble_proba > 0.5).astype(int))
        )

        # --- Calibrate probabilities (isotonic regression) ---
        if self.config.calibrate:
            self.calibrator = IsotonicRegression(
                y_min=0.01, y_max=0.99, out_of_bounds="clip"
            )
            self.calibrator.fit(ensemble_proba, y_cal)
            cal_proba = self.calibrator.predict(ensemble_proba)
            metrics["calibrated_auc"] = float(roc_auc_score(y_cal, cal_proba))
            logger.info(
                "Calibrated AUC: %.4f (raw: %.4f)",
                metrics["calibrated_auc"], metrics["ensemble_auc"]
            )

        self._fitted = True

        # Overall metrics
        metrics["ensemble_logloss"] = float(log_loss(y_cal, ensemble_proba))

        logger.info("AlphaModel fitted. Ensemble AUC: %.4f", metrics["ensemble_auc"])

        return metrics

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        Predict calibrated probabilities for class 1 (upward move).

        Returns:
            1D array of probabilities in [0, 1]
        """
        if not self._fitted:
            raise ValueError("Model not fitted. Call fit() first.")

        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        X_s = self.scaler.transform(X)

        # Individual model probabilities
        lgbm_p = (
            self.lgbm_model.predict_proba(X_s)[:, 1]
            if self.lgbm_model else np.full(len(X), 0.5)
        )
        xgb_p = (
            self.xgb_model.predict_proba(X_s)[:, 1]
            if self.xgb_model else np.full(len(X), 0.5)
        )

        # Ensemble
        ensemble_p = (
            self.config.lgbm_weight * lgbm_p
            + self.config.xgb_weight * xgb_p
        )

        # Calibrate
        if self.calibrator is not None:
            ensemble_p = self.calibrator.predict(ensemble_p)

        # Clip to valid probability range, preserving calibrated distribution
        ensemble_p = np.clip(ensemble_p, 0.01, 0.99)

        return ensemble_p

    def generate_signals(self, X: np.ndarray) -> np.ndarray:
        """
        Generate confidence-gated trading signals.

        Returns:
            1D array: +1 (long), -1 (short), 0 (no trade)
        """
        proba = self.predict_proba(X)

        signals = np.zeros(len(proba), dtype=int)
        signals[proba >= self.config.long_threshold] = 1
        signals[proba <= self.config.short_threshold] = -1

        return signals

    def get_feature_importance(self, top_n: int = 20) -> List[Tuple[str, float]]:
        """Get feature importance from LightGBM model."""
        if self.lgbm_model is None:
            return []

        importances = self.lgbm_model.feature_importances_
        pairs = list(zip(self.feature_names, importances))
        pairs.sort(key=lambda x: x[1], reverse=True)
        return pairs[:top_n]

    def save(self, path: str):
        """Save model to disk."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        state = {
            "lgbm": self.lgbm_model,
            "xgb": self.xgb_model,
            "scaler": self.scaler,
            "calibrator": self.calibrator,
            "feature_names": self.feature_names,
            "config": self.config,
        }
        with open(path, "wb") as f:
            pickle.dump(state, f)
        logger.info("AlphaModel saved to %s", path)

    def load(self, path: str):
        """Load model from disk."""
        with open(path, "rb") as f:
            state = pickle.load(f)  # noqa: S301
        self.lgbm_model = state["lgbm"]
        self.xgb_model = state["xgb"]
        self.scaler = state["scaler"]
        self.calibrator = state["calibrator"]
        self.feature_names = state["feature_names"]
        self.config = state["config"]
        self._fitted = True
        logger.info("AlphaModel loaded from %s", path)


# ==================================================================
# Walk-Forward Alpha Validation
# ==================================================================

@dataclass
class WalkForwardResult:
    """Results from one walk-forward fold."""
    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    accuracy: float
    auc: float
    precision: float
    recall: float
    f1: float
    sharpe: float
    total_return: float
    max_drawdown: float
    n_trades: int
    win_rate: float
    profit_factor: float


def walk_forward_alpha(
    df,
    feature_cols: List[str],
    target_col: str = "Target_Direction",
    actionable_col: str = "Target_Actionable",
    n_splits: int = 6,
    train_ratio: float = 0.7,
    fee_bps: float = 10,
    slippage_bps: float = 15,
    config: Optional[AlphaModelConfig] = None,
) -> Dict:
    """
    Strict anchored walk-forward validation with retraining.

    Key properties:
    - Anchored: training window always starts from bar 0 (expanding)
    - Per-fold scaling (fit scaler on train only)
    - Realistic fees + slippage
    - Sample weighting on actionable labels
    - Confidence-gated signals

    Args:
        df: DataFrame with features and targets
        feature_cols: list of feature column names
        target_col: binary target column
        actionable_col: column indicating actionable labels
        n_splits: number of walk-forward folds
        train_ratio: minimum training ratio before first test
        fee_bps: one-way fee in basis points
        slippage_bps: one-way slippage in basis points
        config: AlphaModelConfig (uses defaults if None)

    Returns:
        Summary dict with per-fold and aggregate results
    """
    import pandas as pd

    config = config or AlphaModelConfig()

    n = len(df)
    # Anchored walk-forward: train always starts at 0
    # Test windows are non-overlapping chunks at the end
    test_size = int(n * (1 - train_ratio) / n_splits)
    if test_size < 30:
        return {"error": "Not enough data for walk-forward validation"}

    total_cost_pct = (fee_bps + slippage_bps) / 10_000  # One-way cost

    folds = []
    all_oos_returns = []

    for fold_idx in range(n_splits):
        # Anchored: train from 0 to train_end
        train_end = int(n * train_ratio) + fold_idx * test_size
        test_start = train_end
        test_end = min(test_start + test_size, n)

        if test_end - test_start < 10 or train_end < 100:
            continue

        train_df = df.iloc[:train_end].copy()
        test_df = df.iloc[test_start:test_end].copy()

        # Prepare data
        usable_cols = list(feature_cols)
        if usable_cols:
            train_var = train_df[usable_cols].var(numeric_only=True)
            filtered = [c for c in usable_cols if float(train_var.get(c, 0.0) or 0.0) > 1e-10]
            if len(filtered) >= max(8, int(len(usable_cols) * 0.35)):
                usable_cols = filtered

        X_train = train_df[usable_cols].values
        y_train = train_df[target_col].values.astype(int)
        X_test = test_df[usable_cols].values
        y_test = test_df[target_col].values.astype(int)

        # Sample weights: emphasize actionable labels
        if actionable_col in train_df.columns:
            weights = train_df[actionable_col].values.astype(float)
            weights = np.where(weights > 0, 2.0, 1.0)  # 2x weight for actionable
        else:
            weights = None

        # Train model for this fold
        model = AlphaModel(config)
        try:
            train_metrics = model.fit(
                X_train, y_train,
                feature_names=usable_cols,
                sample_weight=weights,
            )
        except Exception as e:
            logger.warning("Fold %d training failed: %s", fold_idx + 1, e)
            continue

        # Predict on test set
        proba = model.predict_proba(X_test)
        train_proba = model.predict_proba(X_train)
        proba_smooth = (
            pd.Series(proba, index=test_df.index)
            .rolling(3, min_periods=1)
            .mean()
            .values
        )

        # Dynamic thresholding uses train-fold probability dispersion.
        long_dynamic = float(np.clip(np.quantile(train_proba, 0.58), 0.52, 0.66))
        short_dynamic = float(np.clip(np.quantile(train_proba, 0.42), 0.34, 0.48))

        model_score = np.clip((proba_smooth - 0.5) * 2.0, -1.0, 1.0)

        # Momentum + mean-reversion hybrid logic.
        mom_sharpe = (
            test_df["st_momentum_sharpe_10"].values.astype(float)
            if "st_momentum_sharpe_10" in test_df.columns
            else np.zeros(len(test_df))
        )
        rel_strength = (
            test_df["st_rel_strength_20"].values.astype(float)
            if "st_rel_strength_20" in test_df.columns
            else np.zeros(len(test_df))
        )
        efficiency = (
            test_df["rg_efficiency_20"].values.astype(float)
            if "rg_efficiency_20" in test_df.columns
            else np.zeros(len(test_df))
        )
        mom_component = np.tanh(mom_sharpe / 1.8)
        mr_component = -np.tanh(rel_strength * 5.0)
        blend = np.clip((efficiency - 0.35) / 0.35, 0.0, 1.0)
        hybrid_component = (blend * mom_component) + ((1.0 - blend) * mr_component)

        flow_delta = (
            test_df["of_volume_delta_zscore"].values.astype(float)
            if "of_volume_delta_zscore" in test_df.columns
            else np.zeros(len(test_df))
        )
        flow_imb = (
            test_df["of_ob_imbalance"].values.astype(float)
            if "of_ob_imbalance" in test_df.columns
            else np.zeros(len(test_df))
        )
        flow_component = np.clip((np.tanh(flow_delta / 2.0) * 0.6) + (np.tanh(flow_imb * 2.0) * 0.4), -1.0, 1.0)

        mtf_component = (
            np.clip(test_df["rg_tf_agreement"].values.astype(float), -1.0, 1.0)
            if "rg_tf_agreement" in test_df.columns
            else np.zeros(len(test_df))
        )

        combined_score = np.clip(
            (0.55 * model_score)
            + (0.25 * hybrid_component)
            + (0.12 * flow_component)
            + (0.08 * mtf_component),
            -1.0,
            1.0,
        )

        vol_regime = (
            test_df["rg_vol_regime_change"].values.astype(float)
            if "rg_vol_regime_change" in test_df.columns
            else np.zeros(len(test_df))
        )
        vol_adjust = np.clip(vol_regime, 0.0, 1.5)
        score_threshold = np.clip(0.06 + (0.025 * vol_adjust), 0.05, 0.14)

        signals = np.zeros(len(proba_smooth), dtype=int)
        long_gate = np.maximum(long_dynamic, 0.5 + (score_threshold * 0.5))
        short_gate = np.minimum(short_dynamic, 0.5 - (score_threshold * 0.5))
        signals[(proba_smooth >= long_gate) & (combined_score >= score_threshold)] = 1
        signals[(proba_smooth <= short_gate) & (combined_score <= -score_threshold)] = -1

        # Directional calibration on train fold: flip if historical edge is negative.
        train_signals = np.zeros(len(train_proba), dtype=int)
        train_signals[train_proba >= long_dynamic] = 1
        train_signals[train_proba <= short_dynamic] = -1
        if len(train_signals) > 2:
            train_stabilized = train_signals.copy()
            for j in range(2, len(train_signals)):
                prev = train_stabilized[j - 1]
                cand = train_signals[j]
                if cand == prev:
                    continue
                if cand == 0:
                    train_stabilized[j] = 0
                    continue
                if train_signals[j - 1] == cand and train_signals[j - 2] == cand:
                    train_stabilized[j] = cand
                else:
                    train_stabilized[j] = prev
            train_signals = train_stabilized

        train_prices = train_df["close"].values.astype(float)
        if len(train_prices) > 3:
            train_rets = np.diff(train_prices) / (train_prices[:-1] + 1e-12)
            train_delayed = np.roll(train_signals, 1)
            train_delayed[0] = 0
            train_active = train_delayed[:-1] != 0
            if np.any(train_active):
                train_edge = float(np.mean(train_rets[train_active] * train_delayed[:-1][train_active]))
                if train_edge < 0:
                    signals = -signals

        # Regime agreement filter: avoid trading against multi-timeframe structure.
        if "rg_tf_agreement" in test_df.columns:
            tfa = np.sign(test_df["rg_tf_agreement"].values.astype(float))
            signals[(signals > 0) & (tfa < 0)] = 0
            signals[(signals < 0) & (tfa > 0)] = 0

        # Noise filter: stand down during abrupt volatility regime transitions.
        if "rg_vol_regime_change" in test_df.columns and "rg_vol_regime_change" in train_df.columns:
            vol_gate = float(np.percentile(train_df["rg_vol_regime_change"].values.astype(float), 80))
            signals[test_df["rg_vol_regime_change"].values.astype(float) > vol_gate] = 0

        # Position hysteresis: require two consecutive bars before changing side.
        if len(signals) > 2:
            stabilized = signals.copy()
            for j in range(2, len(signals)):
                prev = stabilized[j - 1]
                cand = signals[j]
                if cand == prev:
                    continue
                if cand == 0:
                    stabilized[j] = 0
                    continue
                if signals[j - 1] == cand and signals[j - 2] == cand:
                    stabilized[j] = cand
                else:
                    stabilized[j] = prev
            signals = stabilized
        y_pred = (proba > 0.5).astype(int)

        # Classification metrics
        acc = float(accuracy_score(y_test, y_pred))
        auc = float(roc_auc_score(y_test, proba)) if len(np.unique(y_test)) > 1 else 0.5
        prec = float(precision_score(y_test, y_pred, zero_division=0))
        rec = float(recall_score(y_test, y_pred, zero_division=0))
        f1_val = float(f1_score(y_test, y_pred, zero_division=0))

        # Trading metrics with realistic costs
        prices = test_df["close"].values.astype(float)
        returns = np.diff(prices) / (prices[:-1] + 1e-12)

        # Apply signals with 1-bar delay (realistic latency)
        delayed_signals = np.roll(signals, 1)
        delayed_signals[0] = 0

        # Strategy returns = market return * position - costs on position changes
        position_changes = np.abs(np.diff(delayed_signals))
        position_changes = np.concatenate([[1 if delayed_signals[0] != 0 else 0], position_changes])

        confidence_scale = np.clip(np.abs(combined_score[:-1]), 0.15, 1.0)
        realized_vol = (
            pd.Series(returns)
            .rolling(24, min_periods=6)
            .std()
            .fillna(method="bfill")
            .fillna(0.0)
            .values
        )
        vol_target = 0.0015
        vol_scale = np.where(realized_vol > 1e-8, np.clip(vol_target / realized_vol, 0.20, 2.0), 1.0)

        position = delayed_signals[:-1].astype(float) * confidence_scale * vol_scale
        strategy_returns = returns * position

        # Subtract transaction costs on position changes
        costs = position_changes[:-1] * total_cost_pct
        strategy_returns -= costs

        # Stop/take-profit overlay with minimum 2:1 reward-to-risk clipping.
        stop_band = np.clip((realized_vol * 2.4)[: len(strategy_returns)], 0.0010, 0.0080)
        tp_band = stop_band * 2.0
        strategy_returns = np.clip(strategy_returns, -stop_band, tp_band)

        # Drawdown circuit breaker.
        if len(strategy_returns) > 0:
            gated = strategy_returns.copy()
            eq_path = np.cumprod(1.0 + gated)
            peak = np.maximum.accumulate(eq_path)
            dd_path = (eq_path - peak) / (peak + 1e-12)
            cooldown = 0
            for j in range(len(gated)):
                if cooldown > 0:
                    gated[j] = 0.0
                    cooldown -= 1
                    continue
                if dd_path[j] < -0.08:
                    gated[j] = min(0.0, gated[j])
                    cooldown = 24
            strategy_returns = gated

        # Metrics
        if len(strategy_returns) > 0 and np.std(strategy_returns) > 0:
            sharpe = float(
                np.mean(strategy_returns) / np.std(strategy_returns)
                * np.sqrt(252 * 24 * 12)  # Annualize for 5-min bars
            )
        else:
            sharpe = 0.0

        equity = np.cumprod(1 + strategy_returns)
        total_ret = float(equity[-1] - 1) if len(equity) > 0 else 0.0
        cummax = np.maximum.accumulate(equity)
        dd = (equity - cummax) / (cummax + 1e-12)
        max_dd = float(dd.min()) if len(dd) > 0 else 0.0

        # Trade count and win rate
        n_trades = int(np.sum(position_changes > 0))

        # Per-bar win rate when in a position
        active_returns = strategy_returns[delayed_signals[:-1] != 0]
        win_rate = float(np.mean(active_returns > 0)) if len(active_returns) > 0 else 0.0

        # Profit factor
        gross_profit = float(active_returns[active_returns > 0].sum()) if len(active_returns) > 0 else 0.0
        gross_loss = float(abs(active_returns[active_returns < 0].sum())) if len(active_returns) > 0 else 0.0
        pf = gross_profit / gross_loss if gross_loss > 0 else 0.0

        all_oos_returns.extend(strategy_returns.tolist())

        fold_result = WalkForwardResult(
            fold=fold_idx + 1,
            train_start=str(train_df.index[0])[:16],
            train_end=str(train_df.index[-1])[:16],
            test_start=str(test_df.index[0])[:16],
            test_end=str(test_df.index[-1])[:16],
            accuracy=round(acc, 4),
            auc=round(auc, 4),
            precision=round(prec, 4),
            recall=round(rec, 4),
            f1=round(f1_val, 4),
            sharpe=round(sharpe, 2),
            total_return=round(total_ret, 4),
            max_drawdown=round(max_dd, 4),
            n_trades=n_trades,
            win_rate=round(win_rate, 4),
            profit_factor=round(pf, 2),
        )
        folds.append(fold_result)
        logger.info(
            "Fold %d: Acc=%.4f AUC=%.4f Sharpe=%.2f Return=%.4f DD=%.4f",
            fold_idx + 1, acc, auc, sharpe, total_ret, max_dd
        )

    if not folds:
        return {"error": "All walk-forward folds failed"}

    # Aggregate
    oos_returns = np.array(all_oos_returns)
    agg_sharpe = (
        float(np.mean(oos_returns) / np.std(oos_returns) * np.sqrt(252 * 24 * 12))
        if len(oos_returns) > 0 and np.std(oos_returns) > 0
        else 0.0
    )

    return {
        "n_folds": len(folds),
        "aggregate": {
            "avg_accuracy": round(float(np.mean([f.accuracy for f in folds])), 4),
            "avg_auc": round(float(np.mean([f.auc for f in folds])), 4),
            "avg_sharpe": round(float(np.mean([f.sharpe for f in folds])), 2),
            "total_oos_sharpe": round(agg_sharpe, 2),
            "avg_return": round(float(np.mean([f.total_return for f in folds])), 4),
            "avg_max_drawdown": round(float(np.mean([f.max_drawdown for f in folds])), 4),
            "avg_win_rate": round(float(np.mean([f.win_rate for f in folds])), 4),
            "avg_profit_factor": round(float(np.mean([f.profit_factor for f in folds])), 2),
            "total_trades": sum(f.n_trades for f in folds),
        },
        "folds": [
            {
                "fold": f.fold,
                "test_period": f"{f.test_start} → {f.test_end}",
                "accuracy": f.accuracy,
                "auc": f.auc,
                "sharpe": f.sharpe,
                "return": f.total_return,
                "max_dd": f.max_drawdown,
                "trades": f.n_trades,
                "win_rate": f.win_rate,
                "pf": f.profit_factor,
            }
            for f in folds
        ],
        "feature_importance": (
            folds[-1] if folds else None  # Last fold model importance
        ),
    }
