"""Trade data repository for persisting and retrieving trade data."""


from datetime import datetime
from typing import List, Literal, Optional, Type

from sqlalchemy import Column, and_, func, text
from sqlalchemy.orm import Session, joinedload

from ..database import get_db_session
from ..models import Cryptocurrency, OHLCVData, TradeData


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
        status: Literal["OPEN", "CANCELLED", "CLOSED"],
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
            status: Trade status ('OPEN', 'CANCELLED', 'CLOSED').
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
        new_status: Literal["OPEN", "CANCELLED", "CLOSED"]
    ) -> None:
        """Update the status of a trade data record by trade ID.

        Args:
            trade_id: Unique trade identifier from the exchange.
            new_status: New status to set ('OPEN', 'CANCELLED', 'CLOSED').
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
