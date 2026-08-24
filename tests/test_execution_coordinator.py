import math
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.trading.execution import (
    ExecutionSafetyError,
    PositionExecutionCoordinator,
)
from crypto_spot_collector.trading.order_state import (
    OrderIntent,
    OrderStatus,
    create_intent,
)
from crypto_spot_collector.trading.protection import (
    PositionSnapshot,
    ProtectionError,
    ProtectionReport,
)

SYMBOL = "ETH/USDC:USDC"


def entry_intent() -> OrderIntent:
    return create_intent(
        strategy="sar-v1",
        symbol=SYMBOL,
        timeframe="30m",
        candle_open_ms=123,
        side="buy",
        amount=0.1,
    )


def live_position(**overrides: Any) -> dict[str, Any]:
    position = {
        "symbol": SYMBOL,
        "side": "long",
        "contracts": 0.1,
        "entryPrice": 2500.0,
        "leverage": 20,
        "marginMode": "cross",
    }
    position.update(overrides)
    return position


class FakePositionAdapter:
    def __init__(self, positions: list[dict[str, Any]]) -> None:
        self.positions = positions

    async def fetch_positions(self) -> list[dict[str, Any]]:
        return list(self.positions)


class StubExecutor:
    def __init__(
        self,
        adapter: FakePositionAdapter,
        *,
        status: OrderStatus = OrderStatus.FILLED,
        flatten_on_close: bool = True,
    ) -> None:
        self.adapter = adapter
        self.status = status
        self.flatten_on_close = flatten_on_close
        self.intents: list[OrderIntent] = []

    async def execute_confirmed(self, intent: OrderIntent) -> OrderIntent:
        self.intents.append(intent)
        filled = (
            intent.amount if self.status is OrderStatus.FILLED else intent.amount / 2
        )
        if (
            intent.reduce_only
            and self.flatten_on_close
            and self.status is OrderStatus.FILLED
        ):
            self.adapter.positions = []
        return replace(intent, status=self.status, filled=filled, order_id="order-1")


class FakeProtectionReconciler:
    def __init__(self, *, fail_live_position: bool = False) -> None:
        self.fail_live_position = fail_live_position
        self.calls: list[list[dict[str, Any]]] = []

    async def reconcile_symbol(
        self,
        symbol: str,
        *,
        positions: list[dict[str, Any]],
    ) -> ProtectionReport:
        self.calls.append(positions)
        current = next(
            (
                item
                for item in positions
                if item.get("symbol") == symbol and item.get("contracts")
            ),
            None,
        )
        if current is not None and self.fail_live_position:
            raise ProtectionError("one-sided protection")
        snapshot = None
        if current is not None:
            snapshot = PositionSnapshot(
                symbol=symbol,
                side=str(current["side"]),
                contracts=float(current["contracts"]),
                entry_price=float(current["entryPrice"]),
                leverage=float(current["leverage"]),
            )
        return ProtectionReport(symbol=symbol, position=snapshot)


def coordinator(
    adapter: FakePositionAdapter,
    executor: StubExecutor,
    protection: FakeProtectionReconciler,
) -> PositionExecutionCoordinator:
    return PositionExecutionCoordinator(
        adapter,
        executor,  # type: ignore[arg-type]
        protection,  # type: ignore[arg-type]
        expected_leverage=20,
        expected_margin_mode="cross",
        position_attempts=1,
        position_delay=0,
    )


@pytest.mark.asyncio
async def test_entry_returns_actual_average_quantity_and_verified_protection() -> None:
    adapter = FakePositionAdapter([live_position()])
    executor = StubExecutor(adapter)
    protection = FakeProtectionReconciler()

    receipt = await coordinator(adapter, executor, protection).execute_entry(
        entry_intent(), expected_side="long"
    )

    assert receipt.position["entryPrice"] == 2500.0
    assert receipt.position["contracts"] == 0.1
    assert receipt.protection.position is not None


