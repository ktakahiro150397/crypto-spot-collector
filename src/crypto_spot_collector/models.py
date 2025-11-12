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
    high_price: Column[DECIMAL] = Column(
        DECIMAL(20, 8), nullable=False, comment="高値")
    low_price: Column[DECIMAL] = Column(
        DECIMAL(20, 8), nullable=False, comment="安値")
    close_price: Column[DECIMAL] = Column(
        DECIMAL(20, 8), nullable=False, comment="クローズ価格"
    )
    volume: Column[DECIMAL] = Column(
        DECIMAL(20, 8), nullable=False, comment="取引量")
    timestamp_utc = Column(TIMESTAMP, nullable=False, comment="データ時刻（UTC）")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    cryptocurrency = relationship(
        "Cryptocurrency", back_populates="ohlcv_data")

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
    exchange_name = Column(String(50), nullable=False, comment="Exchange name")
    trade_id = Column(String(100), nullable=False,
                      comment="Unique trade identifier from the exchange")
    status: Column[Enum] = Column(
        Enum("OPEN", "CANCELLED", "CLOSED", name="status_enum"),
        nullable=False,
        comment="Trade status",
    )
    position_type: Column[Enum] = Column(
        Enum("LONG", "SHORT", name="position_type_enum"),
        nullable=False,
        comment="Long or Short",
    )
    is_spot = Column(
        Boolean,
        nullable=False,
        comment="Is spot trade (TRUE) or margin/futures trade (FALSE)",
    )
    leverage_ratio: Column[DECIMAL] = Column(
        DECIMAL(5, 2), default=1.00, comment="Leverage ratio (1.00 for spot trades)"
    )
    price: Column[DECIMAL] = Column(
        DECIMAL(20, 8), nullable=False, comment="price at which the trade was executed")
    quantity: Column[DECIMAL] = Column(
        DECIMAL(20, 8), nullable=False, comment="quantity traded"
    )
    fee: Column[DECIMAL] = Column(
        DECIMAL(20, 8), nullable=False, comment="transaction fee (if any / as USDT)"
    )
    timestamp_utc = Column(TIMESTAMP, nullable=False,
                           comment="trade execution time (UTC)")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    cryptocurrency = relationship(
        "Cryptocurrency", back_populates="trade_data")

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
            f"exchange='{self.exchange_name}', trade_id='{self.trade_id}', "
            f"status='{self.status}', position='{self.position_type}', "
            f"price={self.price}, timestamp_utc={self.timestamp_utc})>"
        )
