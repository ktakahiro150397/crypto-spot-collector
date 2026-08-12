import pytest

from crypto_spot_collector.trading.config import (
    MAINNET_CONFIRMATION,
    Network,
    SignalMode,
    TradingConfig,
)

SYMBOLS = ("BTC/USDC:USDC",)


def valid_config(**overrides: object) -> TradingConfig:
    values: dict[str, object] = {
        "symbols": SYMBOLS,
        "timeframe": "30m",
        "amount_usdc": 10.0,
        "leverage": 5,
        "take_profit_roe": 3.0,
        "stop_loss_roe": 0.2,
        "trailing_interval_minutes": 3,
        "trailing_activation_roe": 7.0,
        "sar_consecutive_count": 4,
        "sar_close_consecutive_count": 2,
        "price_change_threshold_percent": 999.0,
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
    ],
)
def test_invalid_values_fail_before_runtime(field: str, value: object) -> None:
    config = valid_config(**{field: value})
    with pytest.raises(ValueError):
        config.validate()


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