@pytest.mark.asyncio
async def test_partial_entry_never_advances_to_protection() -> None:
    adapter = FakePositionAdapter([live_position()])
    executor = StubExecutor(adapter, status=OrderStatus.PARTIALLY_FILLED)
    protection = FakeProtectionReconciler()

    with pytest.raises(ExecutionSafetyError, match="strategy transition inhibited"):
        await coordinator(adapter, executor, protection).execute_entry(
            entry_intent(), expected_side="long"
        )

    assert protection.calls == []


@pytest.mark.asyncio
async def test_unverified_protection_triggers_confirmed_reduce_only_close() -> None:
    adapter = FakePositionAdapter([live_position()])
    executor = StubExecutor(adapter)
    protection = FakeProtectionReconciler(fail_live_position=True)

    with pytest.raises(ExecutionSafetyError, match="was closed"):
        await coordinator(adapter, executor, protection).execute_entry(
            entry_intent(), expected_side="long"
        )

    assert len(executor.intents) == 2
    assert executor.intents[-1].reduce_only is True
    assert executor.intents[-1].side == "sell"
    assert adapter.positions == []


@pytest.mark.asyncio
async def test_leverage_mismatch_is_closed_instead_of_accepted() -> None:
    adapter = FakePositionAdapter([live_position(leverage=10)])
    executor = StubExecutor(adapter)
    protection = FakeProtectionReconciler()

    with pytest.raises(ExecutionSafetyError, match="was closed"):
        await coordinator(adapter, executor, protection).execute_entry(
            entry_intent(), expected_side="long"
        )

    assert executor.intents[-1].reduce_only is True
    assert adapter.positions == []


@pytest.mark.asyncio
async def test_close_fill_without_flat_snapshot_inhibits_reverse() -> None:
    adapter = FakePositionAdapter([live_position()])
    executor = StubExecutor(adapter, flatten_on_close=False)
    protection = FakeProtectionReconciler()
    close = create_intent(
        strategy="sar-close-v1",
        symbol=SYMBOL,
        timeframe="30m",
        candle_open_ms=123,
        side="sell",
        amount=0.1,
        reduce_only=True,
    )

    with pytest.raises(ExecutionSafetyError, match="did not become flat"):
        await coordinator(adapter, executor, protection).execute_close(close)


@pytest.mark.asyncio
async def test_close_timeout_inhibits_reverse_without_flat_assumption() -> None:
    adapter = FakePositionAdapter([live_position()])
    executor = StubExecutor(adapter, status=OrderStatus.UNKNOWN)
    protection = FakeProtectionReconciler()
    close = create_intent(
        strategy="sar-close-v1",
        symbol=SYMBOL,
        timeframe="30m",
        candle_open_ms=123,
        side="sell",
        amount=0.1,
        reduce_only=True,
    )

    with pytest.raises(ExecutionSafetyError, match="strategy transition inhibited"):
        await coordinator(adapter, executor, protection).execute_close(close)

    assert adapter.positions != []


class FakeRest:
    async def call(self, _name: str, operation: Any, **_kwargs: Any) -> Any:
        return await operation()


