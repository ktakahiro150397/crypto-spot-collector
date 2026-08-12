"""Exchange-truth position recovery and fail-safe TP/SL reconciliation."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any, Protocol, Sequence


class ProtectionError(RuntimeError):
    """Raised when a live position cannot be proven to have both protections."""


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    side: str
    contracts: float
    entry_price: float
    leverage: float | None = None


@dataclass(frozen=True)
class ProtectionSpec:
    symbol: str
    kind: str
    side: str
    amount: float
    trigger_price: float
    cloid: str


@dataclass(frozen=True)
class ProtectionReport:
    symbol: str
    position: PositionSnapshot | None
    created: tuple[str, ...] = ()
    cancelled: tuple[str, ...] = ()
    orphan_count: int = 0


class ProtectionAdapter(Protocol):
    async def fetch_positions(self) -> Sequence[dict[str, Any]]: ...

    async def fetch_open_orders(self, symbol: str) -> Sequence[dict[str, Any]]: ...

    async def fetch_fills(self, symbol: str) -> Sequence[dict[str, Any]]: ...

    async def fetch_last_price(self, symbol: str) -> float: ...

    async def create_protection_order(self, spec: ProtectionSpec) -> dict[str, Any]: ...

    async def cancel_protection_orders(
        self, symbol: str, order_ids: Sequence[str]
    ) -> None: ...


class ProtectionReconciler:
    """Create/verify replacements before cancelling stale protection."""

    def __init__(
        self,
        adapter: ProtectionAdapter,
        *,
        take_profit_roe: float,
        stop_loss_roe: float,
        leverage: int,
    ) -> None:
        self.adapter = adapter
        self.take_profit_roe = take_profit_roe
        self.stop_loss_roe = stop_loss_roe
        self.leverage = leverage

    async def reconcile_all(self, symbols: Sequence[str]) -> list[ProtectionReport]:
        positions = await self.adapter.fetch_positions()
        reports: list[ProtectionReport] = []
        for symbol in symbols:
            reports.append(await self.reconcile_symbol(symbol, positions=positions))
        return reports

    async def reconcile_symbol(
        self,
        symbol: str,
        *,
        positions: Sequence[dict[str, Any]] | None = None,
        trailing_stop: float | None = None,
    ) -> ProtectionReport:
        actual_positions = (
            positions if positions is not None else await self.adapter.fetch_positions()
        )
        matching_positions = [
            item
            for item in actual_positions
            if item.get("symbol") == symbol
            and abs(float(item.get("contracts") or 0)) > 0
        ]
        if len(matching_positions) > 1:
            raise ProtectionError(f"multiple non-zero positions returned for {symbol}")
        position = _position(matching_positions[0]) if matching_positions else None

        # Fetch fills as part of the authoritative recovery snapshot. CCXT's
        # position entryPrice/contracts remain the adopted values, while fills
        # provide the audit trail and force authentication problems to fail fast.
        await self.adapter.fetch_fills(symbol)
        orders = list(await self.adapter.fetch_open_orders(symbol))
        protection_orders = [order for order in orders if _kind(order) is not None]

        if position is None:
            orphan_ids = [
                str(order["id"]) for order in protection_orders if order.get("id")
            ]
            if orphan_ids:
                await self.adapter.cancel_protection_orders(symbol, orphan_ids)
            return ProtectionReport(
                symbol=symbol,
                position=None,
                cancelled=tuple(orphan_ids),
                orphan_count=len(orphan_ids),
            )

        desired = self._desired(position, protection_orders, trailing_stop)
        last_price = float(await self.adapter.fetch_last_price(symbol))
        if last_price <= 0:
            raise ProtectionError(f"invalid last price returned for {symbol}")
        stop_spec = next(spec for spec in desired if spec.kind == "stop_loss")
        stop_is_breached = (
            position.side == "long" and last_price <= stop_spec.trigger_price
        ) or (position.side == "short" and last_price >= stop_spec.trigger_price)
        if stop_is_breached:
            raise ProtectionError(
                f"configured stop for {symbol} is already breached; "
                "a reduce-only close is required"
            )
        retained: dict[str, dict[str, Any]] = {}
        created: list[str] = []
        for spec in desired:
            match = next(
                (
                    order
                    for order in protection_orders
                    if _matches(order, spec)
                    and str(order.get("id"))
                    not in {str(item.get("id")) for item in retained.values()}
                ),
                None,
            )
            if match is None:
                try:
                    result = await self.adapter.create_protection_order(spec)
                except Exception as exc:
                    raise ProtectionError(
                        f"failed to create {spec.kind} protection for {symbol}"
                    ) from exc
                created.append(str(result.get("id") or spec.cloid))
            else:
                retained[spec.kind] = match

        # Never cancel an old order until the exchange snapshot proves that the
        # complete desired pair exists. A half-created pair therefore leaves the
        # prior protection intact for the next reconciliation pass.
        verified = list(await self.adapter.fetch_open_orders(symbol))
        verified_pair: dict[str, dict[str, Any]] = {}
        for spec in desired:
            match = next((order for order in verified if _matches(order, spec)), None)
            if match is None:
                raise ProtectionError(
                    f"{symbol} is not verifiably protected by both TP and SL"
                )
            verified_pair[spec.kind] = match

        keep_ids = {str(order.get("id")) for order in verified_pair.values()}
        stale_ids = [
            str(order["id"])
            for order in verified
            if _kind(order) is not None
            and order.get("id") is not None
            and str(order["id"]) not in keep_ids
        ]
        if stale_ids:
            await self.adapter.cancel_protection_orders(symbol, stale_ids)
        return ProtectionReport(
            symbol=symbol,
            position=position,
            created=tuple(created),
            cancelled=tuple(stale_ids),
        )

    def _desired(
        self,
        position: PositionSnapshot,
        current_orders: Sequence[dict[str, Any]],
        trailing_stop: float | None,
    ) -> tuple[ProtectionSpec, ProtectionSpec]:
        is_long = position.side == "long"
        if position.side not in {"long", "short"}:
            raise ProtectionError(f"unsupported position side: {position.side}")
        direction = 1 if is_long else -1
        leverage = position.leverage or float(self.leverage)
        take_profit = position.entry_price * (
            1 + direction * (self.take_profit_roe / 100) / leverage
        )
        stop_loss = position.entry_price * (
            1 - direction * (self.stop_loss_roe / 100) / leverage
        )
        current_stops = [
            _trigger(order) for order in current_orders if _kind(order) == "stop_loss"
        ]
        candidates = [stop_loss]
        if trailing_stop is not None and trailing_stop > 0:
            candidates.append(trailing_stop)
        candidates.extend(value for value in current_stops if value > 0)
        # A recovered trailing stop can only move in the more protective
        # direction, never back to the initial stop.
        stop_loss = max(candidates) if is_long else min(candidates)
        close_side = "sell" if is_long else "buy"
        return (
            _spec(position, "take_profit", close_side, take_profit),
            _spec(position, "stop_loss", close_side, stop_loss),
        )


def _position(raw: dict[str, Any]) -> PositionSnapshot:
    contracts = abs(float(raw.get("contracts") or 0))
    entry = float(raw.get("entryPrice") or raw.get("entry_price") or 0)
    if contracts <= 0 or entry <= 0:
        raise ProtectionError("position has invalid contracts or entry price")
    return PositionSnapshot(
        symbol=str(raw["symbol"]),
        side=str(raw.get("side", "")).lower(),
        contracts=contracts,
        entry_price=entry,
        leverage=(float(raw["leverage"]) if raw.get("leverage") is not None else None),
    )


def _spec(
    position: PositionSnapshot, kind: str, side: str, trigger: float
) -> ProtectionSpec:
    canonical = (
        f"protection-v1|{position.symbol}|{position.side}|{position.contracts:.12g}|"
        f"{position.entry_price:.12g}|{kind}|{trigger:.12g}"
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return ProtectionSpec(
        symbol=position.symbol,
        kind=kind,
        side=side,
        amount=position.contracts,
        trigger_price=trigger,
        cloid="0x" + digest[:32],
    )


def _kind(order: dict[str, Any]) -> str | None:
    info = order.get("info", {})
    order_type = str(info.get("orderType") or order.get("type") or "").lower()
    if "take profit" in order_type or order.get("takeProfitPrice") is not None:
        return "take_profit"
    if "stop" in order_type or order.get("stopLossPrice") is not None:
        return "stop_loss"
    return None


def _trigger(order: dict[str, Any]) -> float:
    return float(
        order.get("triggerPrice")
        or order.get("stopLossPrice")
        or order.get("takeProfitPrice")
        or order.get("info", {}).get("triggerPx")
        or 0
    )


def _matches(order: dict[str, Any], spec: ProtectionSpec) -> bool:
    amount = float(order.get("amount") or order.get("remaining") or 0)
    return (
        _kind(order) == spec.kind
        and math.isclose(amount, spec.amount, rel_tol=1e-8, abs_tol=1e-10)
        # HyperLiquid rounds trigger prices to the market's significant-digit
        # precision. Accept that exchange-normalized value when verifying the
        # pair, while still rejecting a materially different protection level.
        and math.isclose(
            _trigger(order), spec.trigger_price, rel_tol=5e-5, abs_tol=1e-10
        )
        and bool(order.get("reduceOnly", order.get("info", {}).get("reduceOnly", True)))
    )
