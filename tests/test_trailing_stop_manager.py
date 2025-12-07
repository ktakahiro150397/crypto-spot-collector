"""Tests for trailing stop manager with acceleration coefficient."""

import pytest

from crypto_spot_collector.exchange.trailing_stop_manager import TrailingStopManager


class TestTrailingStopManager:
    """Test suite for TrailingStopManager."""

    def test_initialization(self) -> None:
        """Test manager initialization with default and custom parameters."""
        # Test default initialization
        tsm = TrailingStopManager()
        assert tsm.initial_af == 0.02
        assert tsm.max_af == 0.2
        assert tsm.af_increment == 0.02
        assert len(tsm.positions) == 0

        # Test custom initialization
        tsm_custom = TrailingStopManager(
            initial_af=0.01,
            max_af=0.15,
            af_increment=0.01,
        )
        assert tsm_custom.initial_af == 0.01
        assert tsm_custom.max_af == 0.15
        assert tsm_custom.af_increment == 0.01

    def test_add_position(self) -> None:
        """Test adding a position to tracking."""
        tsm = TrailingStopManager()

        tsm.add_position(
            symbol="BTC/USDC:USDC",
            side="long",
            entry_price=50000.0,
        )

        assert "BTC/USDC:USDC" in tsm.positions
        position = tsm.positions["BTC/USDC:USDC"]
        assert position.symbol == "BTC/USDC:USDC"
        assert position.side == "long"
        assert position.entry_price == 50000.0
        assert position.highest_price == 50000.0
        assert position.lowest_price == 50000.0
        assert position.acceleration_factor == 0.02
        assert position.current_sl_order_id is None

    def test_remove_position(self) -> None:
        """Test removing a position from tracking."""
        tsm = TrailingStopManager()
        tsm.add_position("BTC/USDC:USDC", "long", 50000.0)

        assert "BTC/USDC:USDC" in tsm.positions

        tsm.remove_position("BTC/USDC:USDC")
        assert "BTC/USDC:USDC" not in tsm.positions

    def test_long_position_new_high(self) -> None:
        """Test long position stop loss calculation with new highs."""
        tsm = TrailingStopManager(
            initial_af=0.02,
            max_af=0.2,
            af_increment=0.02,
        )

        # Add long position at 100
        tsm.add_position("BTC/USDC:USDC", "long", 100.0)

        # Price moves to 110 (new high)
        sl_price = tsm.update_and_calculate_sl("BTC/USDC:USDC", 110.0)
        position = tsm.get_position("BTC/USDC:USDC")

        # AF should increase to 0.04
        assert position.acceleration_factor == 0.04
        assert position.highest_price == 110.0

        # SL = highest - (highest - entry) * AF
        # SL = 110 - (110 - 100) * 0.04 = 110 - 0.4 = 109.6
        assert sl_price == pytest.approx(109.6, rel=1e-5)

        # Price moves to 120 (another new high)
        sl_price = tsm.update_and_calculate_sl("BTC/USDC:USDC", 120.0)
        position = tsm.get_position("BTC/USDC:USDC")

        # AF should increase to 0.06
        assert position.acceleration_factor == 0.06
        assert position.highest_price == 120.0

        # SL = 120 - (120 - 100) * 0.06 = 120 - 1.2 = 118.8
        assert sl_price == pytest.approx(118.8, rel=1e-5)

    def test_long_position_no_new_high(self) -> None:
        """Test long position when price doesn't make new high."""
        tsm = TrailingStopManager(initial_af=0.02, max_af=0.2, af_increment=0.02)

        tsm.add_position("BTC/USDC:USDC", "long", 100.0)

        # Price moves to 110
        tsm.update_and_calculate_sl("BTC/USDC:USDC", 110.0)
        position = tsm.get_position("BTC/USDC:USDC")
        initial_af = position.acceleration_factor

        # Price retraces to 105 (not a new high)
        sl_price = tsm.update_and_calculate_sl("BTC/USDC:USDC", 105.0)
        position = tsm.get_position("BTC/USDC:USDC")

        # AF should NOT increase
        assert position.acceleration_factor == initial_af
        # Highest should remain at 110
        assert position.highest_price == 110.0

        # SL still calculated from highest price
        expected_sl = 110.0 - (110.0 - 100.0) * initial_af
        assert sl_price == pytest.approx(expected_sl, rel=1e-5)

    def test_short_position_new_low(self) -> None:
        """Test short position stop loss calculation with new lows."""
        tsm = TrailingStopManager(
            initial_af=0.02,
            max_af=0.2,
            af_increment=0.02,
        )

        # Add short position at 100
        tsm.add_position("BTC/USDC:USDC", "short", 100.0)

        # Price moves to 90 (new low)
        sl_price = tsm.update_and_calculate_sl("BTC/USDC:USDC", 90.0)
        position = tsm.get_position("BTC/USDC:USDC")

        # AF should increase to 0.04
        assert position.acceleration_factor == 0.04
        assert position.lowest_price == 90.0

        # SL = lowest + (entry - lowest) * AF
        # SL = 90 + (100 - 90) * 0.04 = 90 + 0.4 = 90.4
        assert sl_price == pytest.approx(90.4, rel=1e-5)

        # Price moves to 80 (another new low)
        sl_price = tsm.update_and_calculate_sl("BTC/USDC:USDC", 80.0)
        position = tsm.get_position("BTC/USDC:USDC")

        # AF should increase to 0.06
        assert position.acceleration_factor == 0.06
        assert position.lowest_price == 80.0

        # SL = 80 + (100 - 80) * 0.06 = 80 + 1.2 = 81.2
        assert sl_price == pytest.approx(81.2, rel=1e-5)

    def test_short_position_no_new_low(self) -> None:
        """Test short position when price doesn't make new low."""
        tsm = TrailingStopManager(initial_af=0.02, max_af=0.2, af_increment=0.02)

        tsm.add_position("BTC/USDC:USDC", "short", 100.0)

        # Price moves to 90
        tsm.update_and_calculate_sl("BTC/USDC:USDC", 90.0)
        position = tsm.get_position("BTC/USDC:USDC")
        initial_af = position.acceleration_factor

        # Price retraces to 95 (not a new low)
        sl_price = tsm.update_and_calculate_sl("BTC/USDC:USDC", 95.0)
        position = tsm.get_position("BTC/USDC:USDC")

        # AF should NOT increase
        assert position.acceleration_factor == initial_af
        # Lowest should remain at 90
        assert position.lowest_price == 90.0

        # SL still calculated from lowest price
        expected_sl = 90.0 + (100.0 - 90.0) * initial_af
        assert sl_price == pytest.approx(expected_sl, rel=1e-5)

    def test_af_max_limit(self) -> None:
        """Test that acceleration factor doesn't exceed maximum."""
        tsm = TrailingStopManager(
            initial_af=0.02,
            max_af=0.1,  # Low max for testing
            af_increment=0.02,
        )

        tsm.add_position("BTC/USDC:USDC", "long", 100.0)

        # Make several new highs to reach max AF
        for price in [110, 120, 130, 140, 150, 160]:
            tsm.update_and_calculate_sl("BTC/USDC:USDC", float(price))

        position = tsm.get_position("BTC/USDC:USDC")
        # AF should be capped at max_af
        assert position.acceleration_factor == 0.1

    def test_update_sl_order_id(self) -> None:
        """Test updating stop loss order ID."""
        tsm = TrailingStopManager()
        tsm.add_position("BTC/USDC:USDC", "long", 100.0)

        # Initially no order ID
        position = tsm.get_position("BTC/USDC:USDC")
        assert position.current_sl_order_id is None

        # Update order ID
        tsm.update_sl_order_id("BTC/USDC:USDC", "order123")
        position = tsm.get_position("BTC/USDC:USDC")
        assert position.current_sl_order_id == "order123"

    def test_get_nonexistent_position(self) -> None:
        """Test getting a position that doesn't exist."""
        tsm = TrailingStopManager()
        position = tsm.get_position("NONEXISTENT")
        assert position is None

    def test_update_nonexistent_position(self) -> None:
        """Test updating a position that doesn't exist."""
        tsm = TrailingStopManager()
        sl_price = tsm.update_and_calculate_sl("NONEXISTENT", 100.0)
        assert sl_price is None
