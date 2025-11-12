"""Tests for OrderRepository."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from crypto_spot_collector.database import Base
from crypto_spot_collector.models import Cryptocurrency, Order
from crypto_spot_collector.repository.order_repository import OrderRepository


@pytest.fixture
def test_db_session():
    """Create a test database session."""
    # Use in-memory SQLite for testing
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def order_repository(test_db_session):
    """Create an OrderRepository instance with test session."""
    return OrderRepository(session=test_db_session)


def test_create_order(order_repository, test_db_session):
    """Test creating a new order."""
    # Create order
    order = order_repository.create_order(
        order_id="test_order_123",
        symbol="BTC/USDT",
        side="buy",
        order_type="limit",
        price=50000.0,
        quantity=0.001,
        status="open",
        order_timestamp_utc=datetime.now(timezone.utc)
    )

    # Verify order was created
    assert order.order_id == "test_order_123"
    assert order.symbol == "BTC/USDT"
    assert order.side == "buy"
    assert order.order_type == "limit"
    assert float(order.price) == 50000.0
    assert float(order.quantity) == 0.001
    assert order.status == "open"

    # Verify cryptocurrency was created
    crypto = test_db_session.query(Cryptocurrency).filter(
        Cryptocurrency.symbol == "BTC"
    ).first()
    assert crypto is not None
    assert order.cryptocurrency_id == crypto.id


def test_get_order_by_order_id(order_repository):
    """Test retrieving an order by order ID."""
    # Create order
    created_order = order_repository.create_order(
        order_id="test_order_456",
        symbol="ETH/USDT",
        side="sell",
        order_type="market",
        price=3000.0,
        quantity=0.5,
        status="closed",
        order_timestamp_utc=datetime.now(timezone.utc)
    )

    # Retrieve order
    retrieved_order = order_repository.get_order_by_order_id("test_order_456")

    # Verify
    assert retrieved_order is not None
    assert retrieved_order.order_id == created_order.order_id
    assert retrieved_order.symbol == "ETH/USDT"
    assert retrieved_order.status == "closed"


def test_get_order_by_order_id_not_found(order_repository):
    """Test retrieving a non-existent order."""
    order = order_repository.get_order_by_order_id("nonexistent")
    assert order is None


def test_update_order_status(order_repository):
    """Test updating order status."""
    # Create order
    order_repository.create_order(
        order_id="test_order_789",
        symbol="XRP/USDT",
        side="buy",
        order_type="limit",
        price=0.5,
        quantity=1000.0,
        status="open",
        order_timestamp_utc=datetime.now(timezone.utc)
    )

    # Update status
    updated_order = order_repository.update_order_status(
        "test_order_789",
        "closed"
    )

    # Verify
    assert updated_order is not None
    assert updated_order.status == "closed"

    # Verify in database
    db_order = order_repository.get_order_by_order_id("test_order_789")
    assert db_order.status == "closed"


def test_get_open_orders(order_repository):
    """Test retrieving all open orders."""
    # Create multiple orders
    order_repository.create_order(
        order_id="open_1",
        symbol="BTC/USDT",
        side="buy",
        order_type="limit",
        price=50000.0,
        quantity=0.001,
        status="open",
        order_timestamp_utc=datetime.now(timezone.utc)
    )

    order_repository.create_order(
        order_id="closed_1",
        symbol="ETH/USDT",
        side="buy",
        order_type="limit",
        price=3000.0,
        quantity=0.5,
        status="closed",
        order_timestamp_utc=datetime.now(timezone.utc)
    )

    order_repository.create_order(
        order_id="open_2",
        symbol="SOL/USDT",
        side="buy",
        order_type="limit",
        price=100.0,
        quantity=10.0,
        status="open",
        order_timestamp_utc=datetime.now(timezone.utc)
    )

    # Get open orders
    open_orders = order_repository.get_open_orders()

    # Verify
    assert len(open_orders) == 2
    order_ids = [order.order_id for order in open_orders]
    assert "open_1" in order_ids
    assert "open_2" in order_ids
    assert "closed_1" not in order_ids


def test_get_open_orders_filtered_by_symbol(order_repository):
    """Test retrieving open orders filtered by symbol."""
    # Create orders
    order_repository.create_order(
        order_id="btc_open",
        symbol="BTC/USDT",
        side="buy",
        order_type="limit",
        price=50000.0,
        quantity=0.001,
        status="open",
        order_timestamp_utc=datetime.now(timezone.utc)
    )

    order_repository.create_order(
        order_id="eth_open",
        symbol="ETH/USDT",
        side="buy",
        order_type="limit",
        price=3000.0,
        quantity=0.5,
        status="open",
        order_timestamp_utc=datetime.now(timezone.utc)
    )

    # Get open orders for BTC/USDT
    btc_orders = order_repository.get_open_orders(symbol="BTC/USDT")

    # Verify
    assert len(btc_orders) == 1
    assert btc_orders[0].order_id == "btc_open"
    assert btc_orders[0].symbol == "BTC/USDT"


def test_get_orders_by_symbol(order_repository):
    """Test retrieving orders by symbol."""
    # Create orders
    for i in range(5):
        order_repository.create_order(
            order_id=f"btc_order_{i}",
            symbol="BTC/USDT",
            side="buy",
            order_type="limit",
            price=50000.0 + i * 100,
            quantity=0.001,
            status="open" if i < 3 else "closed",
            order_timestamp_utc=datetime.now(timezone.utc)
        )

    order_repository.create_order(
        order_id="eth_order",
        symbol="ETH/USDT",
        side="buy",
        order_type="limit",
        price=3000.0,
        quantity=0.5,
        status="open",
        order_timestamp_utc=datetime.now(timezone.utc)
    )

    # Get all BTC orders
    btc_orders = order_repository.get_orders_by_symbol("BTC/USDT")

    # Verify
    assert len(btc_orders) == 5
    for order in btc_orders:
        assert order.symbol == "BTC/USDT"


def test_get_orders_by_symbol_with_limit(order_repository):
    """Test retrieving orders by symbol with limit."""
    # Create multiple orders
    for i in range(10):
        order_repository.create_order(
            order_id=f"order_{i}",
            symbol="BTC/USDT",
            side="buy",
            order_type="limit",
            price=50000.0,
            quantity=0.001,
            status="open",
            order_timestamp_utc=datetime.now(timezone.utc)
        )

    # Get orders with limit
    orders = order_repository.get_orders_by_symbol("BTC/USDT", limit=3)

    # Verify
    assert len(orders) == 3


def test_get_orders_between_dates(order_repository):
    """Test retrieving orders between dates."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    tomorrow = now + timedelta(days=1)

    # Create orders with different timestamps
    order_repository.create_order(
        order_id="old_order",
        symbol="BTC/USDT",
        side="buy",
        order_type="limit",
        price=50000.0,
        quantity=0.001,
        status="open",
        order_timestamp_utc=yesterday - timedelta(days=1)
    )

    order_repository.create_order(
        order_id="recent_order",
        symbol="BTC/USDT",
        side="buy",
        order_type="limit",
        price=50000.0,
        quantity=0.001,
        status="open",
        order_timestamp_utc=now
    )

    # Get orders between yesterday and tomorrow
    orders = order_repository.get_orders_between_dates(yesterday, tomorrow)

    # Verify
    assert len(orders) == 1
    assert orders[0].order_id == "recent_order"
