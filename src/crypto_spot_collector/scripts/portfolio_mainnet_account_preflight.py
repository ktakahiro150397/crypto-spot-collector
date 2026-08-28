"""Read-only live account gate for the mainnet portfolio observer."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Mapping

from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.scripts.portfolio_mainnet_preflight import (
    validate_portfolio_mainnet_disabled_settings,
)
from crypto_spot_collector.scripts.portfolio_testnet_account_preflight import (
    audit_flat_account,
)
from crypto_spot_collector.trading.deployment import validate_deployment_secrets
from crypto_spot_collector.utils.secrets import load_config


async def run(settings_path: Path, secrets_path: Path) -> dict[str, object]:
    document: Mapping[str, Any] = load_config(secrets_path, settings_path)
    config = validate_portfolio_mainnet_disabled_settings(
        document,
        mainnet_confirmation=os.getenv("HYPERLIQUID_MAINNET_CONFIRMATION", ""),
    )
    deployment_secrets = validate_deployment_secrets(
        document, config, expected_network="mainnet"
    )
    exchange = HyperLiquidExchange(
        mainWalletAddress=deployment_secrets["mainWalletAddress"],
        apiWalletAddress=deployment_secrets["apiWalletAddress"],
        privateKey=deployment_secrets["privatekey"],
        trading_config=config,
    )
    try:
        return dict(await audit_flat_account(exchange, config))
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
