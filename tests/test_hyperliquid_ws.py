import json
from typing import Any

import pytest
from loguru import logger

from crypto_spot_collector.exchange.hyperliquid_ws import HyperLiquidWebSocket


class FakeWebSocket:
    def __init__(self, messages: list[str] | None = None) -> None:
        self.sent: list[str] = []
        self.messages = list(messages or [])
        self.closed = False
        self.after_last = lambda: None

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str:
        if self.messages:
            message = self.messages.pop(0)
            if not self.messages:
                self.after_last()
            return message
        raise RuntimeError("stop")

    async def close(self) -> None:
        self.closed = True

    async def ping(self) -> None:
        return None


@pytest.mark.asyncio
async def test_duplicate_subscription_sends_once() -> None:
    client = HyperLiquidWebSocket(testnet=True)
    client.ws = FakeWebSocket()  # type: ignore[assignment]

    def callback(_payload: Any) -> None:
        return None

    await client.subscribe_candle("BTC", "30m", callback)
    await client.subscribe_candle("BTC", "30m", callback)
    assert len(client.ws.sent) == 1  # type: ignore[union-attr]
    assert len(client._subscriptions) == 1


@pytest.mark.asyncio
async def test_duplicate_payload_dispatches_once() -> None:
    payload = json.dumps(
        {
            "channel": "candle",
            "data": [{"s": "BTC", "i": "30m", "t": 1}],
        }
    )
    websocket = FakeWebSocket([payload, payload])
    client = HyperLiquidWebSocket(testnet=True)
    client.ws = websocket  # type: ignore[assignment]
    client._running = True
    websocket.after_last = lambda: setattr(client, "_running", False)
    calls: list[Any] = []
    client._callbacks["candle_BTC_30m"] = calls.append
    await client.listen()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_user_fill_logs_do_not_expose_wallet_address() -> None:
    address = "0x27a70dc0656bef760242d5f923be51e638c93b20"
    payload = json.dumps(
        {
            "channel": "userFills",
            "data": {"user": address, "fills": []},
        }
    )
    websocket = FakeWebSocket([payload])
    client = HyperLiquidWebSocket(testnet=False)
    client.ws = websocket  # type: ignore[assignment]
    client._running = True
    websocket.after_last = lambda: setattr(client, "_running", False)
    calls: list[Any] = []
    client._callbacks[f"userFills_{address}"] = calls.append
    messages: list[str] = []
    sink = logger.add(messages.append, level="DEBUG", format="{message}")
    try:
        await client.listen()
    finally:
        logger.remove(sink)

    assert len(calls) == 1
    assert all(address not in message for message in messages)


@pytest.mark.asyncio
async def test_reconnect_restores_one_subscription_and_runs_snapshot_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reconnected = FakeWebSocket()

    async def connect(_url: str) -> FakeWebSocket:
        return reconnected

    monkeypatch.setattr(
        "crypto_spot_collector.exchange.hyperliquid_ws.websockets.connect", connect
    )
    hooks: list[str] = []

    async def hook() -> None:
        hooks.append("reconciled")

    client = HyperLiquidWebSocket(testnet=True, on_reconnect=hook)
    client.ws = FakeWebSocket()  # type: ignore[assignment]
    client._running = True
    client._subscriptions["candle_BTC_30m"] = {
        "method": "subscribe",
        "subscription": {"type": "candle", "coin": "BTC", "interval": "30m"},
    }
    assert await client._reconnect() is True
    assert len(reconnected.sent) == 1
    assert hooks == ["reconciled"]
    assert client.reconnect_count == 1
