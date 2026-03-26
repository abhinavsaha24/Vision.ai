"""
Predictor v2: orchestrates data → alpha features → AlphaModel → signal pipeline.

Replaces the old ModelTrainer-based predictor with the new AlphaModel
that uses LightGBM+XGBoost ensemble with calibrated probabilities.

Features:
  - Alpha feature computation (order flow, volume, regime, stats)
  - Derivatives data integration (funding rate, OI)
  - Sentiment data integration (CryptoPanic)
  - Regime-aware confidence adjustment
  - Calibrated probability output
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np

from backend.src.data.fetcher import DataFetcher
from backend.src.features.indicators import FeatureEngineer
from backend.src.features.alpha_features import (
    compute_alpha_features,
    get_alpha_feature_names,
)
from backend.src.models.alpha_model import AlphaModel, AlphaModelConfig
from backend.src.models.regime_detector import MarketRegimeDetector

logger = logging.getLogger(__name__)

# Optional data feeds — degrade gracefully if unavailable
_derivatives_feed = None
_sentiment_feed = None

try:
    from backend.src.data.derivatives_feed import DerivativesFeed
    _derivatives_feed = DerivativesFeed()
except Exception as e:
    logger.info("Derivatives feed not available: %s", e)

try:
    from backend.src.data.sentiment_feed import SentimentFeed
    _sentiment_feed = SentimentFeed()
except Exception as e:
    logger.info("Sentiment feed not available: %s", e)


class Predictor:
    """Full prediction pipeline: fetch → features → predict → signal."""

    def __init__(self, model_path: Optional[str] = None):
        self.fetcher = DataFetcher()
        self.engineer = FeatureEngineer()
        self.regime_detector = MarketRegimeDetector()
        self.alpha_model = AlphaModel()

        self._model_loaded = False
        if model_path:
            try:
                self.alpha_model.load(model_path)
                self._model_loaded = True
                logger.info("Predictor loaded AlphaModel from: %s", model_path)
            except Exception as e:
                logger.warning("AlphaModel not loaded: %s", e)

    # ------------------------------------------------------------------
    # Heuristic predictor — used when no trained ML model is available
    # ------------------------------------------------------------------

    def _heuristic_predict(self, df, sentiment_score: float = 0.0) -> float:
        """
        Compute a probability from alpha features when no ML model is loaded.

        Uses 12 alpha features across 5 categories:
          - Order flow (volume delta, OB imbalance, spread)
          - Volume intelligence (smart money, volume-weighted momentum)
          - Regime (efficiency, cross-TF agreement, vol breakout)
          - Statistical edge (momentum Sharpe, tail ratio)
          - Sentiment (external score)

        Returns a calibrated probability in [0.05, 0.95] via sigmoid.
        """
        raw_score = 0.0

        # ---- ORDER FLOW (combined weight ~35%) ----

        # 1. Volume delta z-score (strongest microstructure signal)
        if "of_volume_delta_zscore" in df.columns:
            vd = float(df["of_volume_delta_zscore"].iloc[-1])
            raw_score += np.clip(vd * 0.10, -0.25, 0.25)

        # 2. Order book imbalance
        if "of_ob_imbalance" in df.columns:
            obi = float(df["of_ob_imbalance"].iloc[-1])
            raw_score += np.clip(obi * 0.12, -0.20, 0.20)

        # 3. Bid-ask spread (Corwin-Schultz) -- narrow spread = conviction
        if "of_spread_cs" in df.columns:
            spread = float(df["of_spread_cs"].iloc[-1])
            # Low spread amplifies signal; high spread dampens it
            spread_factor = max(0.5, 1.0 - spread * 20.0)
            raw_score *= spread_factor

        # ---- VOLUME INTELLIGENCE (combined weight ~20%) ----

        # 4. Smart money flow divergence
        if "vi_smart_money_flow" in df.columns:
            smf = float(df["vi_smart_money_flow"].iloc[-1])
            raw_score += np.clip(smf * 3.0, -0.15, 0.15)

        # 5. Volume-weighted momentum
        if "vi_vw_momentum_10" in df.columns:
            vm = float(df["vi_vw_momentum_10"].iloc[-1])
            raw_score += np.clip(vm * 4.0, -0.15, 0.15)

        # ---- REGIME & STRUCTURE (combined weight ~25%) ----

        # 6. Market efficiency ratio (trending vs noise)
        if "rg_efficiency_20" in df.columns:
            eff = float(df["rg_efficiency_20"].iloc[-1])
            raw_score += np.clip((eff - 0.25) * 0.3, -0.10, 0.10)

        # 7. Cross-timeframe momentum agreement
        if "rg_tf_agreement" in df.columns:
            tfa = float(df["rg_tf_agreement"].iloc[-1])
            raw_score += np.clip(tfa * 0.15, -0.18, 0.18)

        # 8. Volatility breakout (vol term structure spike)
        if "rg_vol_term_5_20" in df.columns:
            vt = float(df["rg_vol_term_5_20"].iloc[-1])
            if vt > 1.5:
                # Breakout: amplify existing directional bias
                raw_score *= 1.3
            elif vt > 2.0:
                raw_score *= 1.5

        # ---- STATISTICAL EDGE (combined weight ~10%) ----

        # 9. Momentum Sharpe (is the trend statistically significant?)
        if "st_momentum_sharpe_10" in df.columns:
            ms = float(df["st_momentum_sharpe_10"].iloc[-1])
            raw_score += np.clip(ms * 0.05, -0.12, 0.12)

        # 10. Tail ratio (upside vs downside distribution weight)
        if "st_tail_ratio" in df.columns:
            tr = float(df["st_tail_ratio"].iloc[-1])
            raw_score += np.clip((tr - 1.0) * 0.05, -0.08, 0.08)

        # ---- DERIVATIVES (weight ~5%) ----

        # 11. Funding rate (contrarian -- extreme funding = reversal)
        if "dr_funding_extreme" in df.columns:
            fe = float(df["dr_funding_extreme"].iloc[-1])
            if fe > 0.5 and "dr_funding_rate" in df.columns:
                fr = float(df["dr_funding_rate"].iloc[-1])
                raw_score -= np.clip(fr * 60.0, -0.08, 0.08)  # Contrarian

        # ---- SENTIMENT (weight ~5%) ----

        # 12. External sentiment score
        if abs(sentiment_score) > 0.05:
            raw_score += np.clip(sentiment_score * 0.15, -0.10, 0.10)

        # ---- CALIBRATION via sigmoid ----
        # Sigmoid maps raw_score to (0, 1), centered at 0.5
        # Scale factor of 4.0 gives: score=0.5 -> P=0.88, score=-0.5 -> P=0.12
        probability = 1.0 / (1.0 + np.exp(-raw_score * 4.0))

        # Clip to [0.05, 0.95] to prevent degenerate certainty
        probability = float(np.clip(probability, 0.05, 0.95))

        return probability

    def predict_symbol(self, symbol: str = "BTC/USDT", horizon: int = 5) -> List[Dict]:
        """
        Generate predictions for a symbol.

        Returns list of prediction dicts:
        [
            {step, direction, probability, confidence, regime}
        ]
        """
        try:
            # 1. Fetch market data
            df = self.fetcher.fetch(symbol)

            if df is None or df.empty:
                raise ValueError("No market data fetched")

            # 2. Generate features (includes alpha features via transform pipeline)
            df = self.engineer.add_all_indicators(df, add_target=False)

            # 2b. Compute alpha features for heuristic/ML predictor
            try:
                df = compute_alpha_features(df)
            except Exception as e:
                logger.warning("Alpha feature computation failed: %s", e)

            df = df.dropna()

            if len(df) < 50:
                raise ValueError(f"Not enough data ({len(df)} rows)")

            # 3. Detect regime
            regime = self.regime_detector.get_regime(df)

            # 4. Get volatility
            volatility = (
                float(df["volatility_20"].iloc[-1])
                if "volatility_20" in df.columns
                else 0.0
            )

            # 5. Run model prediction (ML or heuristic fallback)
            if not self._model_loaded:
                # Heuristic prediction from alpha features
                p = self._heuristic_predict(df)
                logger.info(
                    "Heuristic prediction for %s: P=%.4f (no ML model loaded)",
                    symbol, p,
                )

                base_confidence = abs(p - 0.5) * 2
                vol_penalty = max(0.5, 1.0 - volatility * 10)
                confidence = base_confidence * vol_penalty

                if p >= 0.60:
                    direction = "UP"
                elif p <= 0.40:
                    direction = "DOWN"
                else:
                    direction = "HOLD"

                return [
                    {
                        "step": i,
                        "direction": direction,
                        "probability": round(p, 4),
                        "confidence": round(confidence, 4),
                        "regime": regime.get("label", "unknown"),
                    }
                    for i in range(1, horizon + 1)
                ]

            # Get alpha feature columns
            alpha_cols = get_alpha_feature_names(df)
            # Include all non-target columns for prediction
            exclude = {"Target", "Target_Direction", "Target_Actionable"}
            feature_cols = [c for c in df.columns if c not in exclude]

            # Ensure features match what the model expects
            model_features = self.alpha_model.feature_names
            if model_features:
                missing = set(model_features) - set(df.columns)
                if missing:
                    logger.warning("Missing features: %s — filling with 0", missing)
                    for col in missing:
                        df[col] = 0
                feature_cols = model_features

            X = df[feature_cols].values
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

            # Get calibrated probabilities
            probs = self.alpha_model.predict_proba(X)

            # 6. Build predictions
            predictions = []
            for i in range(1, min(horizon + 1, len(probs) + 1)):
                p = float(probs[-i])

                # Confidence = distance from 0.5, volatility-adjusted
                base_confidence = abs(p - 0.5) * 2  # [0, 1]
                vol_penalty = max(0.5, 1.0 - volatility * 10)
                confidence = base_confidence * vol_penalty

                # Direction with confidence threshold
                if p >= 0.60:
                    direction = "UP"
                elif p <= 0.40:
                    direction = "DOWN"
                else:
                    direction = "HOLD"

                predictions.append(
                    {
                        "step": i,
                        "direction": direction,
                        "probability": round(p, 4),
                        "confidence": round(confidence, 4),
                        "regime": regime.get("label", "unknown"),
                    }
                )

            return predictions

        except Exception as e:
            logger.error("Prediction error for %s: %s", symbol, e)
            return []

    def predict_with_features(
        self, df, feature_names: Optional[List[str]] = None
    ) -> np.ndarray:
        """
        Predict on pre-engineered DataFrame.
        Returns calibrated probabilities.
        """
        if not self._model_loaded:
            raise ValueError("No AlphaModel loaded")

        names = feature_names or self.alpha_model.feature_names
        X = df[names].values
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        return self.alpha_model.predict_proba(X)

    def get_sentiment_context(self, currencies: str = "BTC") -> Dict:
        """Get current sentiment features for display/logging."""
        if _sentiment_feed:
            try:
                return _sentiment_feed.get_sentiment_features(currencies)
            except Exception as e:
                logger.warning("Sentiment fetch failed: %s", e)
        return {"sent_score": 0.0, "sent_volume": 0.0, "sent_bullish_ratio": 0.5}

    def get_derivatives_context(self, symbol: str = "BTCUSDT") -> Dict:
        """Get current derivatives data for display/logging."""
        if _derivatives_feed:
            try:
                return {
                    "funding_rate": _derivatives_feed.get_current_funding(symbol),
                    "open_interest": _derivatives_feed.get_current_oi(symbol),
                }
            except Exception as e:
                logger.warning("Derivatives fetch failed: %s", e)
        return {"funding_rate": None, "open_interest": None}
