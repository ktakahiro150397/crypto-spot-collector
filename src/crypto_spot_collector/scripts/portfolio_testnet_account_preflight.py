"""Read-only live account gate for the initial portfolio testnet deployment."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.scripts.portfolio_testnet_preflight import (
    validate_portfolio_testnet_settings,
)
from crypto_spot_collector.trading.config import TradingConfig
from crypto_spot_collector.trading.deployment import (
    DeploymentError,
    validate_deployment_secrets,
)
from crypto_spot_collector.trading.portfolio_execution import position_notionals
from crypto_spot_collector.utils.secrets import load_config


class AccountAuditAdapter(Protocol):
    async def validate_api_wallet_authorization(self) -> None: ...

    async def fetch_positions(self) -> Sequence[dict[str, Any]]: ...

    async def fetch_open_orders(
        self, symbol: str | None = None
    ) -> Sequence[dict[str, Any]]: ...

    async def fetch_free_collateral(self) -> float: ...


async def audit_flat_account(
    exchange: AccountAuditAdapter, config: TradingConfig
) -> dict[str, object]:
    """Require a clean account before startup can reconcile protection orders."""

    await exchange.validate_api_wallet_authorization()
    notionals = position_notionals(
        list(await exchange.fetch_positions()), config.symbols
    )
    if any(value != 0 for value in notionals.values()):
        raise DeploymentError(
            "portfolio testnet deployment requires a flat account before startup"
        )
    open_orders = list(await exchange.fetch_open_orders())
    if open_orders:
        raise DeploymentError(
            "portfolio testnet deployment requires zero open orders before startup"
        )
    free_collateral = float(await exchange.fetch_free_collateral())
    collateral_ready = (
        math.isfinite(free_collateral)
        and free_collateral >= config.min_free_collateral_usdc
    )
    return {
        "network": config.network.value,
        "authorized_api_wallet": True,
        "active_position_count": 0,
        "open_order_count": 0,
        "minimum_free_collateral_ready": collateral_ready,
    }


async def run(settings_path: Path, secrets_path: Path) -> dict[str, object]:
    document: Mapping[str, Any] = load_config(secrets_path, settings_path)
    config = validate_portfolio_testnet_settings(document)
    deployment_secrets = validate_deployment_secrets(
        document, config, expected_network="testnet"
    )
    exchange = HyperLiquidExchange(
        mainWalletAddress=deployment_secrets["mainWalletAddress"],
        apiWalletAddress=deployment_secrets["apiWalletAddress"],
        privateKey=deployment_secrets["privatekey"],
        trading_config=config,
    )
    try:
        return await audit_flat_account(exchange, config)
    finally:
        await exchange.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--secrets", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.settings, args.secrets)), sort_keys=True))


if __name__ == "__main__":
    main()
