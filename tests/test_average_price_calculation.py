"""Test for average price calculation logic."""

import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock

from src.crypto_spot_collector.repository.trade_data_repository import (
    TradeDataRepository,
)


class TestAveragePriceCalculation(unittest.TestCase):
    """Test cases for average price calculation."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_session = Mock()
        self.repository = TradeDataRepository(session=self.mock_session)

        # Mock cryptocurrency
        self.mock_crypto = Mock()
        self.mock_crypto.id = 1
        self.mock_crypto.symbol = "BTC"

    def test_no_trades_returns_zero(self):
        """Test that no trades returns (0.0, 0.0)."""
        # Mock no cryptocurrency found
        self.mock_session.query.return_value.filter.return_value.one_or_none.return_value = None

        quantity, avg_price = self.repository.get_current_position_and_avg_price(
            "BTC")

        self.assertEqual(quantity, 0.0)
        self.assertEqual(avg_price, 0.0)

    def test_single_buy_trade(self):
        """Test single buy trade calculation."""
        # Mock cryptocurrency found
        self.mock_session.query.return_value.filter.return_value.one_or_none.return_value = self.mock_crypto

        # Mock single buy trade
        mock_trade = Mock()
        mock_trade.position_type = "LONG"
        mock_trade.price = Decimal('50000.0')
        mock_trade.quantity = Decimal('1.0')
        mock_trade.fee = Decimal('50.0')
        mock_trade.timestamp_utc = datetime(2025, 1, 1)

        self.mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            mock_trade]

        quantity, avg_price = self.repository.get_current_position_and_avg_price(
            "BTC")

        # Expected: quantity = 1.0, avg_price = (50000 * 1 + 50) / 1 = 50050
        self.assertEqual(quantity, 1.0)
        self.assertEqual(avg_price, 50050.0)

    def test_multiple_buy_trades(self):
        """Test multiple buy trades calculation."""
        self.mock_session.query.return_value.filter.return_value.one_or_none.return_value = self.mock_crypto

        # Mock multiple buy trades
        trade1 = Mock()
        trade1.position_type = "LONG"
        trade1.price = Decimal('50000.0')
        trade1.quantity = Decimal('1.0')
        trade1.fee = Decimal('50.0')
        trade1.timestamp_utc = datetime(2025, 1, 1)

        trade2 = Mock()
        trade2.position_type = "LONG"
        trade2.price = Decimal('60000.0')
        trade2.quantity = Decimal('2.0')
        trade2.fee = Decimal('100.0')
        trade2.timestamp_utc = datetime(2025, 1, 2)

        self.mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            trade1, trade2]

        quantity, avg_price = self.repository.get_current_position_and_avg_price(
            "BTC")

        # Expected:
        # After trade1: 1.0 BTC @ 50050
        # After trade2: 3.0 BTC @ (50050 + 120100) / 3 = 56716.67
        self.assertEqual(quantity, 3.0)
        self.assertAlmostEqual(avg_price, 56716.67, places=2)

    def test_buy_and_sell_trades(self):
        """Test buy and sell trades calculation."""
        self.mock_session.query.return_value.filter.return_value.one_or_none.return_value = self.mock_crypto

        # Mock buy and sell trades
        buy_trade = Mock()
        buy_trade.position_type = "LONG"
        buy_trade.price = Decimal('50000.0')
        buy_trade.quantity = Decimal('2.0')
        buy_trade.fee = Decimal('100.0')
        buy_trade.timestamp_utc = datetime(2025, 1, 1)

        sell_trade = Mock()
        sell_trade.position_type = "SHORT"
        sell_trade.price = Decimal('55000.0')
        sell_trade.quantity = Decimal('1.0')
        sell_trade.fee = Decimal('55.0')
        sell_trade.timestamp_utc = datetime(2025, 1, 2)

        self.mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            buy_trade, sell_trade]

        quantity, avg_price = self.repository.get_current_position_and_avg_price(
            "BTC")

        # Expected:
        # After buy: 2.0 BTC @ (50000*2 + 100)/2 = 50050
        # After sell: 1.0 BTC @ 50050 (unchanged)
        self.assertEqual(quantity, 1.0)
        self.assertEqual(avg_price, 50050.0)

    def test_sell_more_than_holdings(self):
        """Test selling more than current holdings."""
        self.mock_session.query.return_value.filter.return_value.one_or_none.return_value = self.mock_crypto

        buy_trade = Mock()
        buy_trade.position_type = "LONG"
        buy_trade.price = Decimal('50000.0')
        buy_trade.quantity = Decimal('1.0')
        buy_trade.fee = Decimal('50.0')
        buy_trade.timestamp_utc = datetime(2025, 1, 1)

        sell_trade = Mock()
        sell_trade.position_type = "SHORT"
        sell_trade.price = Decimal('55000.0')
        sell_trade.quantity = Decimal('2.0')  # More than holdings
        sell_trade.fee = Decimal('110.0')
        sell_trade.timestamp_utc = datetime(2025, 1, 2)

        self.mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            buy_trade, sell_trade]

        quantity, avg_price = self.repository.get_current_position_and_avg_price(
            "BTC")

        # Expected: All holdings sold, remaining 0.0
        self.assertEqual(quantity, 0.0)
        self.assertEqual(avg_price, 0.0)

    def test_complex_trading_scenario(self):
        """Test complex trading scenario with multiple buys and sells."""
        self.mock_session.query.return_value.filter.return_value.one_or_none.return_value = self.mock_crypto

        trades = []

        # Buy 1 BTC @ 50,000 (fee: 50)
        trade1 = Mock()
        trade1.position_type = "LONG"
        trade1.price = Decimal('50000.0')
        trade1.quantity = Decimal('1.0')
        trade1.fee = Decimal('50.0')
        trade1.timestamp_utc = datetime(2025, 1, 1)
        trades.append(trade1)

        # Buy 2 BTC @ 60,000 (fee: 100)
        trade2 = Mock()
        trade2.position_type = "LONG"
        trade2.price = Decimal('60000.0')
        trade2.quantity = Decimal('2.0')
        trade2.fee = Decimal('100.0')
        trade2.timestamp_utc = datetime(2025, 1, 2)
        trades.append(trade2)

        # Sell 1.5 BTC @ 55,000 (fee: 75)
        trade3 = Mock()
        trade3.position_type = "SHORT"
        trade3.price = Decimal('55000.0')
        trade3.quantity = Decimal('1.5')
        trade3.fee = Decimal('75.0')
        trade3.timestamp_utc = datetime(2025, 1, 3)
        trades.append(trade3)

        self.mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = trades

        quantity, avg_price = self.repository.get_current_position_and_avg_price(
            "BTC")

        # Expected calculation:
        # After trade1: 1.0 BTC @ 50050
        # After trade2: 3.0 BTC @ (50050 + 120100) / 3 = 56716.67
        # After trade3: 1.5 BTC @ 56716.67 (unchanged)
        self.assertEqual(quantity, 1.5)
        self.assertAlmostEqual(avg_price, 56716.67, places=2)


if __name__ == "__main__":
    unittest.main()
