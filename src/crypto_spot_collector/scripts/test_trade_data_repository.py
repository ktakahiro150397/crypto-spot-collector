

from crypto_spot_collector.database import db_manager
from crypto_spot_collector.repository.trade_data_repository import TradeDataRepository


def main() -> bool:
    # Test connection
    if not db_manager.test_connection():
        print("❌ Database connection failed!")
        return False

    with TradeDataRepository() as repo:
        trade_data = repo.create_or_update_trade_data(
            cryptocurrency_name="BTC",
            exchange_name="Binance",
            trade_id="unique_trade_00001",
            status="OPEN",
            position_type="LONG",
            is_spot=True,
            leverage_ratio=1.00,
            price=99999.00,
            quantity=0.1,
            fee=5.00,
            timestamp_utc="2024-06-01 13:00:00",
        )
        print(f"Trade data record created/updated: {trade_data}")

        repo.update_trade_status_by_trade_id(
            trade_id="unique_trade_00001",
            new_status="CLOSED"
        )
        print("Trade status updated successfully.")

    return True


if __name__ == "__main__":
    main()
