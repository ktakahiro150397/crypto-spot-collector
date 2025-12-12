from typing import TypedDict, Unpack

from loguru import logger

from crypto_spot_collector.exchange.trailingstop.trailingstop_position import (
    TrailingStopPositionHyperLiquid,
)
from crypto_spot_collector.exchange.types import PositionSide


class TrailingStopManagerOptionHyperliquid(TypedDict):
    stoploss_order_id: str
    initial_stoploss_price: float
    trailing_activated: bool


class TrailingStopManagerHyperLiquid():

    def __init__(self) -> None:
        super().__init__()
        self.positions: dict[str, TrailingStopPositionHyperLiquid] = {}

        self.initial_af_factor: float = 0.02
        self.af_factor_increment_step: float = 0.02
        self.max_af_factor: float = 0.2

        logger.info(
            f"Initialized TrailingStopManagerHyperLiquid with AF factor {self.initial_af_factor}, "
            f"increment step {self.af_factor_increment_step}, "
            f"max AF factor {self.max_af_factor}"
        )

    def add_or_update_position(
        self,
        symbol: str,
        side: PositionSide,
        entry_price: float,
        **kwargs: Unpack[TrailingStopManagerOptionHyperliquid]
    ) -> None:
        stoploss_order_id: str = kwargs.get("stoploss_order_id", "")
        initial_stoploss_price: float = kwargs.get(
            "initial_stoploss_price", 0.0)
        trailing_activated: bool = kwargs.get("trailing_activated", False)

        if symbol in self.positions:
            logger.info(f"Overwriting Trailing Stop Position for {symbol}")
            position = self.positions[symbol]
            position.stoploss_order_id = stoploss_order_id
            position.trailing_activated = trailing_activated
        else:
            logger.info(f"Adding Trailing Stop Position for {symbol}")
            position = TrailingStopPositionHyperLiquid(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                stoploss_order_id=stoploss_order_id,
                highest_price=entry_price,
                lowest_price=entry_price,
                current_stoploss_price=initial_stoploss_price,
                current_af_factor=self.initial_af_factor,
                trailing_activated=trailing_activated,
            )

            self.positions[symbol] = position

    def get_position(self, symbol: str) -> TrailingStopPositionHyperLiquid | None:
        return self.positions.get(symbol, None)

    def remove_position(self, symbol: str) -> None:
        if symbol in self.positions:
            del self.positions[symbol]
            logger.info(f"Removed Trailing Stop Position for {symbol}")
        else:
            logger.warning(
                f"Attempted to remove non-existent position for {symbol}")

    def clear_positions(self) -> None:
        self.positions.clear()
        logger.info("Cleared all Trailing Stop Positions")

    def update_stoploss_price(
        self,
        symbol: str,
        current_price: float,
    ) -> bool:
        """
        Update the stoploss price for the given position based on the current price.
        トレーリングが有効化されていない場合は更新しない。

        :rtype: bool Indicates whether the stoploss price was updated.
        """

        if symbol not in self.positions:
            logger.warning(
                f"Position for {symbol} not found in Trailing Stop Manager.")
            return False

        position = self.positions[symbol]

        # トレーリングが有効化されていない場合はスキップ
        if not position.trailing_activated:
            logger.debug(
                f"Trailing not activated for {symbol}, skipping stoploss update")
            return False

        if position.side == PositionSide.LONG:
            return self._update_long_position_stoploss_price(
                current_price=current_price,
                position=position,
            )
        elif position.side == PositionSide.SHORT:
            return self._update_short_position_stoploss_price(
                current_price=current_price,
                position=position,
            )
        return False

    def activate_trailing(
        self,
        symbol: str,
        current_price: float,
    ) -> bool:
        """
        トレーリングストップを有効化し、ストップロスをエントリー価格に設定する。

        Args:
            symbol: シンボル
            current_price: 現在価格（highest/lowest price更新用）

        Returns:
            bool: 有効化に成功した場合True
        """
        if symbol not in self.positions:
            logger.warning(
                f"Position for {symbol} not found in Trailing Stop Manager.")
            return False

        position = self.positions[symbol]

        if position.trailing_activated:
            logger.debug(f"Trailing already activated for {symbol}")
            return False

        # トレーリングを有効化
        position.trailing_activated = True

        # ストップロスをエントリー価格に設定
        position.current_stoploss_price = position.entry_price

        # 現在価格でhighest/lowest priceを更新
        if position.side == PositionSide.LONG:
            position.highest_price = max(position.highest_price, current_price)
        else:
            position.lowest_price = min(position.lowest_price, current_price)

        # AF係数をリセット
        position.current_af_factor = self.initial_af_factor

        logger.info(
            f"Activated trailing stop for {symbol}: "
            f"stoploss set to entry price {position.entry_price:.4f}, "
            f"AF factor reset to {self.initial_af_factor}"
        )

        return True

    def _update_long_position_stoploss_price(
        self,
        current_price: float,
        position: TrailingStopPositionHyperLiquid,
    ) -> bool:
        if current_price > position.highest_price:
            position.highest_price = current_price
            logger.info(
                f"New highest price for {position.symbol}: {position.highest_price}")

            # Calculate and update the new stoploss price
            stoploss_price_movement = (
                position.highest_price - position.current_stoploss_price) * position.current_af_factor
            new_stoploss_price = position.current_stoploss_price + stoploss_price_movement

            new_current_af_factor = min(
                position.current_af_factor + self.af_factor_increment_step,
                self.max_af_factor,
            )

            logger.info(
                f"Updated stoploss price for {position.symbol}: {position.current_stoploss_price} -> {new_stoploss_price}")
            logger.info(
                f"Updated AF factor for {position.symbol}: {position.current_af_factor} -> {new_current_af_factor}")
            position.current_stoploss_price = new_stoploss_price
            position.current_af_factor = new_current_af_factor

            return True
        else:
            logger.debug(
                f"No update to highest price for {position.symbol}: current price {current_price}, highest price {position.highest_price}")
            return False

    def _update_short_position_stoploss_price(
        self,
        current_price: float,
        position: TrailingStopPositionHyperLiquid,
    ) -> bool:
        if current_price < position.lowest_price:
            position.lowest_price = current_price
            logger.info(
                f"New lowest price for {position.symbol}: {position.lowest_price}")

            # Calculate and update the new stoploss price
            # For SHORT: SAR moves down as price moves down
            stoploss_price_movement = (
                position.current_stoploss_price - position.lowest_price) * position.current_af_factor
            new_stoploss_price = position.current_stoploss_price - stoploss_price_movement

            new_current_af_factor = min(
                position.current_af_factor + self.af_factor_increment_step,
                self.max_af_factor,
            )

            logger.info(
                f"Updated stoploss price for {position.symbol}: {position.current_stoploss_price} -> {new_stoploss_price}")
            logger.info(
                f"Updated AF factor for {position.symbol}: {position.current_af_factor} -> {new_current_af_factor}")
            position.current_stoploss_price = new_stoploss_price
            position.current_af_factor = new_current_af_factor

            return True
        else:
            logger.debug(
                f"No update to lowest price for {position.symbol}: current price {current_price}, lowest price {position.lowest_price}")

            return False
