"""Database connection test script."""

from datetime import datetime, timezone
from decimal import Decimal

from crypto_spot_collector.database import db_manager
from crypto_spot_collector.models import Cryptocurrency, OHLCVData, TradeData


def test_database_connection() -> bool:
    """Test database connection and basic operations."""
    print("🔍 Testing database connection...")

    # Test connection
    if not db_manager.test_connection():
        print("❌ Database connection failed!")
        return False

    print("✅ Database connection successful!")

    # Create tables
    print("📋 Creating tables...")
    try:
        db_manager.create_tables()
        print("✅ Tables created successfully!")
    except Exception as e:
        print(f"❌ Failed to create tables: {e}")
        return False

    # Test basic query
    print("🔍 Testing basic queries...")
    try:
        with db_manager.get_session() as session:
            # Count cryptocurrencies
            crypto_count = session.query(Cryptocurrency).count()
            print(f"📊 Cryptocurrencies in database: {crypto_count}")

            # Count OHLCV data
            ohlcv_count = session.query(OHLCVData).count()
            print(f"📊 OHLCV records in database: {ohlcv_count}")

            # Count trade data
            trade_count = session.query(TradeData).count()
            print(f"📊 Trade records in database: {trade_count}")

            # Show some cryptocurrencies
            cryptos = session.query(Cryptocurrency).limit(5).all()
            print("💰 Sample cryptocurrencies:")
            for crypto in cryptos:
                print(f"  - {crypto.symbol}: {crypto.name}")

            # Test sample data insertion (if no data exists)
            if crypto_count > 0 and ohlcv_count == 0:
                print("📝 Inserting sample OHLCV data...")
                btc = session.query(Cryptocurrency).filter_by(symbol="BTC").first()
                if btc:
                    sample_ohlcv = OHLCVData(
                        cryptocurrency_id=btc.id,
                        open_price=Decimal("50000.00"),
                        high_price=Decimal("51000.00"),
                        low_price=Decimal("49000.00"),
                        close_price=Decimal("50500.00"),
                        volume=Decimal("1000.5"),
                        timestamp_utc=datetime.now(timezone.utc),
                    )
                    session.add(sample_ohlcv)

                    sample_trade = TradeData(
                        cryptocurrency_id=btc.id,
                        exchange_name="Binance",
                        position_type="LONG",
                        is_spot=True,
                        leverage_ratio=Decimal("1.00"),
                        price=Decimal("50500.00"),
                        quantity=Decimal("0.1"),
                        timestamp_utc=datetime.now(timezone.utc),
                    )
                    session.add(sample_trade)
                    session.commit()
                    print("✅ Sample data inserted!")

    except Exception as e:
        print(f"❌ Database query failed: {e}")
        return False

    print("✅ Database test completed successfully!")
    return True


if __name__ == "__main__":
    test_database_connection()
