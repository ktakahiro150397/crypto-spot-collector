from datetime import datetime, timedelta, timezone
from typing import Any

from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.scripts.import_historical_data import HistoricalDataImporter


def load_secrets() -> Any:
    import json
    from pathlib import Path

    secrets_path = Path(__file__).parent / "secrets.json"
    with open(secrets_path, "r") as f:
        secrets = json.load(f)
    return secrets


async def main() -> None:
    secrets = load_secrets()

    bybit_exchange = BybitExchange(
        apiKey=secrets["bybit"]["apiKey"],
        secret=secrets["bybit"]["secret"]
    )

    xrp = bybit_exchange.fetch_price("XRP/USDT")
    print(f"xrp price : {xrp}")
    print(f"xrp last price : {xrp['last']}")

    print(datetime.now())
    # 過去1日のOHLCVデータを取得して登録
    toDateUtc = datetime.now(timezone.utc)
    fromDateUtc = toDateUtc - timedelta(days=1)
    xrp_ohlcv = bybit_exchange.fetch_ohlcv(
        symbol="XRP/USDT",
        timeframe="4h",
        fromDate=fromDateUtc,
        toDate=toDateUtc,
    )
    print(f"xrp ohlcv : {xrp_ohlcv}")

    # OHLCVデータの登録
    importer = HistoricalDataImporter()
    importer.register_data('XRP', xrp_ohlcv)

    balance = bybit_exchange.fetch_balance()

    for value in balance["info"]["result"]["list"]:
        for coin in value["coin"]:
            equity = float(coin["equity"])
            locked = float(coin["locked"])

            print(
                f"{coin['coin']}: equity : {equity} | locked: {locked} | free: {equity - locked}")

    # order_result = bybit_exchange.create_order_spot()
    # print(order_result)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
