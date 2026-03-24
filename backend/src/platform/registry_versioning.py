from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json


class RegistryVersioning:
    def __init__(self, base_dir: str | Path = "data/registry_versions"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def make_version_tag() -> str:
        return datetime.now(timezone.utc).strftime("v%Y%m%d%H%M%S")

    def persist(self, registry_payload: dict[str, Any], diagnostics: dict[str, Any] | None = None) -> dict[str, str]:
        version = str(registry_payload.get("active_version") or self.make_version_tag())
        registry_payload["active_version"] = version
        registry_payload["generated_at"] = datetime.now(timezone.utc).isoformat()

        reg_path = self.base_dir / f"edge_registry_{version}.json"
        diag_path = self.base_dir / f"diagnostics_{version}.json"

        reg_path.write_text(json.dumps(registry_payload, indent=2), encoding="utf-8")
        if diagnostics is not None:
            diag_path.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")

        latest_path = self.base_dir / "LATEST_VERSION.txt"
        latest_path.write_text(version, encoding="utf-8")
        out = {
            "version": version,
            "registry": str(reg_path),
            "latest": str(latest_path),
        }
        if diagnostics is not None:
            out["diagnostics"] = str(diag_path)
        return out
