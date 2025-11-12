"""Order repository for managing cryptocurrency orders."""

from datetime import datetime
from typing import List, Optional, Type

from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..database import get_db_session
from ..models import Cryptocurrency, Order


class OrderRepository:
    """Repository for Order data operations."""

    def __init__(self, session: Optional[Session] = None) -> None:
        """Initialize repository with database session.

        Args:
            session: Database session. If None, creates a new session.
        """
        self.session = session or get_db_session()
        self._own_session = session is None

    def __enter__(self) -> "OrderRepository":
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

    def create_order(
        self,
        order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
        status: str,
        order_timestamp_utc: datetime
    ) -> Order:
        """Create a new order record.

        Args:
            order_id: Exchange order ID
            symbol: Trading pair symbol (e.g., BTC/USDT)
            side: Order side ('buy' or 'sell')
            order_type: Order type ('limit' or 'market')
            price: Order price
            quantity: Order quantity
            status: Order status ('open', 'closed', 'canceled')
            order_timestamp_utc: Order timestamp in UTC

        Returns:
            Created Order object
        """
        # Extract base symbol from trading pair (e.g., BTC from BTC/USDT)
        base_symbol = symbol.split("/")[0]

        # Get or create cryptocurrency
        crypto = self.session.query(Cryptocurrency).filter(
            Cryptocurrency.symbol == base_symbol
        ).first()

        if not crypto:
            crypto = Cryptocurrency(symbol=base_symbol, name=base_symbol)
            self.session.add(crypto)
            self.session.flush()

        # Create order
        order = Order(
            order_id=order_id,
            cryptocurrency_id=crypto.id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
            status=status,
            order_timestamp_utc=order_timestamp_utc
        )

        self.session.add(order)
        self.session.commit()

        return order

    def get_order_by_order_id(self, order_id: str) -> Optional[Order]:
        """Get an order by its exchange order ID.

        Args:
            order_id: Exchange order ID

        Returns:
            Order object if found, None otherwise
        """
        return self.session.query(Order).filter(
            Order.order_id == order_id
        ).first()

    def update_order_status(self, order_id: str, status: str) -> Optional[Order]:
        """Update order status.

        Args:
            order_id: Exchange order ID
            status: New status ('open', 'closed', 'canceled')

        Returns:
            Updated Order object if found, None otherwise
        """
        order = self.get_order_by_order_id(order_id)
        if order:
            order.status = status
            self.session.commit()
        return order

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get all open orders.

        Args:
            symbol: Optional symbol filter

        Returns:
            List of open Order objects
        """
        query = self.session.query(Order).filter(Order.status == "open")

        if symbol:
            query = query.filter(Order.symbol == symbol)

        return query.order_by(Order.order_timestamp_utc.desc()).all()

    def get_orders_by_symbol(
        self,
        symbol: str,
        limit: Optional[int] = None
    ) -> List[Order]:
        """Get orders for a specific symbol.

        Args:
            symbol: Trading pair symbol
            limit: Optional limit on number of results

        Returns:
            List of Order objects
        """
        query = self.session.query(Order).filter(Order.symbol == symbol)
        query = query.order_by(Order.order_timestamp_utc.desc())

        if limit:
            query = query.limit(limit)

        return query.all()

    def get_orders_between_dates(
        self,
        start_date: datetime,
        end_date: datetime,
        symbol: Optional[str] = None
    ) -> List[Order]:
        """Get orders between two dates.

        Args:
            start_date: Start date (UTC)
            end_date: End date (UTC)
            symbol: Optional symbol filter

        Returns:
            List of Order objects
        """
        query = self.session.query(Order).filter(
            and_(
                Order.order_timestamp_utc >= start_date,
                Order.order_timestamp_utc <= end_date
            )
        )

        if symbol:
            query = query.filter(Order.symbol == symbol)

        return query.order_by(Order.order_timestamp_utc.desc()).all()
