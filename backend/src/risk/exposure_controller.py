"""Exposure controls for concentration, gross/net limits, and regime throttling."""

from __future__ import annotations

from typing import Dict


class ExposureController:
    def __init__(
        self,
        max_gross: float = 2.0,
        max_net: float = 1.0,
        max_single_name: float = 0.15,
    ):
        self.max_gross = max_gross
        self.max_net = max_net
        self.max_single_name = max_single_name

    def evaluate(self, exposure: Dict) -> Dict:
        gross = float(exposure.get("gross", 0.0))
        net = float(exposure.get("net", 0.0))
        top_name = float(exposure.get("top_single_name", 0.0))

        limits_ok = (
            gross <= self.max_gross
            and abs(net) <= self.max_net
            and top_name <= self.max_single_name
        )

        return {
            "limits_ok": limits_ok,
            "gross": gross,
            "net": net,
            "top_single_name": top_name,
            "max_limits": {
                "gross": self.max_gross,
                "net": self.max_net,
                "single_name": self.max_single_name,
            },
            "recommended_scale": 1.0 if limits_ok else 0.5,
        }
