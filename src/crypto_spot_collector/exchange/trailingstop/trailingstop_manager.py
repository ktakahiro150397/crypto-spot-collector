import math
from collections.abc import Collection

from loguru import logger

from crypto_spot_collector.exchange.trailingstop.trailingstop_position import (
    TrailingStopPositionHyperLiquid,
)
from crypto_spot_collector.exchange.types import PositionSide


def normalized_pnl_percentage(
    percentage: float | int | str,
    unrealized_pnl: float | int | str,
) -> float:
    """Return a signed PnL percentage using unrealized PnL as sign authority."""

    normalized_percentage = float(percentage)
    normalized_unrealized_pnl = float(unrealized_pnl)
    if not math.isfinite(normalized_percentage) or not math.isfinite(
        normalized_unrealized_pnl
    ):
        raise ValueError("PnL percentage and unrealized PnL must be finite")
    if normalized_unrealized_pnl < 0:
        return -abs(normalized_percentage)
    if normalized_unrealized_pnl > 0:
        return abs(normalized_percentage)
    return 0.0


def pnl_reaches_activation(
    percentage: float | int | str,
    unrealized_pnl: float | int | str,
    activation_threshold: float,
) -> bool:
    """Return whether a profitable position reaches the activation threshold."""

    if activation_threshold <= 0 or not math.isfinite(activation_threshold):
        raise ValueError("activation threshold must be finite and greater than zero")
    return normalized_pnl_percentage(percentage, unrealized_pnl) >= activation_threshold


