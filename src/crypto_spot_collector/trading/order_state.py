"""Persistent, idempotent order intent state machine."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Protocol, Sequence


class OrderStatus(str, Enum):
    PREPARED = "prepared"
    SUBMITTING = "submitting"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


TERMINAL_STATUSES = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}

ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PREPARED: {OrderStatus.SUBMITTING},
    OrderStatus.SUBMITTING: {
        OrderStatus.OPEN,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.REJECTED,
        OrderStatus.UNKNOWN,
    },
    OrderStatus.OPEN: {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.UNKNOWN,
    },
    OrderStatus.PARTIALLY_FILLED: {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.UNKNOWN,
    },
    OrderStatus.UNKNOWN: {
        OrderStatus.OPEN,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
    },
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED: set(),
}


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    cloid: str
    strategy: str
    symbol: str
    timeframe: str
    candle_open_ms: int
    side: str
    amount: float
    reduce_only: bool
    status: OrderStatus
    filled: float = 0.0
    order_id: str | None = None
    error: str | None = None


def create_intent(
    *,
    strategy: str,
    symbol: str,
    timeframe: str,
    candle_open_ms: int,
    side: str,
    amount: float,
    reduce_only: bool = False,
) -> OrderIntent:
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if amount <= 0:
        raise ValueError("amount must be greater than zero")
    canonical = "|".join(
        [
            "v1",
            strategy,
            symbol,
            timeframe,
            str(candle_open_ms),
            side,
            "reduce" if reduce_only else "entry",
        ]
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return OrderIntent(
        intent_id=digest,
        cloid="0x" + digest[:32],
        strategy=strategy,
        symbol=symbol,
        timeframe=timeframe,
        candle_open_ms=candle_open_ms,
        side=side,
        amount=amount,
        reduce_only=reduce_only,
        status=OrderStatus.PREPARED,
    )


class SQLiteOrderIntentStore:
    """Small durable store; each mutation is an immediate transaction."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._transaction() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS order_intents (
                    intent_id TEXT PRIMARY KEY,
                    cloid TEXT NOT NULL UNIQUE,
                    strategy TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    candle_open_ms INTEGER NOT NULL,
                    side TEXT NOT NULL,
                    amount REAL NOT NULL,
                    reduce_only INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    filled REAL NOT NULL DEFAULT 0,
                    order_id TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def prepare(self, intent: OrderIntent) -> tuple[OrderIntent, bool]:
        with self._transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM order_intents WHERE intent_id = ?", (intent.intent_id,)
            ).fetchone()
            if existing is not None:
                return self._from_row(existing), False
            connection.execute(
                """
                INSERT INTO order_intents (
                    intent_id, cloid, strategy, symbol, timeframe,
                    candle_open_ms, side, amount, reduce_only, status,
                    filled, order_id, error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.intent_id,
                    intent.cloid,
                    intent.strategy,
                    intent.symbol,
                    intent.timeframe,
                    intent.candle_open_ms,
                    intent.side,
                    intent.amount,
                    int(intent.reduce_only),
                    intent.status.value,
                    intent.filled,
                    intent.order_id,
                    intent.error,
                    _now(),
                ),
            )
            return intent, True

    def get(self, intent_id: str) -> OrderIntent | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM order_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def transition(
        self,
        intent_id: str,
        status: OrderStatus,
        *,
        filled: float | None = None,
        order_id: str | None = None,
        error: str | None = None,
    ) -> OrderIntent:
        with self._transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM order_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            if row is None:
                raise KeyError(intent_id)
            current = OrderStatus(row["status"])
            if status is not current and status not in ALLOWED_TRANSITIONS[current]:
                raise ValueError(f"invalid order transition: {current.value} -> {status.value}")
            connection.execute(
                """
                UPDATE order_intents
                SET status = ?, filled = ?, order_id = ?, error = ?, updated_at = ?
                WHERE intent_id = ?
                """,
                (
                    status.value,
                    float(row["filled"] if filled is None else filled),
                    row["order_id"] if order_id is None else order_id,
                    error,
                    _now(),
                    intent_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM order_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
        assert updated is not None
        return self._from_row(updated)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> OrderIntent:
        return OrderIntent(
            intent_id=row["intent_id"],
            cloid=row["cloid"],
            strategy=row["strategy"],
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            candle_open_ms=int(row["candle_open_ms"]),
            side=row["side"],
            amount=float(row["amount"]),
            reduce_only=bool(row["reduce_only"]),
            status=OrderStatus(row["status"]),
            filled=float(row["filled"]),
            order_id=row["order_id"],
            error=row["error"],
        )


class TradingAdapter(Protocol):
    async def submit_market_order(self, intent: OrderIntent) -> dict[str, Any]: ...

    async def fetch_order_by_cloid(
        self, symbol: str, cloid: str
    ) -> dict[str, Any] | None: ...

    async def fetch_open_orders(self, symbol: str) -> Sequence[dict[str, Any]]: ...

    async def fetch_fills(self, symbol: str) -> Sequence[dict[str, Any]]: ...

    async def fetch_positions(self) -> Sequence[dict[str, Any]]: ...


class IdempotentOrderExecutor:
    def __init__(self, adapter: TradingAdapter, store: SQLiteOrderIntentStore) -> None:
        self.adapter = adapter
        self.store = store
        self._locks: dict[str, asyncio.Lock] = {}
        self._accepting = True

    def stop_accepting(self) -> None:
        self._accepting = False

    async def execute(self, requested: OrderIntent) -> OrderIntent:
        if not self._accepting:
            raise RuntimeError("new order intents are disabled during shutdown")
        lock = self._locks.setdefault(requested.symbol, asyncio.Lock())
        async with lock:
            intent, created = self.store.prepare(requested)
            if not created:
                if intent.status is OrderStatus.PREPARED:
                    # A crash before SUBMITTING is the only safe retry point.
                    pass
                elif intent.status in TERMINAL_STATUSES:
                    return intent
                else:
                    return await self.reconcile(intent)

            intent = self.store.transition(intent.intent_id, OrderStatus.SUBMITTING)
            try:
                response = await self.adapter.submit_market_order(intent)
            except (TimeoutError, asyncio.TimeoutError) as exc:
                intent = self.store.transition(
                    intent.intent_id, OrderStatus.UNKNOWN, error=type(exc).__name__
                )
                return await self.reconcile(intent)
            except Exception as exc:
                return self.store.transition(
                    intent.intent_id,
                    OrderStatus.REJECTED,
                    error=f"{type(exc).__name__}: {exc}",
                )
            applied = self._apply_exchange_order(intent, response)
            # HyperLiquid can return an accepted market-order envelope with no
            # normalized CCXT status even though the order has already filled.
            # Reconcile that ambiguous response by cloid before returning; the
            # UNKNOWN state continues to inhibit any automatic resubmission.
            if applied.status is OrderStatus.UNKNOWN:
                return await self.reconcile(applied)
            return applied

    async def reconcile(self, intent: OrderIntent) -> OrderIntent:
        order = await self.adapter.fetch_order_by_cloid(intent.symbol, intent.cloid)
        if order is None:
            orders = await self.adapter.fetch_open_orders(intent.symbol)
            order = next((item for item in orders if _cloid(item) == intent.cloid), None)

        fills = await self.adapter.fetch_fills(intent.symbol)
        matching = [fill for fill in fills if _cloid(fill) == intent.cloid]
        if matching:
            filled = sum(float(fill.get("amount") or fill.get("filled") or 0) for fill in matching)
            status = (
                OrderStatus.FILLED
                if filled >= intent.amount
                else OrderStatus.PARTIALLY_FILLED
            )
            return self.store.transition(intent.intent_id, status, filled=filled)

        # HyperLiquid's lookup-by-cloid endpoint can represent an already
        # filled market order as open. Prefer the immutable fill ledger above
        # the order snapshot; only use the latter when no linked fill exists.
        if order is not None:
            return self._apply_exchange_order(intent, order)

        # Positions are still queried as part of the timeout reconciliation.
        # Without a cloid/order/fill link a position is not sufficient proof
        # that this particular intent executed, so the state remains UNKNOWN.
        await self.adapter.fetch_positions()
        return self.store.transition(
            intent.intent_id,
            OrderStatus.UNKNOWN,
            error="no exchange evidence for cloid; automatic resubmit inhibited",
        )

    def _apply_exchange_order(
        self, intent: OrderIntent, order: dict[str, Any]
    ) -> OrderIntent:
        raw_status = str(order.get("status", "open")).lower()
        filled = float(order.get("filled") or 0)
        status_map = {
            "open": OrderStatus.OPEN,
            "new": OrderStatus.OPEN,
            "closed": OrderStatus.FILLED,
            "filled": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "cancelled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
        }
        status = status_map.get(raw_status, OrderStatus.UNKNOWN)
        if status is OrderStatus.OPEN and filled > 0:
            status = OrderStatus.PARTIALLY_FILLED
        return self.store.transition(
            intent.intent_id,
            status,
            filled=filled,
            order_id=str(order.get("id")) if order.get("id") is not None else None,
        )


def _cloid(item: dict[str, Any]) -> str | None:
    return item.get("clientOrderId") or item.get("info", {}).get("cloid")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
