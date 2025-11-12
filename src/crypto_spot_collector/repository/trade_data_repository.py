"""Trade data repository for persisting and retrieving trade data."""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional, Type

from loguru import logger
from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..database import get_db_session
from ..models import Cryptocurrency, TradeData


class TradeDataRepository:
    """Repository for trade data operations."""

    def __init__(self, session: Optional[Session] = None) -> None:
        """Initialize repository with database session.

        Args:
            session: Database session. If None, creates a new session.
        """
        self.session = session or get_db_session()
        self._own_session = session is None

    def __enter__(self) -> "TradeDataRepository":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[object]
    ) -> None:
        """Context manager exit."""
        if self._own_session and self.session:
            self.session.close()

    def create_or_update_trade_data(
        self,
        cryptocurrency_name: str,
        exchange_name: str,
        trade_id: str,
        status: Literal["OPEN", "CANCELED", "CLOSED"],
        position_type: Literal["LONG", "SHORT"],
        is_spot: bool,
        leverage_ratio: float,
        price: float,
        quantity: float,
        fee: float,
        timestamp_utc: datetime
    ) -> None:
        """Create or update trade data record.

        Args:
            cryptocurrency_name: Name of the cryptocurrency (e.g., 'BTC').
            exchange_name: Name of the exchange (e.g., 'Binance').
            trade_id: Unique trade identifier from the exchange.
            status: Trade status ('OPEN', 'CANCELED', 'CLOSED').
            position_type: 'LONG' or 'SHORT'.
            is_spot: True if spot trade, False if margin/futures.
            leverage_ratio: Leverage ratio (1.00 for spot trades).
            price: Price at which the trade was executed.
            quantity: Quantity traded.
            fee: Transaction fee (if any / as USDT).
            timestamp_utc: Trade execution time (UTC).
        """
        # Fetch or create Cryptocurrency
        crypto = (
            self.session.query(Cryptocurrency)
            .filter(Cryptocurrency.symbol == cryptocurrency_name)
            .one_or_none()
        )
        if not crypto:
            crypto = Cryptocurrency(
                name=cryptocurrency_name, symbol=cryptocurrency_name)
            self.session.add(crypto)
            self.session.commit()

        # Check for existing trade data
        trade_data = (
            self.session.query(TradeData)
            .filter(
                and_(
                    TradeData.cryptocurrency_id == crypto.id,
                    TradeData.exchange_name == exchange_name,
                    TradeData.trade_id == trade_id,
                )
            )
            .one_or_none()
        )

        # よしなに変換
        if position_type.upper() == "BUY":
            position_type = "LONG"
        elif position_type.upper() == "SELL":
            position_type = "SHORT"

        if status is None:
            status = 'OPEN'
        else:
            status = status.upper()

        if trade_data:
            # Update existing record
            trade_data.status = status
            trade_data.position_type = position_type
            trade_data.is_spot = is_spot
            trade_data.leverage_ratio = leverage_ratio
            trade_data.price = price
            trade_data.quantity = quantity
            trade_data.fee = fee
            trade_data.timestamp_utc = timestamp_utc
        else:
            # Create new record
            trade_data = TradeData(
                cryptocurrency_id=crypto.id,
                exchange_name=exchange_name,
                trade_id=trade_id,
                status=status,
                position_type=position_type,
                is_spot=is_spot,
                leverage_ratio=leverage_ratio,
                price=price,
                quantity=quantity,
                fee=fee,
                timestamp_utc=timestamp_utc,
            )
            self.session.add(trade_data)

        self.session.commit()

    def update_trade_status_by_trade_id(
        self,
        trade_id: str,
        new_status: Literal["OPEN", "CANCELED", "CLOSED"]
    ) -> None:
        """Update the status of a trade data record by trade ID.

        Args:
            trade_id: Unique trade identifier from the exchange.
            new_status: New status to set ('OPEN', 'CANCELED', 'CLOSED').
        """
        trade_data = (
            self.session.query(TradeData)
            .filter(TradeData.trade_id == trade_id)
            .one_or_none()
        )

        if not trade_data:
            raise ValueError(
                f"Trade data with trade_id '{trade_id}' not found")

        trade_data.status = new_status
        self.session.commit()

    def get_current_position_and_avg_price(
        self,
        symbol: str
    ) -> tuple[float, float]:
        """Get current holdings and average acquisition price for a given cryptocurrency symbol.

        Args:
            symbol: Symbol of the cryptocurrency (e.g., 'BTC').
        Returns:
            Tuple of (current_quantity, average_price).
            Returns (0.0, 0.0) if no holdings or no records found.
        """
        crypto = (
            self.session.query(Cryptocurrency)
            .filter(Cryptocurrency.symbol == symbol)
            .one_or_none()
        )
        if not crypto:
            return 0.0, 0.0

        # Get all trades for this cryptocurrency ordered by timestamp
        trades = (
            self.session.query(TradeData)
            .filter(
                and_(
                    TradeData.cryptocurrency_id == crypto.id,
                    TradeData.status == "CLOSED",
                )
            )
            .order_by(TradeData.timestamp_utc)
            .all()
        )

        if not trades:
            return 0.0, 0.0

        total_quantity = Decimal('0.0')  # Current holdings
        total_cost = Decimal('0.0')      # Total cost basis

        for trade in trades:
            if trade.position_type == "LONG":  # Purchase
                # Add to holdings and update total cost
                # Use Decimal for precise calculations
                purchase_cost = trade.price * trade.quantity
                total_cost += purchase_cost
                total_quantity += trade.quantity - \
                    (trade.fee / trade.price)  # Adjust quantity for fee

            elif trade.position_type == "SHORT":  # Sale
                # Reduce holdings (average price remains the same)
                sell_quantity = min(trade.quantity, total_quantity)
                if total_quantity > 0:
                    # Calculate current average price
                    current_avg_price = total_cost / total_quantity
                    # Reduce cost basis proportionally
                    total_cost -= current_avg_price * \
                        sell_quantity - (trade.fee)

                total_quantity -= sell_quantity
                # Prevent negative holdings
                total_quantity = max(Decimal('0.0'), total_quantity)

        # Calculate final average price
        if total_quantity > 0:
            average_price = total_cost / total_quantity

            logger.debug(
                f"Computed for {symbol}: Total Quantity = {total_quantity}, Total Cost = {total_cost}, Average Price = {average_price}"
            )
            return float(total_quantity), float(average_price)
        else:
            return 0.0, 0.0

    def get_average_buy_price_by_symbol(
        self,
        symbol: str
    ) -> float:
        """Get average acquisition price for a given cryptocurrency symbol.

        This method is deprecated. Use get_current_position_and_avg_price() instead.

        Args:
            symbol: Symbol of the cryptocurrency (e.g., 'BTC').
        Returns:
            Average acquisition price or 0.0 if no holdings.
        """
        _, avg_price = self.get_current_position_and_avg_price(symbol)
        return avg_price
