"""Strategy robustness and parameter sensitivity analysis."""

from __future__ import annotations

from itertools import product
from typing import Callable, Dict, List

import numpy as np
import pandas as pd


class StrategyRobustnessAnalyzer:
    """Evaluates robustness across perturbations and parameter sweeps."""

    @staticmethod
    def evaluate_noise_stability(
        returns: np.ndarray, n_trials: int = 200, noise_std: float = 0.001
    ) -> Dict:
        returns = np.asarray(returns, dtype=float)
        if len(returns) < 20:
            return {"error": "insufficient_returns"}

        sharpes = []
        totals = []
        for _ in range(n_trials):
            perturbed = returns + np.random.normal(0, noise_std, len(returns))
            sharpe = (
                float((perturbed.mean() / perturbed.std()) * np.sqrt(252))
                if perturbed.std() > 0
                else 0.0
            )
            total = float(np.prod(1 + perturbed) - 1)
            sharpes.append(sharpe)
            totals.append(total)

        return {
            "n_trials": n_trials,
            "sharpe_mean": float(np.mean(sharpes)),
            "sharpe_std": float(np.std(sharpes)),
            "return_mean": float(np.mean(totals)),
            "return_std": float(np.std(totals)),
            "robust_pass": bool(np.mean(sharpes) > 0 and np.std(sharpes) < 1.0),
        }

    @staticmethod
    def parameter_sensitivity(
        evaluator: Callable[[Dict], float],
        param_grid: Dict[str, List],
    ) -> Dict:
        keys = list(param_grid.keys())
        values = [param_grid[k] for k in keys]

        rows = []
        for combo in product(*values):
            params = {k: v for k, v in zip(keys, combo)}
            score = float(evaluator(params))
            rows.append({**params, "score": score})

        if not rows:
            return {"error": "empty_grid"}

        df = pd.DataFrame(rows)
        best_row = df.loc[df["score"].idxmax()].to_dict()

        return {
            "n_runs": int(len(df)),
            "best": best_row,
            "score_std": float(df["score"].std(ddof=0)),
            "score_mean": float(df["score"].mean()),
            "stable_region": bool(df["score"].std(ddof=0) < 0.5),
            "results": df.to_dict(orient="records"),
        }
