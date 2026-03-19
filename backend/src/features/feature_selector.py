"""
Automated feature selection for ML trading models.

Methods:
  - Correlation-based redundancy removal
  - Mutual information ranking
  - Combined pipeline: remove redundant → rank → select top-N
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class FeatureSelector:
    """
    Pipeline: remove redundant features → rank by importance → select top-N.
    """

    def __init__(
        self,
        correlation_threshold: float = 0.95,
        top_n: int = 30,
        target_col: str = "Target_Direction",
    ):
        self.correlation_threshold = correlation_threshold
        self.top_n = top_n
        self.target_col = target_col
        self.selected_features_: List[str] = []

    # --------------------------------------------------
    # Step 1: Remove redundant (highly correlated) features
    # --------------------------------------------------

    def remove_redundant(self, df: pd.DataFrame, feature_cols: List[str]) -> List[str]:
        """Remove features with correlation above threshold."""

        corr_matrix = df[feature_cols].corr().abs()

        # Find highly correlated pairs
        to_remove = set()
        cols = corr_matrix.columns

        for i, col_i in enumerate(cols):
            if col_i in to_remove:
                continue
            for j in range(i + 1, len(cols)):
                if cols[j] in to_remove:
                    continue

                if corr_matrix.iloc[i, j] >= self.correlation_threshold:
                    # Keep the one more correlated with target
                    if self.target_col in df.columns:
                        corr_i = abs(df[col_i].corr(df[self.target_col]))
                        corr_j = abs(df[cols[j]].corr(df[self.target_col]))
                        drop = cols[j] if corr_i >= corr_j else cols[i]
                    else:
                        drop = cols[j]

                    to_remove.add(drop)

        kept = [c for c in feature_cols if c not in to_remove]
        logger.info(
            "Redundancy removal: %s → %s features (removed %s)",
            len(feature_cols),
            len(kept),
            len(to_remove),
        )

        return kept

    # --------------------------------------------------
    # Step 2: Rank features by mutual information
    # --------------------------------------------------

    def rank_by_mutual_information(
        self, df: pd.DataFrame, feature_cols: List[str]
    ) -> List[Tuple[str, float]]:
        """Rank features by mutual information with target."""
        from sklearn.feature_selection import mutual_info_classif

        if self.target_col not in df.columns:
            return [(c, 0.0) for c in feature_cols]

        X = df[feature_cols].values
        y = df[self.target_col].values

        # Clean
        X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)
        valid = ~np.isnan(y)
        X, y = X[valid], y[valid]

        if len(X) < 30:
            return [(c, 0.0) for c in feature_cols]

        mi_scores = mutual_info_classif(X, y, random_state=42, n_neighbors=5)

        ranked = sorted(zip(feature_cols, mi_scores), key=lambda x: x[1], reverse=True)

        return ranked

    # --------------------------------------------------
    # Step 3: Select top-N
    # --------------------------------------------------

    def select(
        self, df: pd.DataFrame, feature_cols: Optional[List[str]] = None
    ) -> List[str]:
        """
        Full pipeline: redundancy removal → MI ranking → top-N selection.

        Returns list of selected feature names.
        """
        if feature_cols is None:
            exclude = {
                "Target",
                "Target_Direction",
                self.target_col,
                "open",
                "high",
                "low",
                "close",
                "volume",
            }
            feature_cols = [c for c in df.columns if c not in exclude]

        # Step 1: Remove redundant
        non_redundant = self.remove_redundant(df, feature_cols)

        # Step 2: Rank
        ranked = self.rank_by_mutual_information(df, non_redundant)

        # Step 3: Top-N
        selected = [name for name, score in ranked[: self.top_n] if score > 0]

        # Ensure minimum features
        if len(selected) < 10 and len(non_redundant) >= 10:
            selected = non_redundant[: self.top_n]

        self.selected_features_ = selected

        logger.info("Feature selection: %s → %s features", len(feature_cols), len(selected))

        return selected

    def get_feature_report(
        self, df: pd.DataFrame, feature_cols: Optional[List[str]] = None
    ) -> dict:
        """Return detailed feature analysis report."""
        if feature_cols is None:
            exclude = {"Target", "Target_Direction", self.target_col}
            feature_cols = [c for c in df.columns if c not in exclude]

        non_redundant = self.remove_redundant(df, feature_cols)
        ranked = self.rank_by_mutual_information(df, non_redundant)

        return {
            "total_features": len(feature_cols),
            "after_redundancy_removal": len(non_redundant),
            "selected": len(self.selected_features_),
            "ranking": [
                {"feature": name, "mi_score": round(float(score), 6)}
                for name, score in ranked[:30]
            ],
        }
