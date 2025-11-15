

from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.repository.ohlcv_repository import OHLCVRepository
from crypto_spot_collector.repository.trade_data_repository import TradeDataRepository
from crypto_spot_collector.utils.pnl import create_pnl_plot
from crypto_spot_collector.utils.secrets import load_config

spot_symbol = ["btc", "eth", "xrp", "sol", "link",
               "avax", "hype", "bnb", "doge", "wld", "ltc", "pol",
               "xaut",]


async def main() -> bool:
    from pathlib import Path

    # Use the secrets.json and settings.json from the apps directory
    secrets_path = Path(__file__).parent.parent / "apps" / "secrets.json"
    settings_path = Path(__file__).parent.parent / "apps" / "settings.json"
    secrets = load_config(secrets_path, settings_path)

    bybit_exchange = BybitExchange(
        apiKey=secrets["bybit"]["apiKey"],
        secret=secrets["bybit"]["secret"]
    )
    async with bybit_exchange:
        with TradeDataRepository() as tradeRepo:
            pnl_result = await create_pnl_plot(
                exchange=bybit_exchange,
                tradeRepo=tradeRepo
            )

            # bytesIOを保存
            with open("pnl_statement_test.png", "wb") as f:
                f.write(pnl_result.img_buffer.getbuffer())

    return True


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
