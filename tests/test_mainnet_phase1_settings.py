import copy
import json
from pathlib import Path

import pytest

from crypto_spot_collector.trading.config import (
    MAINNET_CONFIRMATION,
    Network,
    TradingConfig,
)

SAMPLE = (
    Path(__file__).parents[1]
    / "deploy"
    / "settings"
    / "hyperliquid.mainnet-phase1.json.sample"
)


def test_phase1_sample_is_fail_closed_and_matches_approved_limits() -> None:
    settings = json.loads(SAMPLE.read_text(encoding="utf-8"))["settings"]
    perpetual = settings["perpetual"]
    risk = perpetual["risk"]

    assert settings["network"] == "mainnet"
    assert settings["allow_mainnet"] is False
    assert perpetual["entries_enabled"] is False
    assert perpetual["symbols"] == ["ETH/USDC:USDC", "BTC/USDC:USDC"]
    assert perpetual["canary_mode"] is False
    assert perpetual["amountByUSDC"] == 12.5
    assert perpetual["leverage"] == 1
    assert risk == {
        "max_order_notional_usdc": 12.5,
        "max_symbol_notional_usdc": 12.5,
        "max_total_notional_usdc": 25.0,
        "max_positions": 2,
        "max_leverage": 1,
        "min_free_collateral_usdc": 10.0,
    }

    with pytest.raises(ValueError, match="allow_mainnet"):
        TradingConfig.from_mapping(
            settings,
            mainnet_confirmation=MAINNET_CONFIRMATION,
        )


def test_phase1_sample_passes_validation_only_after_mainnet_interlock() -> None:
    settings = json.loads(SAMPLE.read_text(encoding="utf-8"))["settings"]
    enabled = copy.deepcopy(settings)
    enabled["allow_mainnet"] = True

    config = TradingConfig.from_mapping(
        enabled,
        mainnet_confirmation=MAINNET_CONFIRMATION,
    )

    assert config.network is Network.MAINNET
    assert config.symbols == ("ETH/USDC:USDC", "BTC/USDC:USDC")
    assert config.entries_enabled is False
    assert config.max_positions == 2
    assert config.max_total_notional_usdc == 25.0
