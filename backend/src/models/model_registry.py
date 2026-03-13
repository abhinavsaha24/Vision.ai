"""
Model registry: tracks trained model versions with performance metadata.

Features:
  - Model versioning with timestamps
  - Performance metric tracking per version
  - Auto-rollback if new model underperforms
  - Registry persistence to disk
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class ModelVersion:
    """Metadata for a single model version."""
    version_id: str
    created_at: str
    model_name: str
    accuracy: float = 0.0
    cv_accuracy_mean: float = 0.0
    cv_accuracy_std: float = 0.0
    sharpe_ratio: float = 0.0
    n_train_samples: int = 0
    n_features: int = 0
    top_features: List[str] = field(default_factory=list)
    status: str = "active"  # active, archived, rolled_back
    notes: str = ""


class ModelRegistry:
    """
    Manages model versions with performance tracking.

    Stores metadata in a JSON registry file alongside model artifacts.
    Supports auto-rollback when a new model underperforms.
    """

    def __init__(self, model_dir: str = "models", max_versions: int = 10):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(exist_ok=True)
        self.max_versions = max_versions

        self.registry_path = self.model_dir / "registry.json"
        self.versions: List[ModelVersion] = []
        self.active_version: Optional[str] = None

        self._load_registry()

    # --------------------------------------------------
    # Registry persistence
    # --------------------------------------------------

    def _load_registry(self):
        """Load registry from disk."""
        if self.registry_path.exists():
            try:
                data = json.loads(self.registry_path.read_text())
                self.versions = [
                    ModelVersion(**v) for v in data.get("versions", [])
                ]
                self.active_version = data.get("active_version")
                logger.info(
                    f"Model registry loaded: {len(self.versions)} versions, "
                    f"active={self.active_version}"
                )
            except Exception as e:
                logger.warning(f"Failed to load registry: {e}")
                self.versions = []

    def _save_registry(self):
        """Persist registry to disk."""
        data = {
            "active_version": self.active_version,
            "versions": [asdict(v) for v in self.versions],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.registry_path.write_text(json.dumps(data, indent=2))

    # --------------------------------------------------
    # Version management
    # --------------------------------------------------

    def register_model(self, model_name: str, metrics: Dict,
                       feature_names: List[str] = None,
                       notes: str = "") -> ModelVersion:
        """
        Register a newly trained model version.

        Args:
            model_name: base name of the model files
            metrics: training metrics dict
            feature_names: list of feature names used
            notes: optional notes about this version

        Returns:
            The new ModelVersion
        """
        version_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        version = ModelVersion(
            version_id=version_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            model_name=model_name,
            accuracy=metrics.get("accuracy", 0),
            cv_accuracy_mean=metrics.get("cv_accuracy_mean", 0),
            cv_accuracy_std=metrics.get("cv_accuracy_std", 0),
            n_train_samples=metrics.get("n_train_samples", 0),
            n_features=len(feature_names) if feature_names else 0,
            top_features=(feature_names or [])[:10],
            status="active",
            notes=notes,
        )

        self.versions.append(version)
        self.active_version = version_id

        # Prune old versions
        if len(self.versions) > self.max_versions:
            old = self.versions[:-self.max_versions]
            self.versions = self.versions[-self.max_versions:]
            for v in old:
                v.status = "archived"

        self._save_registry()
        logger.info(f"Model registered: v{version_id} (accuracy={version.accuracy:.4f})")

        return version

    def should_rollback(self, new_metrics: Dict,
                        threshold: float = 0.02) -> bool:
        """
        Check if a new model underperforms the current active model.

        Args:
            new_metrics: metrics from the new model
            threshold: minimum accuracy improvement required

        Returns:
            True if rollback is recommended
        """
        if not self.versions:
            return False

        current = self.get_active_version()
        if current is None:
            return False

        new_acc = new_metrics.get("accuracy", 0)
        old_acc = current.accuracy

        if new_acc < old_acc - threshold:
            logger.warning(
                f"Model regression detected: new={new_acc:.4f} < "
                f"current={old_acc:.4f} (threshold={threshold})"
            )
            return True

        return False

    def rollback(self) -> Optional[ModelVersion]:
        """Rollback to the previous model version."""
        if len(self.versions) < 2:
            logger.warning("Cannot rollback: no previous version")
            return None

        current = self.versions[-1]
        current.status = "rolled_back"

        previous = self.versions[-2]
        previous.status = "active"
        self.active_version = previous.version_id

        self._save_registry()
        logger.info(f"Rolled back to v{previous.version_id}")
        return previous

    # --------------------------------------------------
    # Queries
    # --------------------------------------------------

    def get_active_version(self) -> Optional[ModelVersion]:
        """Get the currently active model version."""
        for v in reversed(self.versions):
            if v.version_id == self.active_version:
                return v
        return self.versions[-1] if self.versions else None

    def get_all_versions(self) -> List[Dict]:
        """Return all versions as serializable dicts."""
        return [asdict(v) for v in self.versions]

    def get_performance_history(self) -> List[Dict]:
        """Return accuracy history for all versions."""
        return [
            {
                "version": v.version_id,
                "accuracy": v.accuracy,
                "cv_accuracy": v.cv_accuracy_mean,
                "created_at": v.created_at,
                "status": v.status,
            }
            for v in self.versions
        ]
