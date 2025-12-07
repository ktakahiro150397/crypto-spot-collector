"""Periodic processor for managing trailing stops with acceleration coefficient."""

import asyncio

from loguru import logger

from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.exchange.trailing_stop_manager import (
    PositionTrailingStop,
    TrailingStopManager,
)


class TrailingStopProcessor:
    """
    Periodically checks positions and updates trailing stop losses.
    """

    def __init__(
        self,
        exchange: HyperLiquidExchange,
        trailing_stop_manager: TrailingStopManager,
        check_interval_seconds: int = 60,
        sl_update_threshold_percent: float = 0.1,
    ):
        """
        Initialize the trailing stop processor.

        Args:
            exchange: HyperLiquid exchange instance
            trailing_stop_manager: Trailing stop manager instance
            check_interval_seconds: How often to check positions (default 60s)
            sl_update_threshold_percent: Minimum % change to update SL (default 0.1%)
        """
        self.exchange = exchange
        self.tsm = trailing_stop_manager
        self.check_interval = check_interval_seconds
        self.sl_update_threshold_percent = sl_update_threshold_percent
        self.is_running = False

        logger.info(
            f"TrailingStopProcessor initialized: "
            f"check_interval={check_interval_seconds}s, "
            f"update_threshold={sl_update_threshold_percent}%"
        )

    async def start(self) -> None:
        """Start the periodic processing loop."""
        if self.is_running:
            logger.warning("TrailingStopProcessor is already running")
            return

        self.is_running = True
        logger.info("Starting TrailingStopProcessor")

        try:
            while self.is_running:
                await self._process_positions()
                await asyncio.sleep(self.check_interval)
        except Exception as e:
            logger.error(f"Error in TrailingStopProcessor main loop: {e}")
            raise
        finally:
            self.is_running = False
            logger.info("TrailingStopProcessor stopped")

    async def stop(self) -> None:
        """Stop the periodic processing loop."""
        logger.info("Stopping TrailingStopProcessor")
        self.is_running = False

    async def _process_positions(self) -> None:
        """Process all tracked positions and update stop losses if needed."""
        try:
            # Fetch current positions from exchange
            positions = await self.exchange.fetch_positions_async()

            if not positions:
                logger.debug("No open positions found")
                return

            logger.info(f"Processing {len(positions)} open positions")

            for position in positions:
                await self._process_single_position(position)

        except Exception as e:
            logger.error(f"Error processing positions: {e}")

    async def _process_single_position(self, position: dict) -> None:
        """
        Process a single position and update its trailing stop if needed.

        Args:
            position: Position data from exchange
        """
        try:
            symbol = position.get("symbol")
            side = position.get("side")  # 'long' or 'short'
            contracts = float(position.get("contracts", 0))
            entry_price = float(position.get("entryPrice", 0))

            if not symbol or not side or contracts == 0:
                logger.debug(f"Skipping invalid position: {position}")
                return

            # Add position to tracking if not already tracked
            if symbol not in self.tsm.positions:
                logger.info(f"Adding new position to tracking: {symbol} {side}")
                self.tsm.add_position(
                    symbol=symbol,
                    side=side,
                    entry_price=entry_price,
                )

            # Get current market price
            ticker = await self.exchange.fetch_price_async(symbol)
            current_price = float(ticker["last"])

            # Calculate new stop loss price
            new_sl_price = self.tsm.update_and_calculate_sl(symbol, current_price)

            if new_sl_price is None:
                logger.debug(f"No SL update needed for {symbol}")
                return

            # Check if update is significant enough
            tracked_position = self.tsm.get_position(symbol)
            if tracked_position and await self._should_update_sl(
                tracked_position, new_sl_price, current_price
            ):
                await self._update_stop_loss(tracked_position, new_sl_price, contracts)

        except Exception as e:
            logger.error(f"Error processing position {position.get('symbol')}: {e}")

    async def _should_update_sl(
        self,
        position: PositionTrailingStop,
        new_sl_price: float,
        current_price: float,
    ) -> bool:
        """
        Check if the stop loss should be updated.

        Returns True if:
        - No current SL order exists
        - New SL is significantly different (based on threshold)
        """
        # Always update if no SL order exists
        if not position.current_sl_order_id:
            logger.info(f"No existing SL order for {position.symbol}, will create new")
            return True

        # Fetch current open orders to check existing SL trigger price
        try:
            orders = await self.exchange.fetch_open_orders_all_async(position.symbol)

            # Find the current SL order
            sl_order = None
            for order in orders:
                if order.get("id") == position.current_sl_order_id:
                    sl_order = order
                    break

            if not sl_order:
                logger.warning(
                    f"Current SL order {position.current_sl_order_id} not found, "
                    f"will create new"
                )
                return True

            # Check trigger price
            current_sl_trigger = float(sl_order.get("triggerPrice", 0))
            if current_sl_trigger == 0:
                logger.warning("Invalid trigger price in SL order, will update")
                return True

            # Calculate percentage difference
            sl_change_percent = (
                abs(new_sl_price - current_sl_trigger) / current_price * 100
            )

            if sl_change_percent >= self.sl_update_threshold_percent:
                logger.info(
                    f"SL update needed for {position.symbol}: "
                    f"current={current_sl_trigger:.4f}, new={new_sl_price:.4f}, "
                    f"change={sl_change_percent:.2f}%"
                )
                return True

            logger.debug(
                f"SL change too small for {position.symbol}: {sl_change_percent:.2f}%"
            )
            return False

        except Exception as e:
            logger.error(f"Error checking SL update necessity: {e}")
            # Default to updating if we can't check
            return True

    async def _update_stop_loss(
        self,
        position: PositionTrailingStop,
        new_sl_price: float,
        amount: float,
    ) -> None:
        """
        Update or create a stop loss order for a position.

        Args:
            position: Position tracking data
            new_sl_price: New stop loss trigger price
            amount: Position size
        """
        try:
            # Determine order side (opposite of position side)
            if position.side == "long":
                order_side = "sell"
            else:
                order_side = "buy"

            # Cancel existing order and create new one
            # Note: Using cancel-and-recreate approach as it's more reliable
            # than trying to modify trigger orders, which may not be supported
            # TODO: Once HyperLiquid API support for modifying trigger orders
            # is confirmed, can optimize to use modify instead of cancel+create
            if position.current_sl_order_id:
                try:
                    logger.info(
                        f"Canceling existing SL order {position.current_sl_order_id} "
                        f"for {position.symbol}"
                    )
                    await self.exchange.cancel_order_async(
                        order_id=position.current_sl_order_id,
                        symbol=position.symbol,
                    )
                except Exception as cancel_error:
                    logger.warning(
                        f"Failed to cancel old SL order (may already be filled): "
                        f"{cancel_error}"
                    )

            # Create new stop loss order
            logger.info(
                f"Creating new SL order for {position.symbol} at {new_sl_price:.4f}"
            )
            result = await self.exchange.create_stop_loss_order_async(
                symbol=position.symbol,
                side=order_side,
                amount=amount,
                trigger_price=new_sl_price,
            )

            # Update tracking with new order ID
            new_order_id = result.get("id")
            if new_order_id:
                self.tsm.update_sl_order_id(position.symbol, new_order_id)
                logger.info(
                    f"Updated SL order ID for {position.symbol}: {new_order_id}"
                )

        except Exception as e:
            logger.error(f"Failed to update stop loss for {position.symbol}: {e}")
