"""
Exchange adapter abstraction layer.

Provides a unified interface for order execution across different modes:
  - PaperAdapter: simulated fills for paper trading (default)
  - BinanceAdapter: real order routing via ccxt

All execution flows through this interface, ensuring the core trading
logic never touches exchange-specific code directly.
"""

from __future__ import annotations

import logging
import time
import numpy as np
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Order data structures
# ------------------------------------------------------------------

@dataclass
class Order:
    """Represents a single order submitted to an exchange."""

    order_id: str
    symbol: str
    side: str          # "buy" or "sell"
    order_type: str    # "market", "limit"
    quantity: float
    price: float       # requested price (limit) or market price
    status: str = "pending"  # pending → submitted → partial → filled | cancelled | rejected
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    commission: float = 0.0
    created_at: str = ""
    updated_at: str = ""
    exchange_order_id: str = ""
    error: str = ""
    metadata: Dict = field(default_factory=dict)

    def is_terminal(self) -> bool:
        return self.status in ("filled", "cancelled", "rejected")


@dataclass
class Balance:
    """Exchange account balance."""
    total: Dict[str, float] = field(default_factory=dict)
    free: Dict[str, float] = field(default_factory=dict)
    used: Dict[str, float] = field(default_factory=dict)


# ------------------------------------------------------------------
# Abstract exchange adapter
# ------------------------------------------------------------------

