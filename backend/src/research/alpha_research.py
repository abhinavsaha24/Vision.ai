"""
Alpha research framework for quantitative analysis.

Tools:
  - FactorAnalyzer: Factor returns, IC (Information Coefficient), IR
  - CorrelationAnalyzer: Feature correlation and redundancy detection
  - MutualInformationRanker: Non-linear feature importance
  - SHAPExplainer: Model explainability via SHAP values
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ==================================================================
# Factor Analyzer
# ==================================================================


class FactorAnalyzer:
    """Analyze alpha factor quality: IC, IR, factor returns."""

    def compute_ic(self, factor_values: pd.Series, forward_returns: pd.Series) -> float:
        """
        Compute Information Coefficient (rank correlation between factor and forward returns).
        """
        valid = pd.DataFrame({"f": factor_values, "r": forward_returns}).dropna()
        if len(valid) < 10:
            return 0.0
        return float(valid["f"].corr(valid["r"], method="spearman"))

    def compute_ic_series(
        self, df: pd.DataFrame, factor_col: str, return_col: str, window: int = 20
    ) -> pd.Series:
        """Rolling IC over time."""
        ic_values = []
        for i in range(window, len(df)):
            chunk = df.iloc[i - window : i]
            ic = self.compute_ic(chunk[factor_col], chunk[return_col])
            ic_values.append(ic)

        return pd.Series(ic_values, index=df.index[window:])

    def compute_ir(self, ic_series: pd.Series) -> float:
        """Information Ratio = mean(IC) / std(IC)."""
        if len(ic_series) < 5 or ic_series.std() == 0:
            return 0.0
        return float(ic_series.mean() / ic_series.std())

    def analyze_factor(
        self, df: pd.DataFrame, factor_col: str, return_col: str = "returns"
    ) -> Dict:
        """Full factor analysis."""
        if factor_col not in df.columns or return_col not in df.columns:
            return {"error": f"Column not found: {factor_col} or {return_col}"}

        ic = self.compute_ic(df[factor_col], df[return_col])
        ic_series = self.compute_ic_series(df, factor_col, return_col)
        ir = self.compute_ir(ic_series)

        # Factor quintile returns
        quintile_returns = self._quintile_returns(df, factor_col, return_col)

        return {
            "factor": factor_col,
            "ic": round(ic, 4),
            "ir": round(ir, 4),
            "ic_mean": round(float(ic_series.mean()), 4),
            "ic_std": round(float(ic_series.std()), 4),
            "quintile_returns": quintile_returns,
        }

    def _quintile_returns(
        self, df: pd.DataFrame, factor_col: str, return_col: str
    ) -> Dict:
        """Compute average return per factor quintile."""
        valid = df[[factor_col, return_col]].dropna()
        if len(valid) < 25:
            return {}

        valid["quintile"] = pd.qcut(
            valid[factor_col], q=5, labels=False, duplicates="drop"
        )
        result = valid.groupby("quintile")[return_col].mean()

        return {f"Q{int(k) + 1}": round(float(v), 6) for k, v in result.items()}


# ==================================================================
# Correlation Analyzer
# ==================================================================


class CorrelationAnalyzer:
    """Analyze feature correlations and detect redundancy."""

    def compute_correlation_matrix(
        self, df: pd.DataFrame, feature_cols: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """Compute correlation matrix."""
        if feature_cols:
            return df[feature_cols].corr()
        return df.select_dtypes(include=[np.number]).corr()

    def find_redundant_features(
        self,
        df: pd.DataFrame,
        threshold: float = 0.9,
        feature_cols: Optional[List[str]] = None,
    ) -> List[tuple]:
        """Find highly correlated feature pairs."""
        corr = self.compute_correlation_matrix(df, feature_cols)

        redundant = []
        cols = corr.columns
        for i, col_i in enumerate(cols):
            for j in range(i + 1, len(cols)):
                if abs(corr.iloc[i, j]) >= threshold:
                    redundant.append(
                        (col_i, cols[j], round(float(corr.iloc[i, j]), 4))
                    )

        return sorted(redundant, key=lambda x: abs(x[2]), reverse=True)

    def suggest_feature_removal(
        self, df: pd.DataFrame, threshold: float = 0.9, target_col: str = "returns"
    ) -> List[str]:
        """Suggest which features to remove (keep the one more correlated with target)."""
        redundant = self.find_redundant_features(df, threshold)
        to_remove = set()

        for f1, f2, _ in redundant:
            if f1 in to_remove or f2 in to_remove:
                continue

            if target_col in df.columns:
                corr1 = abs(df[f1].corr(df[target_col]))
                corr2 = abs(df[f2].corr(df[target_col]))
                to_remove.add(f2 if corr1 > corr2 else f1)
            else:
                to_remove.add(f2)

        return list(to_remove)


# ==================================================================
# Mutual Information Ranker
# ==================================================================


class MutualInformationRanker:
    """Non-linear feature importance using mutual information."""

    def rank_features(
        self, X: pd.DataFrame, y: pd.Series, top_n: int = 20
    ) -> Dict[str, float]:
        """
        Rank features by mutual information with target.

        Uses sklearn's mutual_info_classif for classification targets.
        """
        from sklearn.feature_selection import (mutual_info_classif,
                                               mutual_info_regression)

        valid_mask = ~(X.isna().any(axis=1) | y.isna())
        X_clean = X[valid_mask].values
        y_clean = y[valid_mask].values

        if len(X_clean) < 30:
            return {}

        # Detect if classification or regression
        unique_y = len(np.unique(y_clean))
        if unique_y <= 10:
            mi = mutual_info_classif(X_clean, y_clean, random_state=42)
        else:
            mi = mutual_info_regression(X_clean, y_clean, random_state=42)

        importance = dict(zip(X.columns, mi))
        sorted_imp = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))

        return {k: round(float(v), 6) for k, v in list(sorted_imp.items())[:top_n]}


# ==================================================================
# SHAP Explainer
# ==================================================================


class SHAPExplainer:
    """Model explainability using SHAP values."""

    def __init__(self):
        self._shap_available = False
        try:
            pass

            self._shap_available = True
        except ImportError:
            logger.warning("shap not installed — SHAP explainability unavailable")

    def explain(
        self, model, X: np.ndarray, feature_names: List[str], n_samples: int = 100
    ) -> Dict:
        """
        Compute SHAP values for a model.

        Args:
            model: trained sklearn/xgboost/lightgbm model
            X: scaled feature matrix
            feature_names: list of feature names
            n_samples: number of samples to explain

        Returns:
            {"feature_importance": {name: mean_abs_shap}}
        """
        if not self._shap_available:
            return {"error": "shap not installed"}

        import shap

        # Use subset for speed
        X_sub = X[:n_samples] if len(X) > n_samples else X

        try:
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_sub)

            # For binary classification, shap_values may be a list
            if isinstance(shap_values, list):
                shap_values = shap_values[1]  # class 1

            mean_abs_shap = np.abs(shap_values).mean(axis=0)

            importance = {
                name: round(float(val), 6)
                for name, val in zip(feature_names, mean_abs_shap)
            }

            sorted_imp = dict(
                sorted(importance.items(), key=lambda x: x[1], reverse=True)
            )

            return {"feature_importance": sorted_imp}

        except Exception as e:
            logger.error("SHAP failed: %s", e)
            return {"error": str(e)}
