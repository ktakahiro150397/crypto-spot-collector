"""Trailing Stop Manager with Acceleration Coefficient for Hyperliquid Perp."""

from dataclasses import dataclass
from typing import Optional

from loguru import logger


@dataclass
class PositionTrailingStop:
    """Position state for trailing stop with acceleration coefficient."""

    symbol: str
    side: str  # "long" or "short"
    entry_price: float
    highest_price: float  # For long positions
    lowest_price: float  # For short positions
    acceleration_factor: float
    current_sl_order_id: Optional[str] = None


class TrailingStopManager:
    """
    Manages trailing stops with acceleration coefficient for perpetual positions.

    Based on Parabolic SAR concept where the stop loss accelerates as the position
    moves in profit. The acceleration factor increases as the price reaches new highs/lows.
    """

    def __init__(
        self,
        initial_af: float = 0.02,
        max_af: float = 0.2,
        af_increment: float = 0.02,
    ):
        """
        Initialize the trailing stop manager.

        Args:
            initial_af: Initial acceleration factor (default 0.02)
            max_af: Maximum acceleration factor (default 0.2)
            af_increment: Increment for acceleration factor (default 0.02)
        """
        self.initial_af = initial_af
        self.max_af = max_af
        self.af_increment = af_increment
        self.positions: dict[str, PositionTrailingStop] = {}

        logger.info(
            f"TrailingStopManager initialized: "
            f"initial_af={initial_af}, max_af={max_af}, af_increment={af_increment}"
        )

    def add_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        sl_order_id: Optional[str] = None,
    ) -> None:
        """
        Add a new position to track.

        Args:
            symbol: Trading symbol
            side: Position side ("long" or "short")
            entry_price: Entry price of the position
            sl_order_id: Stop loss order ID if exists
        """
        position = PositionTrailingStop(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            highest_price=entry_price,
            lowest_price=entry_price,
            acceleration_factor=self.initial_af,
            current_sl_order_id=sl_order_id,
        )
        self.positions[symbol] = position
        logger.info(f"Added position for tracking: {symbol} {side} @ {entry_price}")

    def remove_position(self, symbol: str) -> None:
        """Remove a position from tracking."""
        if symbol in self.positions:
            del self.positions[symbol]
            logger.info(f"Removed position from tracking: {symbol}")

    def update_and_calculate_sl(
        self,
        symbol: str,
        current_price: float,
    ) -> Optional[float]:
        """
        Update position state and calculate new stop loss price.

        Returns the new stop loss price if it should be updated, None otherwise.

        Args:
            symbol: Trading symbol
            current_price: Current market price

        Returns:
            New stop loss price if update is needed, None otherwise
        """
        if symbol not in self.positions:
            logger.warning(f"Position {symbol} not found in tracking")
            return None

        position = self.positions[symbol]

        if position.side == "long":
            return self._update_long_position(position, current_price)
        else:
            return self._update_short_position(position, current_price)

    def _update_long_position(
        self,
        position: PositionTrailingStop,
        current_price: float,
    ) -> Optional[float]:
        """
        Update long position and calculate new stop loss.

        For long positions:
        - Track highest price reached
        - Increase acceleration factor when new high is reached
        - Calculate SL = highest_price - (highest_price - entry_price) * acceleration_factor
        """
        # Check if we have a new high
        if current_price > position.highest_price:
            position.highest_price = current_price
            # Increase acceleration factor
            position.acceleration_factor = min(
                position.acceleration_factor + self.af_increment, self.max_af
            )
            logger.debug(
                f"New high for {position.symbol}: {current_price:.4f}, "
                f"AF: {position.acceleration_factor:.4f}"
            )

        # Calculate trailing stop loss
        # SL moves up based on the profit and acceleration factor
        profit_distance = position.highest_price - position.entry_price
        sl_distance = profit_distance * position.acceleration_factor
        new_sl_price = position.highest_price - sl_distance

        logger.debug(
            f"Long SL calculation for {position.symbol}: "
            f"high={position.highest_price:.4f}, entry={position.entry_price:.4f}, "
            f"profit_dist={profit_distance:.4f}, sl_dist={sl_distance:.4f}, "
            f"new_sl={new_sl_price:.4f}"
        )

        return new_sl_price

    def _update_short_position(
        self,
        position: PositionTrailingStop,
        current_price: float,
    ) -> Optional[float]:
        """
        Update short position and calculate new stop loss.

        For short positions:
        - Track lowest price reached
        - Increase acceleration factor when new low is reached
        - Calculate SL = lowest_price + (entry_price - lowest_price) * acceleration_factor
        """
        # Check if we have a new low
        if current_price < position.lowest_price:
            position.lowest_price = current_price
            # Increase acceleration factor
            position.acceleration_factor = min(
                position.acceleration_factor + self.af_increment, self.max_af
            )
            logger.debug(
                f"New low for {position.symbol}: {current_price:.4f}, "
                f"AF: {position.acceleration_factor:.4f}"
            )

        # Calculate trailing stop loss
        # SL moves down based on the profit and acceleration factor
        profit_distance = position.entry_price - position.lowest_price
        sl_distance = profit_distance * position.acceleration_factor
        new_sl_price = position.lowest_price + sl_distance

        logger.debug(
            f"Short SL calculation for {position.symbol}: "
            f"low={position.lowest_price:.4f}, entry={position.entry_price:.4f}, "
            f"profit_dist={profit_distance:.4f}, sl_dist={sl_distance:.4f}, "
            f"new_sl={new_sl_price:.4f}"
        )

        return new_sl_price

    def get_position(self, symbol: str) -> Optional[PositionTrailingStop]:
        """Get position tracking data."""
        return self.positions.get(symbol)

    def update_sl_order_id(self, symbol: str, order_id: str) -> None:
        """Update the stop loss order ID for a position."""
        if symbol in self.positions:
            self.positions[symbol].current_sl_order_id = order_id
            logger.debug(f"Updated SL order ID for {symbol}: {order_id}")