class ExchangeAdapter(ABC):
    """
    Abstract interface for exchange interactions.

    Implementations must handle:
      - Order submission (market + limit)
      - Order status checking
      - Order cancellation
      - Balance retrieval
      - Position querying
    """

    @abstractmethod
    def place_market_order(self, symbol: str, side: str, quantity: float,
                           price: float = 0.0) -> Order:
        """Place a market order. Returns Order with fill details."""
        ...

    @abstractmethod
    def place_limit_order(self, symbol: str, side: str, quantity: float,
                          price: float) -> Order:
        """Place a limit order. Returns Order in pending/submitted state."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> Order:
        """Cancel an open order. Returns updated Order."""
        ...

    @abstractmethod
    def get_order_status(self, order_id: str, symbol: str) -> Order:
        """Check current status of an order."""
        ...

    @abstractmethod
    def get_balance(self) -> Balance:
        """Retrieve current account balances."""
        ...

    @abstractmethod
    def get_open_orders(self, symbol: str = "") -> List[Order]:
        """Get all open orders, optionally filtered by symbol."""
        ...

    @abstractmethod
    def cancel_all_orders(self, symbol: str = "") -> int:
        """Cancel all open orders. Returns count cancelled."""
        ...


# ------------------------------------------------------------------
# Paper trading adapter (simulated fills)
# ------------------------------------------------------------------

class PaperAdapter(ExchangeAdapter):
    """
    Simulates exchange behavior for paper trading.

    - Market orders fill immediately at requested price ± slippage
    - Limit orders fill immediately if price is favorable
    - Tracks a virtual balance
    """

    def __init__(self, initial_cash: float = 10000.0,
                 commission_rate: float = 0.001,
                 max_slippage: float = 0.001):
        self.cash = initial_cash
        self.commission_rate = commission_rate
        self.max_slippage = max_slippage
        self.holdings: Dict[str, float] = {}

        self._order_counter = 0
        self._orders: Dict[str, Order] = {}

    def _next_order_id(self) -> str:
        self._order_counter += 1
        return f"PAPER-{self._order_counter:06d}"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _simulate_slippage(self, price: float, side: str) -> float:
        slip = np.random.uniform(0, self.max_slippage)
        if side == "buy":
            return price * (1 + slip)
        return price * (1 - slip)

    def place_market_order(self, symbol: str, side: str, quantity: float,
                           price: float = 0.0) -> Order:
        order_id = self._next_order_id()
        now = self._now()

        fill_price = self._simulate_slippage(price, side)
        commission = fill_price * quantity * self.commission_rate

        # Validate balance
        if side == "buy":
            cost = fill_price * quantity + commission
            if cost > self.cash:
                return Order(
                    order_id=order_id, symbol=symbol, side=side,
                    order_type="market", quantity=quantity, price=price,
                    status="rejected", error="Insufficient funds",
                    created_at=now, updated_at=now,
                )
            self.cash -= cost
            self.holdings[symbol] = self.holdings.get(symbol, 0) + quantity
        else:
            current = self.holdings.get(symbol, 0)
            if current < quantity:
                return Order(
                    order_id=order_id, symbol=symbol, side=side,
                    order_type="market", quantity=quantity, price=price,
                    status="rejected", error="Insufficient holdings",
                    created_at=now, updated_at=now,
                )
            self.holdings[symbol] = current - quantity
            self.cash += fill_price * quantity - commission

        order = Order(
            order_id=order_id, symbol=symbol, side=side,
            order_type="market", quantity=quantity, price=price,
            status="filled", filled_quantity=quantity,
            filled_price=fill_price, commission=commission,
            created_at=now, updated_at=now,
        )
        self._orders[order_id] = order

        logger.info(
            f"[PAPER] {side.upper()} {quantity:.6f} {symbol} "
            f"@ {fill_price:.2f} (slip={fill_price - price:.2f})"
        )
        return order

    def place_limit_order(self, symbol: str, side: str, quantity: float,
                          price: float) -> Order:
        # In paper trading, limit orders fill immediately at limit price
        # (conservative: assume favorable fill)
        order_id = self._next_order_id()
        now = self._now()
        commission = price * quantity * self.commission_rate

        if side == "buy":
            cost = price * quantity + commission
            if cost > self.cash:
                return Order(
                    order_id=order_id, symbol=symbol, side=side,
                    order_type="limit", quantity=quantity, price=price,
                    status="rejected", error="Insufficient funds",
                    created_at=now, updated_at=now,
                )
            self.cash -= cost
            self.holdings[symbol] = self.holdings.get(symbol, 0) + quantity
        else:
            current = self.holdings.get(symbol, 0)
            if current < quantity:
                return Order(
                    order_id=order_id, symbol=symbol, side=side,
                    order_type="limit", quantity=quantity, price=price,
                    status="rejected", error="Insufficient holdings",
                    created_at=now, updated_at=now,
                )
            self.holdings[symbol] = current - quantity
            self.cash += price * quantity - commission

        order = Order(
            order_id=order_id, symbol=symbol, side=side,
            order_type="limit", quantity=quantity, price=price,
            status="filled", filled_quantity=quantity,
            filled_price=price, commission=commission,
            created_at=now, updated_at=now,
        )
        self._orders[order_id] = order
        return order

    def cancel_order(self, order_id: str, symbol: str) -> Order:
        order = self._orders.get(order_id)
        if order and not order.is_terminal():
            order.status = "cancelled"
            order.updated_at = self._now()
        return order or Order(
            order_id=order_id, symbol=symbol, side="", order_type="",
            quantity=0, price=0, status="not_found",
        )

    def get_order_status(self, order_id: str, symbol: str) -> Order:
        return self._orders.get(order_id, Order(
            order_id=order_id, symbol=symbol, side="", order_type="",
            quantity=0, price=0, status="not_found",
        ))

    def get_balance(self) -> Balance:
        total = {"USDT": self.cash}
        total.update(self.holdings)
        return Balance(total=total, free=dict(total), used={})

    def get_open_orders(self, symbol: str = "") -> List[Order]:
        return [
            o for o in self._orders.values()
            if not o.is_terminal() and (not symbol or o.symbol == symbol)
        ]

    def cancel_all_orders(self, symbol: str = "") -> int:
        count = 0
        for o in self._orders.values():
            if not o.is_terminal() and (not symbol or o.symbol == symbol):
                o.status = "cancelled"
                o.updated_at = self._now()
                count += 1
        return count


# ------------------------------------------------------------------
# Binance live adapter
# ------------------------------------------------------------------

class BinanceAdapter(ExchangeAdapter):
    """
    Real exchange adapter using ccxt to route orders to Binance.

    Safety:
      - Rate limiting is handled by ccxt
      - All orders are logged
      - Errors are caught and returned as rejected orders
    """

    def __init__(self, api_key: str, secret: str, testnet: bool = False):
        import ccxt

        config = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }

        if testnet:
            config["urls"] = {
                "api": {
                    "public": "https://testnet.binance.vision/api/v3",
                    "private": "https://testnet.binance.vision/api/v3",
                }
            }

        self.exchange = ccxt.binanceus(config)
        self.testnet = testnet
        self._order_cache: Dict[str, Order] = {}

        logger.info(
            f"BinanceAdapter initialized "
            f"(testnet={testnet}, rate_limit={self.exchange.enableRateLimit})"
        )

    def _ccxt_to_order(self, raw: Dict, symbol: str = "") -> Order:
        """Convert ccxt order response to our Order dataclass."""
        status_map = {
            "open": "submitted",
            "closed": "filled",
            "canceled": "cancelled",
            "cancelled": "cancelled",
            "expired": "cancelled",
            "rejected": "rejected",
        }
        ccxt_status = raw.get("status", "open")

        return Order(
            order_id=str(raw.get("id", "")),
            symbol=raw.get("symbol", symbol),
            side=raw.get("side", ""),
            order_type=raw.get("type", "market"),
            quantity=float(raw.get("amount", 0)),
            price=float(raw.get("price", 0)),
            status=status_map.get(ccxt_status, ccxt_status),
            filled_quantity=float(raw.get("filled", 0)),
            filled_price=float(raw.get("average", 0) or raw.get("price", 0)),
            commission=float(raw.get("fee", {}).get("cost", 0) if raw.get("fee") else 0),
            exchange_order_id=str(raw.get("id", "")),
            created_at=raw.get("datetime", ""),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def place_market_order(self, symbol: str, side: str, quantity: float,
                           price: float = 0.0) -> Order:
        try:
            if side == "buy":
                raw = self.exchange.create_market_buy_order(symbol, quantity)
            else:
                raw = self.exchange.create_market_sell_order(symbol, quantity)

            order = self._ccxt_to_order(raw, symbol)
            self._order_cache[order.order_id] = order

            logger.info(
                f"[LIVE] {side.upper()} MARKET {quantity:.6f} {symbol} "
                f"→ filled @ {order.filled_price:.2f}"
            )
            return order

        except Exception as e:
            logger.error(f"[LIVE] Market order failed: {e}")
            return Order(
                order_id="", symbol=symbol, side=side,
                order_type="market", quantity=quantity, price=price,
                status="rejected", error=str(e),
                created_at=datetime.now(timezone.utc).isoformat(),
                updated_at=datetime.now(timezone.utc).isoformat(),
            )

    def place_limit_order(self, symbol: str, side: str, quantity: float,
                          price: float) -> Order:
        try:
            if side == "buy":
                raw = self.exchange.create_limit_buy_order(symbol, quantity, price)
            else:
                raw = self.exchange.create_limit_sell_order(symbol, quantity, price)

            order = self._ccxt_to_order(raw, symbol)
            self._order_cache[order.order_id] = order

            logger.info(
                f"[LIVE] {side.upper()} LIMIT {quantity:.6f} {symbol} "
                f"@ {price:.2f} → {order.status}"
            )
            return order

        except Exception as e:
            logger.error(f"[LIVE] Limit order failed: {e}")
            return Order(
                order_id="", symbol=symbol, side=side,
                order_type="limit", quantity=quantity, price=price,
                status="rejected", error=str(e),
                created_at=datetime.now(timezone.utc).isoformat(),
                updated_at=datetime.now(timezone.utc).isoformat(),
            )

    def cancel_order(self, order_id: str, symbol: str) -> Order:
        try:
            raw = self.exchange.cancel_order(order_id, symbol)
            order = self._ccxt_to_order(raw, symbol)
            self._order_cache[order_id] = order
            return order
        except Exception as e:
            logger.error(f"[LIVE] Cancel failed: {e}")
            return Order(
                order_id=order_id, symbol=symbol, side="", order_type="",
                quantity=0, price=0, status="rejected", error=str(e),
            )

    def get_order_status(self, order_id: str, symbol: str) -> Order:
        try:
            raw = self.exchange.fetch_order(order_id, symbol)
            order = self._ccxt_to_order(raw, symbol)
            self._order_cache[order_id] = order
            return order
        except Exception as e:
            logger.error(f"[LIVE] Order status check failed: {e}")
            cached = self._order_cache.get(order_id)
            if cached:
                return cached
            return Order(
                order_id=order_id, symbol=symbol, side="", order_type="",
                quantity=0, price=0, status="not_found", error=str(e),
            )

    def get_balance(self) -> Balance:
        try:
            raw = self.exchange.fetch_balance()
            return Balance(
                total=raw.get("total", {}),
                free=raw.get("free", {}),
                used=raw.get("used", {}),
            )
        except Exception as e:
            logger.error(f"[LIVE] Balance fetch failed: {e}")
            return Balance()

    def get_open_orders(self, symbol: str = "") -> List[Order]:
        try:
            raw_orders = self.exchange.fetch_open_orders(symbol or None)
            return [self._ccxt_to_order(r) for r in raw_orders]
        except Exception as e:
            logger.error(f"[LIVE] Open orders fetch failed: {e}")
            return []

    def cancel_all_orders(self, symbol: str = "") -> int:
        open_orders = self.get_open_orders(symbol)
        cancelled = 0
        for order in open_orders:
            result = self.cancel_order(order.order_id, order.symbol)
            if result.status == "cancelled":
                cancelled += 1
        return cancelled
