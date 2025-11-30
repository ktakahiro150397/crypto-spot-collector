"""Tests for exchange interface."""

from crypto_spot_collector.exchange import IExchange, BybitExchange, PositionSide, SpotAsset, SpotOrderResult
from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange


def test_bybit_exchange_implements_interface() -> None:
    """Test that BybitExchange implements IExchange interface."""
    assert issubclass(BybitExchange, IExchange), \
        "BybitExchange should implement IExchange"


def test_hyperliquid_exchange_implements_interface() -> None:
    """Test that HyperLiquidExchange implements IExchange interface."""
    assert issubclass(HyperLiquidExchange, IExchange), \
        "HyperLiquidExchange should implement IExchange"


def test_interface_exports() -> None:
    """Test that all expected types are exported from exchange module."""
    from crypto_spot_collector.exchange import IExchange, BybitExchange
    from crypto_spot_collector.exchange import PositionSide, SpotAsset, SpotOrderResult

    assert IExchange is not None
    assert BybitExchange is not None
    assert PositionSide is not None
    assert SpotAsset is not None
    assert SpotOrderResult is not None


def test_position_side_enum() -> None:
    """Test PositionSide enum values."""
    assert PositionSide.LONG.value == "long"
    assert PositionSide.SHORT.value == "short"
    assert PositionSide.ALL.value == "all"


def test_spot_order_result_dataclass() -> None:
    """Test SpotOrderResult dataclass."""
    result = SpotOrderResult(
        order_id="test-id",
        symbol="BTC/USDT",
        amount=1.0,
        price=50000.0,
        order_value=50000.0,
        original_order={"test": "order"}
    )
    assert result.order_id == "test-id"
    assert result.symbol == "BTC/USDT"
    assert result.amount == 1.0
    assert result.price == 50000.0
    assert result.order_value == 50000.0
    assert result.original_order == {"test": "order"}


def test_spot_asset_dataclass() -> None:
    """Test SpotAsset dataclass."""
    asset = SpotAsset(
        symbol="BTC",
        total_amount=1.0,
        current_value=50000.0,
        profit_loss=1000.0
    )
    assert asset.symbol == "BTC"
    assert asset.total_amount == 1.0
    assert asset.current_value == 50000.0
    assert asset.profit_loss == 1000.0
