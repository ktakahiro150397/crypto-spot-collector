"""Offline settings gate for the observation-only mainnet portfolio service."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from crypto_spot_collector.scripts.portfolio_testnet_preflight import sanitized_summary
from crypto_spot_collector.trading.config import Network, SignalMode, TradingConfig
from crypto_spot_collector.trading.deployment import validate_deployment_secrets
from crypto_spot_collector.trading.portfolio_execution import (
    trend_config_from_trading_config,
)


def validate_portfolio_mainnet_disabled_settings(
    document: Mapping[str, Any],
    *,
    mainnet_confirmation: str,
) -> TradingConfig:
    settings = document.get("settings")
    if not isinstance(settings, Mapping):
        raise ValueError("settings object is missing")
    config = TradingConfig.from_mapping(
        settings,
        mainnet_confirmation=mainnet_confirmation,
    )
    if config.network is not Network.MAINNET:
        raise ValueError("portfolio mainnet preflight requires network=mainnet")
    if config.signal_mode is not SignalMode.PORTFOLIO_TREND_ENSEMBLE:
        raise ValueError("settings do not select portfolio_trend_ensemble")
    if config.entries_enabled:
        raise ValueError("mainnet portfolio observer requires entries_enabled=false")
    trend_config_from_trading_config(config)
    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--secrets", type=Path, required=True)
    args = parser.parse_args()
    document = json.loads(args.settings.read_text(encoding="utf-8"))
    config = validate_portfolio_mainnet_disabled_settings(
        document,
        mainnet_confirmation=os.getenv("HYPERLIQUID_MAINNET_CONFIRMATION", ""),
    )
    secrets = json.loads(args.secrets.read_text(encoding="utf-8"))
    validate_deployment_secrets(secrets, config, expected_network="mainnet")
    print(json.dumps(sanitized_summary(config), sort_keys=True))


if __name__ == "__main__":
    main()
