from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.src.portfolio.edge_portfolio_allocator import AllocatorConfig, EdgePortfolioAllocator


@dataclass
class AllocationInput:
    edges: list[dict[str, Any]]


@dataclass
class AllocationOutput:
    positions: dict[str, float]
    meta: dict[str, Any]


class PortfolioAllocator:
    """Canonical allocator interface for production pipeline.

    Input contract:
      - edges: list of registry-qualified signal edges with confidence and stats

    Output contract:
      - positions: target symbol exposures in [-1, 1]
      - meta: allocation diagnostics and concentration metrics
    """

    def __init__(self, config: AllocatorConfig | None = None):
        self._allocator = EdgePortfolioAllocator(config=config)

    def allocate(self, payload: AllocationInput) -> AllocationOutput:
        result = self._allocator.allocate(payload.edges)
        return AllocationOutput(
            positions=dict(result.get("positions", {})),
            meta=dict(result.get("meta", {})),
        )
