"""Exchange-truth execution gates for entries and reduce-only closes."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from crypto_spot_collector.trading.order_state import (
    IdempotentOrderExecutor,
    OrderIntent,
    OrderStatus,
    create_intent,
)
from crypto_spot_collector.trading.protection import (
    ProtectionReconciler,
    ProtectionReport,
)


class ExecutionSafetyError(RuntimeError):
    """Raised when exchange truth cannot prove a safe strategy transition."""


class PositionAdapter(Protocol):
    async def fetch_positions(self) -> Sequence[dict[str, Any]]: ...


@dataclass(frozen=True)
class EntryReceipt:
    order: OrderIntent
    position: dict[str, Any]
    protection: ProtectionReport


class PositionExecutionCoordinator:
    """Require fills, actual positions, account settings and verified protection."""

    def __init__(
        self,
        adapter: PositionAdapter,
        executor: IdempotentOrderExecutor,
        protection_reconciler: ProtectionReconciler,
        *,
        expected_leverage: int,
        expected_margin_mode: str = "cross",
        position_attempts: int = 5,
        position_delay: float = 0.25,
    ) -> None:
        if position_attempts < 1 or position_delay < 0:
            raise ValueError("invalid position confirmation policy")
        if expected_leverage <= 0:
            raise ValueError("expected leverage must be positive")
        if expected_margin_mode not in {"cross", "isolated"}:
            raise ValueError("expected margin mode must be cross or isolated")
        self.adapter = adapter
        self.executor = executor
        self.protection_reconciler = protection_reconciler
        self.expected_leverage = expected_leverage
        self.expected_margin_mode = expected_margin_mode
        self.position_attempts = position_attempts
        self.position_delay = position_delay

    async def execute_entry(
        self,
        intent: OrderIntent,
        *,
        expected_side: str,
    ) -> EntryReceipt:
        if intent.reduce_only:
            raise ValueError("entry intent must not be reduce-only")
        if expected_side not in {"long", "short"}:
            raise ValueError("expected side must be long or short")

        order = await self.executor.execute_confirmed(intent)
        self._require_full_fill(order, operation="entry")
        positions, position = await self._wait_for_position(
            intent.symbol,
            expected_side=expected_side,
        )
        try:
            if str(position.get("side", "")).lower() != expected_side:
                raise ExecutionSafetyError(
                    f"actual side {position.get('side')!r} does not match "
                    f"expected {expected_side!r}"
                )
            self._validate_position_settings(position)
            protection = await self.protection_reconciler.reconcile_symbol(
                intent.symbol,
                positions=positions,
            )
        except Exception as protection_error:
            await self._close_unprotected(intent, position, protection_error)
            raise ExecutionSafetyError(
                f"{intent.symbol} entry was closed because protection or account "
                "settings could not be verified"
            ) from protection_error
        return EntryReceipt(order=order, position=position, protection=protection)

    async def execute_close(self, intent: OrderIntent) -> OrderIntent:
        if not intent.reduce_only:
            raise ValueError("close intent must be reduce-only")
        order = await self.executor.execute_confirmed(intent)
        self._require_full_fill(order, operation="close")
        positions, position = await self._wait_for_position(intent.symbol)
        if position is not None:
            raise ExecutionSafetyError(
                f"{intent.symbol} close filled but exchange position is not flat"
            )
        await self.protection_reconciler.reconcile_symbol(
            intent.symbol,
            positions=positions,
        )
        return order

    async def _close_unprotected(
        self,
        entry_intent: OrderIntent,
        position: dict[str, Any],
        protection_error: Exception,
    ) -> None:
        side = str(position.get("side", "")).lower()
        contracts = abs(float(position.get("contracts") or 0))
        if side not in {"long", "short"} or contracts <= 0:
            raise ExecutionSafetyError(
                f"cannot safely close unprotected {entry_intent.symbol} position"
            ) from protection_error
        close_intent = create_intent(
            strategy="unprotected-position-close-v1",
            symbol=entry_intent.symbol,
            timeframe=entry_intent.timeframe,
            candle_open_ms=entry_intent.candle_open_ms,
            side="sell" if side == "long" else "buy",
            amount=contracts,
            reduce_only=True,
        )
        try:
            await self.execute_close(close_intent)
        except Exception as close_error:
            raise ExecutionSafetyError(
                f"CRITICAL: {entry_intent.symbol} is unprotected and emergency "
                "reduce-only close could not be confirmed"
            ) from close_error

    async def _wait_for_position(
        self,
        symbol: str,
        *,
        expected_side: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        latest: list[dict[str, Any]] = []
        for attempt in range(self.position_attempts):
            latest = list(await self.adapter.fetch_positions())
            matching = [
                position
                for position in latest
                if position.get("symbol") == symbol
                and abs(float(position.get("contracts") or 0)) > 0
            ]
            if len(matching) > 1:
                raise ExecutionSafetyError(
                    f"multiple non-zero positions returned for {symbol}"
                )
            position = matching[0] if matching else None
            if expected_side is None:
                if position is None:
                    return latest, None
            elif position is not None:
                return latest, position
            if attempt + 1 < self.position_attempts and self.position_delay:
                await asyncio.sleep(self.position_delay)
        expected = "flat" if expected_side is None else expected_side
        raise ExecutionSafetyError(
            f"exchange position for {symbol} did not become {expected} before deadline"
        )

    def _validate_position_settings(self, position: dict[str, Any]) -> None:
        leverage_value = position.get("leverage")
        if isinstance(leverage_value, dict):
            leverage = float(leverage_value.get("value") or 0)
            leverage_mode = leverage_value.get("type")
        else:
            leverage = float(leverage_value or 0)
            leverage_mode = None
        info = position.get("info", {})
        raw_leverage = info.get("position", info).get("leverage", {})
        if not leverage and isinstance(raw_leverage, dict):
            leverage = float(raw_leverage.get("value") or 0)
        margin_mode = (
            position.get("marginMode")
            or leverage_mode
            or (raw_leverage.get("type") if isinstance(raw_leverage, dict) else None)
        )
        if not math.isclose(leverage, self.expected_leverage, rel_tol=1e-9):
            raise ExecutionSafetyError(
                f"actual leverage {leverage} does not match configured "
                f"{self.expected_leverage}"
            )
        if str(margin_mode).lower() != self.expected_margin_mode:
            raise ExecutionSafetyError(
                f"actual margin mode {margin_mode!r} does not match configured "
                f"{self.expected_margin_mode!r}"
            )

    @staticmethod
    def _require_full_fill(order: OrderIntent, *, operation: str) -> None:
        completely_filled = order.filled >= order.amount or math.isclose(
            order.filled,
            order.amount,
            rel_tol=1e-9,
            abs_tol=1e-12,
        )
        if order.status is not OrderStatus.FILLED or not completely_filled:
            raise ExecutionSafetyError(
                f"{operation} intent {order.cloid} is {order.status.value} "
                f"({order.filled}/{order.amount}); strategy transition inhibited"
            )
