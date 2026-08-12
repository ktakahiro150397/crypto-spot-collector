"""Fail-closed entry risk limits based on the latest exchange snapshot."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

from crypto_spot_collector.trading.config import TradingConfig


class EntryRiskError(RuntimeError):
    """Raised when a new entry cannot be proven to stay within risk limits."""


class RiskAdapter(Protocol):
    async def fetch_positions(self) -> Sequence[dict[str, Any]]: ...

    async def fetch_open_orders(
        self, symbol: str | None = None
    ) -> Sequence[dict[str, Any]]: ...

    async def fetch_free_collateral(self) -> float: ...


@dataclass(frozen=True)
class EntryReservation:
    reservation_id: int
    symbol: str
    notional: float


class EntryRiskGuard:
    """Serialize entry reservations without affecting protection or closes."""

    def __init__(
        self,
        adapter: RiskAdapter,
        config: TradingConfig,
        *,
        kill_switch_path: Path | str,
    ) -> None:
        config.validate()
        self.adapter = adapter
        self.config = config
        self.kill_switch_path = Path(kill_switch_path)
        self._lock = asyncio.Lock()
        self._stopped_reason: str | None = None
        self._next_reservation_id = 1
        self._reservations: dict[int, EntryReservation] = {}

    def stop_entries(self, reason: str) -> None:
        """Immediately stop only new entries; reduce-only paths remain usable."""

        self._stopped_reason = reason or "entry kill switch activated"

    async def reserve_entry(
        self,
        *,
        symbol: str,
        amount: float,
        price: float,
    ) -> EntryReservation:
        async with self._lock:
            self._ensure_entries_enabled()
            notional = _positive_finite(amount, "amount") * _positive_finite(
                price, "price"
            )
            positions = list(await self.adapter.fetch_positions())
            orders = list(await self.adapter.fetch_open_orders(None))
            free_collateral = _non_negative_finite(
                await self.adapter.fetch_free_collateral(),
                "free collateral",
            )
            self._validate_snapshot(
                symbol=symbol,
                new_notional=notional,
                free_collateral=free_collateral,
                positions=positions,
                orders=orders,
            )
            reservation = EntryReservation(
                reservation_id=self._next_reservation_id,
                symbol=symbol,
                notional=notional,
            )
            self._next_reservation_id += 1
            self._reservations[reservation.reservation_id] = reservation
            return reservation

    async def release(self, reservation: EntryReservation) -> None:
        async with self._lock:
            self._reservations.pop(reservation.reservation_id, None)

    def _ensure_entries_enabled(self) -> None:
        if not self.config.entries_enabled:
            raise EntryRiskError("new entries are disabled by configuration")
        if self._stopped_reason is not None:
            raise EntryRiskError(f"new entries are stopped: {self._stopped_reason}")
        if self.kill_switch_path.exists():
            raise EntryRiskError(
                f"new entries are stopped by kill-switch file: "
                f"{self.kill_switch_path}"
            )

    def _validate_snapshot(
        self,
        *,
        symbol: str,
        new_notional: float,
        free_collateral: float,
        positions: Sequence[dict[str, Any]],
        orders: Sequence[dict[str, Any]],
    ) -> None:
        config = self.config
        allowlist = set(config.symbols)
        if symbol not in allowlist:
            raise EntryRiskError(f"symbol {symbol} is outside the configured allowlist")
        if config.leverage > config.max_leverage:
            raise EntryRiskError("configured leverage exceeds the hard risk limit")
        if new_notional > config.max_order_notional_usdc:
            raise EntryRiskError(
                f"order notional {new_notional:.8f} exceeds max order notional"
            )

        live_positions: dict[str, float] = {}
        position_total = 0.0
        for position in positions:
            contracts = abs(float(position.get("contracts") or 0))
            if not math.isfinite(contracts):
                raise EntryRiskError("position contracts must be finite")
            if contracts == 0:
                continue
            position_symbol = str(position.get("symbol") or "")
            if position_symbol not in allowlist:
                raise EntryRiskError(
                    f"live position {position_symbol!r} is outside the allowlist"
                )
            if position_symbol in live_positions:
                raise EntryRiskError(
                    f"multiple live positions returned for {position_symbol}"
                )
            position_price = _position_price(position)
            position_notional = contracts * position_price
            if position_notional > config.max_symbol_notional_usdc:
                raise EntryRiskError(
                    f"live {position_symbol} notional exceeds symbol limit"
                )
            actual_leverage = _position_leverage(position)
            if actual_leverage > config.max_leverage:
                raise EntryRiskError(
                    f"live {position_symbol} leverage exceeds max_leverage"
                )
            live_positions[position_symbol] = position_notional
            position_total += position_notional

        if len(live_positions) > config.max_positions:
            raise EntryRiskError("live position count exceeds max_positions")
        if position_total > config.max_total_notional_usdc:
            raise EntryRiskError("live total notional exceeds total limit")

        if symbol in live_positions:
            raise EntryRiskError(f"existing position for {symbol} blocks a new entry")

        for order in orders:
            order_info = order.get("info", {}) or {}
            order_symbol = str(order.get("symbol") or order_info.get("symbol") or "")
            if order_symbol not in allowlist:
                raise EntryRiskError(
                    f"open order for {order_symbol!r} is outside the allowlist"
                )
            if _is_reduce_only(order):
                if order_symbol not in live_positions:
                    raise EntryRiskError(
                        f"orphan reduce-only order exists for flat {order_symbol}"
                    )
                continue
            raise EntryRiskError(
                f"unsettled non-reduce-only order exists for {order_symbol}"
            )

        reserved_total = sum(item.notional for item in self._reservations.values())
        reserved_by_symbol = sum(
            item.notional
            for item in self._reservations.values()
            if item.symbol == symbol
        )
        projected_position_count = len(live_positions) + len(self._reservations) + 1
        if projected_position_count > config.max_positions:
            raise EntryRiskError("projected position count exceeds max_positions")
        if reserved_by_symbol + new_notional > config.max_symbol_notional_usdc:
            raise EntryRiskError("projected symbol notional exceeds symbol limit")
        if (
            position_total + reserved_total + new_notional
            > config.max_total_notional_usdc
        ):
            raise EntryRiskError("projected total notional exceeds total limit")
        required_margin = new_notional / config.leverage
        if free_collateral - required_margin < config.min_free_collateral_usdc:
            raise EntryRiskError(
                "free collateral would fall below the configured reserve"
            )


def _positive_finite(value: float, name: str) -> float:
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise EntryRiskError(f"{name} must be finite and positive")
    return normalized


def _non_negative_finite(value: float, name: str) -> float:
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise EntryRiskError(f"{name} must be finite and non-negative")
    return normalized


def _position_price(position: dict[str, Any]) -> float:
    return _positive_finite(
        position.get("markPrice")
        or position.get("entryPrice")
        or position.get("entry_price")
        or 0,
        "position price",
    )


def _position_leverage(position: dict[str, Any]) -> float:
    raw = position.get("leverage")
    if isinstance(raw, dict):
        raw = raw.get("value")
    if raw is None:
        info = position.get("info", {}) or {}
        raw_leverage = info.get("position", info).get("leverage", {})
        raw = (
            raw_leverage.get("value")
            if isinstance(raw_leverage, dict)
            else raw_leverage
        )
    return _positive_finite(raw or 0, "position leverage")


def _is_reduce_only(order: dict[str, Any]) -> bool:
    info = order.get("info", {}) or {}
    if bool(order.get("reduceOnly", info.get("reduceOnly", False))):
        return True
    order_type = str(info.get("orderType") or order.get("type") or "").lower()
    return "take profit" in order_type or "stop" in order_type
