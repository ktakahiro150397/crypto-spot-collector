"""Offline settings preflight for the portfolio testnet service."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from crypto_spot_collector.trading.config import Network, SignalMode, TradingConfig
from crypto_spot_collector.trading.deployment import validate_deployment_secrets
from crypto_spot_collector.trading.portfolio_execution import (
    trend_config_from_trading_config,
)


def validate_portfolio_testnet_settings(
    document: Mapping[str, Any],
    *,
    require_entries_disabled: bool = True,
) -> TradingConfig:
    settings = document.get("settings")
    if not isinstance(settings, Mapping):
        raise ValueError("settings object is missing")
    config = TradingConfig.from_mapping(settings)
    if config.network is not Network.TESTNET:
        raise ValueError("portfolio deployment preflight is testnet-only")
    if config.signal_mode is not SignalMode.PORTFOLIO_TREND_ENSEMBLE:
        raise ValueError("settings do not select portfolio_trend_ensemble")
    if require_entries_disabled and config.entries_enabled:
        raise ValueError("initial portfolio deployment requires entries_enabled=false")
    trend_config_from_trading_config(config)
    return config


def sanitized_summary(config: TradingConfig) -> dict[str, object]:
    return {
        "network": config.network.value,
        "signal_mode": config.signal_mode.value,
        "symbols": list(config.symbols),
        "entries_enabled": config.entries_enabled,
        "leverage": config.leverage,
        "max_order_notional_usdc": config.max_order_notional_usdc,
        "max_symbol_notional_usdc": config.max_symbol_notional_usdc,
        "max_total_notional_usdc": config.max_total_notional_usdc,
        "max_positions": config.max_positions,
        "rebalance_tolerance_usdc": config.portfolio_rebalance_tolerance_usdc,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--secrets", type=Path, required=True)
    parser.add_argument(
        "--allow-entries-enabled",
        action="store_true",
        help="accept an already activated testnet file after initial acceptance",
    )
    args = parser.parse_args()
    document = json.loads(args.settings.read_text(encoding="utf-8"))
    config = validate_portfolio_testnet_settings(
        document,
        require_entries_disabled=not args.allow_entries_enabled,
    )
    secrets = json.loads(args.secrets.read_text(encoding="utf-8"))
    validate_deployment_secrets(secrets, config, expected_network="testnet")
    print(json.dumps(sanitized_summary(config), sort_keys=True))


if __name__ == "__main__":
    main()