class TrailingStopManagerHyperLiquid:

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
        *,
        contracts: float,
        stoploss_order_id: str,
        initial_stoploss_price: float,
        trailing_activated: bool = False,
    ) -> None:
        entry_price = float(entry_price)
        contracts = abs(float(contracts))
        initial_stoploss_price = float(initial_stoploss_price)

        values = (entry_price, contracts, initial_stoploss_price)
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError(
                "entry price, contracts and initial stop-loss price must be "
                "finite and positive"
            )

        existing_position = self.positions.get(symbol)
        if existing_position is not None and self._is_same_position(
            existing_position,
            side=side,
            entry_price=entry_price,
            contracts=contracts,
        ):
            logger.info(
                f"Updating Trailing Stop Position for {symbol} - "
                f"preserving trailing state: activated={existing_position.trailing_activated}, "
                f"af_factor={existing_position.current_af_factor}, "
                f"highest={existing_position.highest_price}, lowest={existing_position.lowest_price}"
            )
            existing_position.stoploss_order_id = stoploss_order_id
            existing_position.trailing_activated = (
                existing_position.trailing_activated or trailing_activated
            )
            if side == PositionSide.LONG:
                existing_position.current_stoploss_price = max(
                    existing_position.current_stoploss_price,
                    initial_stoploss_price,
                )
            else:
                existing_position.current_stoploss_price = min(
                    existing_position.current_stoploss_price,
                    initial_stoploss_price,
                )
        else:
            if existing_position is None:
                logger.info(f"Adding new Trailing Stop Position for {symbol}")
            else:
                logger.info(
                    f"Resetting Trailing Stop Position for {symbol}: "
                    "side, entry price, or contracts changed"
                )
            position = TrailingStopPositionHyperLiquid(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                contracts=contracts,
                stoploss_order_id=stoploss_order_id,
                highest_price=entry_price,
                lowest_price=entry_price,
                current_stoploss_price=initial_stoploss_price,
                current_af_factor=self.initial_af_factor,
                trailing_activated=trailing_activated,
            )

            self.positions[symbol] = position

    @staticmethod
    def _is_same_position(
        position: TrailingStopPositionHyperLiquid,
        *,
        side: PositionSide,
        entry_price: float,
        contracts: float,
    ) -> bool:
        return (
            position.side == side
            and math.isclose(position.entry_price, entry_price, rel_tol=1e-9)
            and math.isclose(position.contracts, contracts, rel_tol=1e-9)
        )

    def get_position(self, symbol: str) -> TrailingStopPositionHyperLiquid | None:
        return self.positions.get(symbol, None)

    def remove_position(self, symbol: str) -> None:
        if symbol in self.positions:
            del self.positions[symbol]
            logger.info(f"Removed Trailing Stop Position for {symbol}")
        else:
            logger.warning(f"Attempted to remove non-existent position for {symbol}")

    def clear_positions(self) -> None:
        self.positions.clear()
        logger.info("Cleared all Trailing Stop Positions")

    def remove_missing(self, active_symbols: Collection[str]) -> None:
        """Remove local state for positions absent from an exchange snapshot."""

        active = set(active_symbols)
        for symbol in set(self.positions) - active:
            self.remove_position(symbol)

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

        if not math.isfinite(current_price) or current_price <= 0:
            raise ValueError("current price must be finite and positive")

        if symbol not in self.positions:
            logger.warning(f"Position for {symbol} not found in Trailing Stop Manager.")
            return False

        position = self.positions[symbol]

        # トレーリングが有効化されていない場合はスキップ
        if not position.trailing_activated:
            logger.debug(
                f"Trailing not activated for {symbol}, skipping stoploss update"
            )
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
        if not math.isfinite(current_price) or current_price <= 0:
            raise ValueError("current price must be finite and positive")

        if symbol not in self.positions:
            logger.warning(f"Position for {symbol} not found in Trailing Stop Manager.")
            return False

        position = self.positions[symbol]

        if position.trailing_activated:
            logger.debug(f"Trailing already activated for {symbol}")
            return False

        # トレーリングを有効化
        position.trailing_activated = True

        # Move protection to at least breakeven without weakening a stop that
        # was already made more protective outside this process.
        if position.side == PositionSide.LONG:
            position.current_stoploss_price = max(
                position.current_stoploss_price,
                position.entry_price,
            )
        else:
            position.current_stoploss_price = min(
                position.current_stoploss_price,
                position.entry_price,
            )

        # 現在価格でhighest/lowest priceを更新
        if position.side == PositionSide.LONG:
            position.highest_price = max(position.highest_price, current_price)
        else:
            position.lowest_price = min(position.lowest_price, current_price)

        # AF係数をリセット
        position.current_af_factor = self.initial_af_factor

        logger.info(
            f"Activated trailing stop for {symbol}: "
            f"stoploss protected at {position.current_stoploss_price:.4f}, "
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
                f"New highest price for {position.symbol}: {position.highest_price}"
            )

            # Calculate and update the new stoploss price
            stoploss_price_movement = (
                position.highest_price - position.current_stoploss_price
            ) * position.current_af_factor
            new_stoploss_price = max(
                position.current_stoploss_price,
                min(
                    position.highest_price,
                    position.current_stoploss_price + stoploss_price_movement,
                ),
            )

            new_current_af_factor = min(
                position.current_af_factor + self.af_factor_increment_step,
                self.max_af_factor,
            )

            logger.info(
                f"Updated stoploss price for {position.symbol}: {position.current_stoploss_price} -> {new_stoploss_price}"
            )
            logger.info(
                f"Updated AF factor for {position.symbol}: {position.current_af_factor} -> {new_current_af_factor}"
            )
            position.current_stoploss_price = new_stoploss_price
            position.current_af_factor = new_current_af_factor

            return True
        else:
            logger.debug(
                f"No update to highest price for {position.symbol}: current price {current_price}, highest price {position.highest_price}"
            )
            return False

    def _update_short_position_stoploss_price(
        self,
        current_price: float,
        position: TrailingStopPositionHyperLiquid,
    ) -> bool:
        if current_price < position.lowest_price:
            position.lowest_price = current_price
            logger.info(
                f"New lowest price for {position.symbol}: {position.lowest_price}"
            )

            # Calculate and update the new stoploss price
            # For SHORT: SAR moves down as price moves down
            stoploss_price_movement = (
                position.current_stoploss_price - position.lowest_price
            ) * position.current_af_factor
            new_stoploss_price = min(
                position.current_stoploss_price,
                max(
                    position.lowest_price,
                    position.current_stoploss_price - stoploss_price_movement,
                ),
            )

            new_current_af_factor = min(
                position.current_af_factor + self.af_factor_increment_step,
                self.max_af_factor,
            )

            logger.info(
                f"Updated stoploss price for {position.symbol}: {position.current_stoploss_price} -> {new_stoploss_price}"
            )
            logger.info(
                f"Updated AF factor for {position.symbol}: {position.current_af_factor} -> {new_current_af_factor}"
            )
            position.current_stoploss_price = new_stoploss_price
            position.current_af_factor = new_current_af_factor

            return True
        else:
            logger.debug(
                f"No update to lowest price for {position.symbol}: current price {current_price}, lowest price {position.lowest_price}"
            )

            return False
