"""Database models for crypto spot collector."""

from sqlalchemy import (
    DECIMAL,
    TIMESTAMP,
    Boolean,
    Column,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class Cryptocurrency(Base):
    """Cryptocurrency model."""

    __tablename__ = "cryptocurrencies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(
        String(10), unique=True, nullable=False, comment="通貨シンボル (BTC, ETH等)"
    )
    name = Column(String(100), nullable=False, comment="通貨名")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # Relationships
    ohlcv_data = relationship("OHLCVData", back_populates="cryptocurrency")
    trade_data = relationship("TradeData", back_populates="cryptocurrency")
    orders = relationship("Order", back_populates="cryptocurrency")

    def __repr__(self) -> str:
        return f"<Cryptocurrency(symbol='{self.symbol}', name='{self.name}')>"


class OHLCVData(Base):
    """OHLCV data model for each cryptocurrency."""

    __tablename__ = "ohlcv_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cryptocurrency_id = Column(
        Integer, ForeignKey("cryptocurrencies.id"), nullable=False
    )
    open_price: Column[DECIMAL] = Column(
        DECIMAL(20, 8), nullable=False, comment="オープン価格"
    )
    high_price: Column[DECIMAL] = Column(DECIMAL(20, 8), nullable=False, comment="高値")
    low_price: Column[DECIMAL] = Column(DECIMAL(20, 8), nullable=False, comment="安値")
    close_price: Column[DECIMAL] = Column(
        DECIMAL(20, 8), nullable=False, comment="クローズ価格"
    )
    volume: Column[DECIMAL] = Column(DECIMAL(20, 8), nullable=False, comment="取引量")
    timestamp_utc = Column(TIMESTAMP, nullable=False, comment="データ時刻（UTC）")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    cryptocurrency = relationship("Cryptocurrency", back_populates="ohlcv_data")

    # Indexes and constraints
    __table_args__ = (
        Index("idx_crypto_timestamp", "cryptocurrency_id", "timestamp_utc"),
        Index("idx_timestamp_utc", "timestamp_utc"),
        # Unique constraint to prevent duplicate data
        Index(
            "unique_crypto_timestamp", "cryptocurrency_id", "timestamp_utc", unique=True
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<OHLCVData(cryptocurrency_id={self.cryptocurrency_id}, "
            f"close_price={self.close_price}, timestamp_utc={self.timestamp_utc})>"
        )


class TradeData(Base):
    """Trade data model with exchange, position type, spot/derivatives."""

    __tablename__ = "trade_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cryptocurrency_id = Column(
        Integer, ForeignKey("cryptocurrencies.id"), nullable=False
    )
    exchange_name = Column(String(50), nullable=False, comment="取引所名")
    position_type: Column[Enum] = Column(
        Enum("LONG", "SHORT", name="position_type_enum"),
        nullable=False,
        comment="ロング/ショート",
    )
    is_spot = Column(
        Boolean,
        nullable=False,
        comment="現物かどうか（TRUE: 現物, FALSE: 先物/デリバティブ）",
    )
    leverage_ratio: Column[DECIMAL] = Column(
        DECIMAL(5, 2), default=1.00, comment="レバレッジ倍率（現物の場合は1.00）"
    )
    price: Column[DECIMAL] = Column(DECIMAL(20, 8), nullable=False, comment="取引価格")
    quantity: Column[DECIMAL] = Column(
        DECIMAL(20, 8), nullable=False, comment="取引数量"
    )
    timestamp_utc = Column(TIMESTAMP, nullable=False, comment="取引時刻（UTC）")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    cryptocurrency = relationship("Cryptocurrency", back_populates="trade_data")

    # Indexes
    __table_args__ = (
        Index(
            "idx_crypto_exchange_time",
            "cryptocurrency_id",
            "exchange_name",
            "timestamp_utc",
        ),
        Index("idx_timestamp_utc", "timestamp_utc"),
        Index("idx_exchange_name", "exchange_name"),
        Index("idx_position_type", "position_type"),
        Index("idx_is_spot", "is_spot"),
    )

    def __repr__(self) -> str:
        return (
            f"<TradeData(cryptocurrency_id={self.cryptocurrency_id}, "
            f"exchange='{self.exchange_name}', position='{self.position_type}', "
            f"price={self.price}, timestamp_utc={self.timestamp_utc})>"
        )


class Order(Base):
    """Order model for tracking buy/sell orders."""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), unique=True, nullable=False, comment="取引所の注文ID")
    cryptocurrency_id = Column(
        Integer, ForeignKey("cryptocurrencies.id"), nullable=False
    )
    symbol = Column(String(20), nullable=False, comment="通貨ペア (BTC/USDT等)")
    side: Column[Enum] = Column(
        Enum("buy", "sell", name="order_side_enum"),
        nullable=False,
        comment="売買方向 (buy/sell)",
    )
    order_type: Column[Enum] = Column(
        Enum("limit", "market", name="order_type_enum"),
        nullable=False,
        comment="注文種類 (limit: 指値, market: 成り行き)",
    )
    price: Column[DECIMAL] = Column(
        DECIMAL(20, 8), nullable=False, comment="注文価格"
    )
    quantity: Column[DECIMAL] = Column(
        DECIMAL(20, 8), nullable=False, comment="注文数量"
    )
    status: Column[Enum] = Column(
        Enum("open", "closed", "canceled", name="order_status_enum"),
        nullable=False,
        default="open",
        comment="注文ステータス (open: 注文中, closed: 約定済み, canceled: キャンセル済み)",
    )
    order_timestamp_utc = Column(
        TIMESTAMP, nullable=False, comment="注文日時（UTC）"
    )
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # Relationships
    cryptocurrency = relationship("Cryptocurrency", back_populates="orders")

    # Indexes
    __table_args__ = (
        Index("idx_order_id", "order_id"),
        Index("idx_crypto_status", "cryptocurrency_id", "status"),
        Index("idx_symbol_status", "symbol", "status"),
        Index("idx_order_timestamp", "order_timestamp_utc"),
    )

    def __repr__(self) -> str:
        return (
            f"<Order(order_id='{self.order_id}', symbol='{self.symbol}', "
            f"side='{self.side}', type='{self.order_type}', "
            f"status='{self.status}', price={self.price})>"
        )
