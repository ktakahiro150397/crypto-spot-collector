#!/usr/bin/env python3
"""Sample script demonstrating how to use OHLCVRepository to fetch data."""

from datetime import datetime, timedelta

from crypto_spot_collector.repository import OHLCVRepository


def main() -> None:
    """Main function demonstrating OHLCVRepository usage."""
    print("=== OHLCV Repository Usage Example ===\n")

    # Create repository instance
    with OHLCVRepository() as repo:
        try:
            # Get available symbols
            print("1. Available symbols:")
            symbols = repo.get_available_symbols()
            print(f"   {symbols[:5]}...")  # Show first 5 symbols
            print()

            # Use BTC as example (if available)
            symbol = "BTC"
            if symbol not in symbols:
                print(f"Symbol {symbol} not found in database.")
                return

            # Get date range for the symbol
            print(f"2. Date range for {symbol}:")
            try:
                earliest, latest = repo.get_date_range(symbol)
                print(f"   Earliest: {earliest}")
                print(f"   Latest: {latest}")
                print()
            except ValueError as e:
                print(f"   Error: {e}")
                return

            # Example 1: Get 4h data for the last week
            print("3. Example 1: 4h data for last 7 days")
            to_date = datetime.now()
            from_date = to_date - timedelta(days=7)

            try:
                data_4h = repo.get_ohlcv_data(
                    symbol=symbol,
                    interval="4h",
                    from_datetime=from_date,
                    to_datetime=to_date
                )
                print(f"   Found {len(data_4h)} records")
                if data_4h:
                    print("   Sample records:")
                    for record in data_4h[:3]:  # Show first 3 records
                        print(
                            f"     {record.timestamp_utc}: "
                            f"O={record.open_price}, "
                            f"H={record.high_price}, "
                            f"L={record.low_price}, "
                            f"C={record.close_price}, "
                            f"V={record.volume}"
                        )
                print()
            except Exception as e:
                print(f"   Error: {e}")
                print()

            # Example 2: Get 1h data count
            print("4. Example 2: 1h data count for last 24 hours")
            to_date = datetime.now()
            from_date = to_date - timedelta(hours=24)

            try:
                count = repo.get_ohlcv_data_count(
                    symbol=symbol,
                    interval="1h",
                    from_datetime=from_date,
                    to_datetime=to_date
                )
                print(f"   Count: {count} records")
                print()
            except Exception as e:
                print(f"   Error: {e}")
                print()

            # Example 3: Get 5m data
            print("5. Example 3: 5m data for last 2 hours")
            to_date = datetime.now()
            from_date = to_date - timedelta(hours=2)

            try:
                data_5m = repo.get_ohlcv_data(
                    symbol=symbol,
                    interval="5m",
                    from_datetime=from_date,
                    to_datetime=to_date
                )
                print(f"   Found {len(data_5m)} records")
                if data_5m:
                    print("   Time intervals (showing clean 5-minute marks):")
                    for record in data_5m[:5]:  # Show first 5 records
                        print(f"     {record.timestamp_utc}")
                print()
            except Exception as e:
                print(f"   Error: {e}")
                print()

            # Example 4: Get latest data
            print("6. Example 4: Latest 10 records")
            try:
                latest_data = repo.get_latest_ohlcv_data(symbol=symbol, limit=10)
                print(f"   Found {len(latest_data)} records")
                if latest_data:
                    print("   Latest records:")
                    for record in latest_data[:3]:  # Show first 3 records
                        print(
                            f"     {record.timestamp_utc}: "
                            f"Close={record.close_price}"
                        )
                print()
            except Exception as e:
                print(f"   Error: {e}")
                print()

        except Exception as e:
            print(f"Database connection error: {e}")


if __name__ == "__main__":
    main()
