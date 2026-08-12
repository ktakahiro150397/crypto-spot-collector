from __future__ import annotations

from typing import Any

import pytest

from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange


class _DirectCaller:
    async def call(self, _operation: str, function: Any, **_kwargs: Any) -> Any:
        return await function()


class _Exchange:
    def __init__(self, mode: str, spot_free: float) -> None:
        self.mode = mode
        self.spot_free = spot_free
        self.requested_balance_type: str | None = None

    async def public_post_info(self, _request: dict[str, str]) -> str:
        return self.mode

    async def fetch_balance(self, params: dict[str, str]) -> dict[str, Any]:
        self.requested_balance_type = params["type"]
        return {"free": {"USDC": self.spot_free}}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ['"unifiedAccount"', "portfolioMargin"])
async def test_unified_collateral_uses_spot_clearinghouse_balance(mode: str) -> None:
    adapter = object.__new__(HyperLiquidExchange)
    adapter.main_wallet_address = "unused"
    adapter.rest = _DirectCaller()
    adapter.exchange_public = _Exchange(mode, 123.0)

    assert await adapter.fetch_free_collateral() == 123.0
    assert adapter.exchange_public.requested_balance_type == "spot"


@pytest.mark.asyncio
async def test_unknown_account_abstraction_mode_fails_closed() -> None:
    adapter = object.__new__(HyperLiquidExchange)
    adapter.main_wallet_address = "unused"
    adapter.rest = _DirectCaller()
    adapter.exchange_public = _Exchange("future-mode", 123.0)

    with pytest.raises(RuntimeError, match="account abstraction"):
        await adapter.fetch_free_collateral()
