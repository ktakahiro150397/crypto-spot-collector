"""Tests for Bybit sell_spot method."""

from unittest.mock import MagicMock, patch

import pytest

from crypto_spot_collector.exchange.bybit import BybitExchange, SpotSellResult


@pytest.fixture
def mock_exchange():
    """Create a mock BybitExchange instance."""
    with patch("crypto_spot_collector.exchange.bybit.ccxt.bybit") as mock_ccxt:
        mock_ccxt.return_value = MagicMock()
        exchange = BybitExchange(apiKey="test_key", secret="test_secret")
        return exchange


def test_sell_spot_basic(mock_exchange):
    """Test basic sell_spot functionality."""
    # Mock the exchange methods
    mock_exchange.exchange.create_order = MagicMock(
        return_value={
            "id": "order123",
            "symbol": "BTC/USDT",
            "side": "sell",
            "type": "market",
            "amount": 0.5,
            "filled": 0.5,
            "average": 50000.0,
            "status": "closed",
        }
    )

    mock_exchange.fetch_price = MagicMock(return_value={"last": 50000.0})
    mock_exchange.fetch_average_buy_price_spot = MagicMock(return_value=48000.0)

    # Execute sell_spot
    order, result = mock_exchange.sell_spot(symbol="BTC", amount=0.5)

    # Verify the result
    assert isinstance(result, SpotSellResult)
    assert result.order_id == "order123"
    assert result.symbol == "BTC/USDT"
    assert result.amount == 0.5
    assert result.price == 50000.0
    assert result.order_value == 25000.0  # 0.5 * 50000
    # PnL = (50000 - 48000) * 0.5 = 1000.0
    assert result.profit_loss == 1000.0

    # Verify create_order was called correctly
    mock_exchange.exchange.create_order.assert_called_once_with(
        symbol="BTC/USDT", type="market", side="sell", amount=0.5, params={}
    )


def test_sell_spot_with_symbol_suffix(mock_exchange):
    """Test sell_spot with symbol already having /USDT suffix."""
    mock_exchange.exchange.create_order = MagicMock(
        return_value={
            "id": "order456",
            "symbol": "ETH/USDT",
            "filled": 1.0,
            "average": 3000.0,
        }
    )

    mock_exchange.fetch_price = MagicMock(return_value={"last": 3000.0})
    mock_exchange.fetch_average_buy_price_spot = MagicMock(return_value=2800.0)

    # Execute with symbol already having /USDT
    order, result = mock_exchange.sell_spot(symbol="ETH/USDT", amount=1.0)

    assert result.symbol == "ETH/USDT"
    assert result.amount == 1.0
    assert result.price == 3000.0


def test_sell_spot_no_average_price(mock_exchange):
    """Test sell_spot when no average buy price is available."""
    mock_exchange.exchange.create_order = MagicMock(
        return_value={
            "id": "order789",
            "symbol": "SOL/USDT",
            "filled": 10.0,
            "average": 100.0,
        }
    )

    mock_exchange.fetch_price = MagicMock(return_value={"last": 100.0})
    # Return 0 when no buy orders found
    mock_exchange.fetch_average_buy_price_spot = MagicMock(return_value=0.0)

    order, result = mock_exchange.sell_spot(symbol="SOL", amount=10.0)

    # PnL should be 0 when no average price available
    assert result.profit_loss == 0.0
    assert result.amount == 10.0
    assert result.price == 100.0


def test_sell_spot_pnl_calculation_negative(mock_exchange):
    """Test sell_spot with negative PnL (loss)."""
    mock_exchange.exchange.create_order = MagicMock(
        return_value={
            "id": "order999",
            "symbol": "XRP/USDT",
            "filled": 100.0,
            "average": 0.5,
        }
    )

    mock_exchange.fetch_price = MagicMock(return_value={"last": 0.5})
    # Average buy price is higher than sell price (loss scenario)
    mock_exchange.fetch_average_buy_price_spot = MagicMock(return_value=0.6)

    order, result = mock_exchange.sell_spot(symbol="XRP", amount=100.0)

    # PnL = (0.5 - 0.6) * 100 = -10.0
    assert result.profit_loss == -10.0
    assert result.amount == 100.0


def test_sell_spot_exception_handling(mock_exchange):
    """Test sell_spot handles exceptions properly."""
    mock_exchange.exchange.create_order = MagicMock(side_effect=Exception("API Error"))

    mock_exchange.fetch_price = MagicMock(return_value={"last": 50000.0})
    mock_exchange.fetch_average_buy_price_spot = MagicMock(return_value=48000.0)

    # Should raise the exception
    with pytest.raises(Exception) as exc_info:
        mock_exchange.sell_spot(symbol="BTC", amount=0.5)

    assert "API Error" in str(exc_info.value)


def test_sell_spot_pnl_calculation_exception(mock_exchange):
    """Test sell_spot when PnL calculation fails."""
    mock_exchange.exchange.create_order = MagicMock(
        return_value={
            "id": "order111",
            "symbol": "LINK/USDT",
            "filled": 5.0,
            "average": 10.0,
        }
    )

    mock_exchange.fetch_price = MagicMock(return_value={"last": 10.0})
    # Simulate exception in fetching average price
    mock_exchange.fetch_average_buy_price_spot = MagicMock(
        side_effect=Exception("Database error")
    )

    # Should still complete the sale with PnL = 0
    order, result = mock_exchange.sell_spot(symbol="LINK", amount=5.0)

    assert result.profit_loss == 0.0
    assert result.amount == 5.0
    assert result.order_id == "order111"