class FakeCcxtExchange:
    def __init__(self) -> None:
        self.leverage_calls: list[tuple[int, str, dict[str, Any]]] = []
        self.precisionMode = 4

    async def load_markets(self) -> dict[str, Any]:
        return {}

    def market(self, _symbol: str) -> dict[str, Any]:
        return {
            "limits": {
                "amount": {"min": 0.001},
                "cost": {"min": 10},
                "leverage": {"max": 25},
            },
            "precision": {"amount": 0.001},
        }

    def amount_to_precision(self, _symbol: str, amount: float) -> str:
        return f"{amount:.3f}"

    def price_to_precision(self, _symbol: str, price: float) -> str:
        return f"{price:.1f}"

    async def set_leverage(
        self,
        leverage: int,
        symbol: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        self.leverage_calls.append((leverage, symbol, params))
        return {"status": "ok", "response": {"type": "default"}}


class FakePublicExchange:
    def __init__(self, role: dict[str, Any]) -> None:
        self.role = role

    async def public_post_info(self, _request: dict[str, str]) -> dict[str, Any]:
        return self.role


def bare_exchange() -> HyperLiquidExchange:
    exchange = object.__new__(HyperLiquidExchange)
    exchange.exchange_private = FakeCcxtExchange()
    exchange.rest = FakeRest()
    exchange.leverage = 20
    exchange.trading_config = SimpleNamespace(
        margin_mode="cross",
        max_order_notional_usdc=10.5,
    )
    return exchange


@pytest.mark.asyncio
async def test_order_is_rounded_to_market_precision_and_minimum() -> None:
    exchange = bare_exchange()

    prepared = await exchange.prepare_market_order(
        SYMBOL, 0.00449, reference_price=2500.04
    )

    assert prepared.amount == 0.004
    assert prepared.reference_price == 2500.0

    with pytest.raises(ValueError, match="notional"):
        await exchange.prepare_market_order(SYMBOL, 0.001, reference_price=2500)

    with pytest.raises(ValueError, match="invalid order amount"):
        await exchange.prepare_market_order(SYMBOL, math.nan, reference_price=2500)


@pytest.mark.asyncio
async def test_entry_amount_is_rounded_down_below_notional_cap() -> None:
    exchange = bare_exchange()

    prepared = await exchange.prepare_market_order(
        SYMBOL,
        0.0106,
        reference_price=1000,
        max_notional=10.5,
    )

    assert prepared.amount == 0.01
    assert prepared.amount * prepared.reference_price == 10.0


@pytest.mark.asyncio
async def test_notional_cap_fails_when_safe_amount_is_below_exchange_minimum() -> None:
    exchange = bare_exchange()

    with pytest.raises(ValueError, match="below .* minimum"):
        await exchange.prepare_market_order(
            SYMBOL,
            0.0106,
            reference_price=1000,
            max_notional=9.9,
        )


@pytest.mark.asyncio
async def test_api_wallet_must_be_authorized_for_main_wallet() -> None:
    exchange = bare_exchange()
    exchange.main_wallet_address = "0xmain"
    exchange.api_wallet_address = "0xagent"
    exchange.exchange_public = FakePublicExchange(
        {"role": "agent", "data": {"user": "0xMAIN"}}
    )

    await exchange.validate_api_wallet_authorization()

    exchange.exchange_public = FakePublicExchange({"role": "missing"})
    with pytest.raises(RuntimeError, match="not authorized"):
        await exchange.validate_api_wallet_authorization()


@pytest.mark.asyncio
async def test_main_wallet_signer_is_valid_for_same_main_account() -> None:
    exchange = bare_exchange()
    exchange.main_wallet_address = "0xmain"
    exchange.api_wallet_address = "0xMAIN"
    exchange.exchange_public = FakePublicExchange({"role": "user"})

    await exchange.validate_api_wallet_authorization()


@pytest.mark.asyncio
async def test_api_wallet_authorized_for_another_main_wallet_is_rejected() -> None:
    exchange = bare_exchange()
    exchange.main_wallet_address = "0xmain"
    exchange.api_wallet_address = "0xagent"
    exchange.exchange_public = FakePublicExchange(
        {"role": "agent", "data": {"user": "0xother"}}
    )

    with pytest.raises(RuntimeError, match="not authorized"):
        await exchange.validate_api_wallet_authorization()


@pytest.mark.asyncio
async def test_leverage_and_margin_mode_are_exchange_acknowledged() -> None:
    exchange = bare_exchange()

    await exchange.ensure_market_configuration(SYMBOL)

    assert exchange.exchange_private.leverage_calls == [
        (20, SYMBOL, {"marginMode": "cross"})
    ]
