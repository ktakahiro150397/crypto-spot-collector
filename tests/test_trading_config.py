import math
from datetime import datetime, timezone

import pytest

from crypto_spot_collector.trading.config import (
    MAINNET_CONFIRMATION,
    Network,
    SignalMode,
    TradingConfig,
    next_timeframe_boundary,
)

SYMBOLS = ("BTC/USDC:USDC",)


def valid_config(**overrides: object) -> TradingConfig:
    values: dict[str, object] = {
        "symbols": SYMBOLS,
        "timeframe": "30m",
        "amount_usdc": 10.0,
        "leverage": 5,
        "take_profit_roe": 15.0,
        "stop_loss_roe": 3.0,
        "trailing_interval_minutes": 3,
        "trailing_activation_roe": 7.0,
        "sar_consecutive_count": 4,
        "sar_close_consecutive_count": 2,
        "price_change_threshold_percent": 999.0,
        "max_order_notional_usdc": 25.0,
        "max_symbol_notional_usdc": 50.0,
        "max_total_notional_usdc": 100.0,
        "max_positions": 2,
        "max_leverage": 5,
        "min_free_collateral_usdc": 10.0,
    }
    values.update(overrides)
    return TradingConfig(**values)  # type: ignore[arg-type]


def test_testnet_is_safe_default() -> None:
    config = valid_config()
    config.validate()
    assert config.network is Network.TESTNET
    assert config.testnet is True


@pytest.mark.parametrize(
    ("allow_mainnet", "confirmation"),
    [(False, ""), (True, ""), (False, MAINNET_CONFIRMATION)],
)
def test_mainnet_requires_both_interlocks(
    allow_mainnet: bool, confirmation: str
) -> None:
    config = valid_config(
        network=Network.MAINNET,
        allow_mainnet=allow_mainnet,
        mainnet_confirmation=confirmation,
    )
    with pytest.raises(ValueError, match="mainnet"):
        config.validate()


def test_explicit_mainnet_configuration_is_accepted() -> None:
    config = valid_config(
        network=Network.MAINNET,
        allow_mainnet=True,
        mainnet_confirmation=MAINNET_CONFIRMATION,
    )
    config.validate()
    assert config.testnet is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("symbols", ()),
        ("timeframe", "monthly"),
        ("amount_usdc", 0),
        ("leverage", 0),
        ("take_profit_roe", 0),
        ("stop_loss_roe", -1),
        ("trailing_interval_minutes", 0),
        ("trailing_activation_roe", 0),
        ("max_order_notional_usdc", math.nan),
        ("max_symbol_notional_usdc", math.inf),
        ("max_total_notional_usdc", -math.inf),
        ("min_free_collateral_usdc", math.nan),
        ("entry_kill_switch_file", ""),
    ],
)
def test_invalid_values_fail_before_runtime(field: str, value: object) -> None:
    config = valid_config(**{field: value})
    with pytest.raises(ValueError):
        config.validate()


def test_trailing_must_activate_before_take_profit() -> None:
    with pytest.raises(ValueError, match="lower than take_profit"):
        valid_config(take_profit_roe=7.0, trailing_activation_roe=7.0).validate()


def test_legacy_mapping_without_sandbox_flag_remains_testnet() -> None:
    config = TradingConfig.from_mapping({"perpetual": {}}, symbols=SYMBOLS)
    assert config.network is Network.TESTNET
    assert config.signal_mode is SignalMode.SAR_ONLY


def test_signal_mode_is_explicit_and_exclusive() -> None:
    config = TradingConfig.from_mapping(
        {"perpetual": {"signal_mode": "price_change_only"}}, symbols=SYMBOLS
    )
    assert config.signal_mode is SignalMode.PRICE_CHANGE_ONLY

    with pytest.raises(ValueError, match="signal mode"):
        TradingConfig.from_mapping(
            {"perpetual": {"signal_mode": "sar_or_price"}}, symbols=SYMBOLS
        )


def test_margin_mode_is_explicit_and_validated() -> None:
    config = TradingConfig.from_mapping(
        {"perpetual": {"margin_mode": "isolated"}}, symbols=SYMBOLS
    )
    assert config.margin_mode == "isolated"

    with pytest.raises(ValueError, match="margin_mode"):
        valid_config(margin_mode="portfolio").validate()


def test_symbols_are_loaded_from_validated_mapping() -> None:
    config = TradingConfig.from_mapping({"perpetual": {"symbols": list(SYMBOLS)}})
    assert config.symbols == SYMBOLS


def test_canary_requires_one_symbol_and_one_position() -> None:
    valid_config(canary_mode=True, max_positions=1).validate()

    with pytest.raises(ValueError, match="exactly one symbol"):
        valid_config(
            symbols=("BTC/USDC:USDC", "ETH/USDC:USDC"),
            canary_mode=True,
            max_positions=1,
        ).validate()
    with pytest.raises(ValueError, match="max_positions=1"):
        valid_config(canary_mode=True, max_positions=2).validate()


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_order_notional_usdc": 60.0},
        {"max_symbol_notional_usdc": 110.0},
        {"amount_usdc": 30.0},
        {"leverage": 6},
    ],
)
def test_conflicting_risk_limits_are_rejected(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        valid_config(**overrides).validate()


def test_mainnet_mapping_requires_explicit_risk_limits() -> None:
    with pytest.raises(ValueError, match="explicit risk limits"):
        TradingConfig.from_mapping(
            {
                "network": "mainnet",
                "allow_mainnet": True,
                "perpetual": {"symbols": list(SYMBOLS)},
            },
            mainnet_confirmation=MAINNET_CONFIRMATION,
        )


def test_mainnet_canary_mapping_accepts_one_symbol_and_explicit_limits() -> None:
    config = TradingConfig.from_mapping(
        {
            "network": "mainnet",
            "allow_mainnet": True,
            "perpetual": {
                "symbols": list(SYMBOLS),
                "canary_mode": True,
                "amountByUSDC": 12,
                "leverage": 2,
                "risk": {
                    "max_order_notional_usdc": 12,
                    "max_symbol_notional_usdc": 12,
                    "max_total_notional_usdc": 12,
                    "max_positions": 1,
                    "max_leverage": 2,
                    "min_free_collateral_usdc": 25,
                },
            },
        },
        mainnet_confirmation=MAINNET_CONFIRMATION,
    )

    assert config.network is Network.MAINNET
    assert config.canary_mode is True
    assert config.symbols == SYMBOLS


@pytest.mark.parametrize(
    ("timeframe", "expected"),
    [
        ("30m", datetime(2026, 8, 13, 12, 30, tzinfo=timezone.utc)),
        ("2h", datetime(2026, 8, 13, 14, 0, tzinfo=timezone.utc)),
        ("1d", datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc)),
    ],
)
def test_validated_timeframes_have_scheduler_boundaries(
    timeframe: str,
    expected: datetime,
) -> None:
    now = datetime(2026, 8, 13, 12, 17, tzinfo=timezone.utc)
    assert next_timeframe_boundary(now, timeframe) == expected
