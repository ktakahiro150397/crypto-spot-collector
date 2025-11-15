

from crypto_spot_collector.database import db_manager
from crypto_spot_collector.repository.trade_data_repository import TradeDataRepository

spot_symbol = ["btc", "eth", "xrp", "sol", "link",
               "avax", "hype", "bnb", "doge", "wld", "ltc", "pol",
               "xaut",]


def main() -> bool:
    # Test connection
    if not db_manager.test_connection():
        print("❌ Database connection failed!")
        return False

    with TradeDataRepository() as repo:
        # trade_data = repo.create_or_update_trade_data(
        #     cryptocurrency_name="BTC",
        #     exchange_name="Binance",
        #     trade_id="unique_trade_00001",
        #     status="OPEN",
        #     position_type="LONG",
        #     is_spot=True,
        #     leverage_ratio=1.00,
        #     price=99999.00,
        #     quantity=0.1,
        #     fee=5.00,
        #     timestamp_utc="2024-06-01 13:00:00",
        # )
        # print(f"Trade data record created/updated: {trade_data}")

        # repo.update_trade_status_by_trade_id(
        #     trade_id="unique_trade_00001",
        #     new_status="CLOSED"
        # )
        # print("Trade status updated successfully.")

        for symbol in spot_symbol:

            holdings, avg_price = repo.get_current_position_and_avg_price(
                symbol=symbol
            )
            print(
                f"{symbol.upper() : <4} :  Average Buy Price: {avg_price : 8f} / Holdings: {holdings : 8f} / overall value: {holdings * avg_price : 8f}")

    return True


if __name__ == "__main__":
    main()
