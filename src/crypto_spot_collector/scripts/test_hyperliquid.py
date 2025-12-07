import pandas as pd
from matplotlib import pyplot as plt

from crypto_spot_collector.apps.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.exchange.types import PositionSide
from crypto_spot_collector.utils.secrets import load_config
from crypto_spot_collector.utils.trade_data import get_current_pnl_from_db


async def main() -> None:
    from pathlib import Path

    # Use the secrets.json and settings.json from the apps directory
    secrets_path = Path(__file__).parent.parent / "apps" / "secrets.json"
    settings_path = Path(__file__).parent.parent / "apps" / "settings.json"
    secrets = load_config(secrets_path, settings_path)

    hyperliquid_exchange = HyperLiquidExchange(
        mainWalletAddress=secrets["hyperliquid"]["mainWalletAddress"],
        apiWalletAddress=secrets["hyperliquid"]["apiWalletAddress"],
        privateKey=secrets["hyperliquid"]["privatekey"],
        take_profit_rate=secrets["settings"]["perpetual"]["take_profit_rate"],
        stop_loss_rate=secrets["settings"]["perpetual"]["stop_loss_rate"],
        leverage=secrets["settings"]["perpetual"]["leverage"],
        testnet=True,
    )

    # balance = await hyperliquid_exchange.fetch_balance_async()

    # print("Balance:", balance)

    # result = await hyperliquid_exchange.create_order_perp_long_async(
    #     symbol="ETH/USDC:USDC",
    #     amount=0.01,
    #     price=3000,
    # )
    # result = await hyperliquid_exchange.create_order_perp_long_async(
    #     symbol="SOL/USDC:USDC",
    #     amount=5,
    #     price=130,
    # )
    # result = await hyperliquid_exchange.create_order_perp_long_async(
    #     symbol="BTC/USDC:USDC",
    #     amount=0.001,
    #     price=89000,
    # )

    # print("Order Result:", result)

    # 持っているポジションを決済
    close_result = await hyperliquid_exchange.close_all_positions_perp_async(
        side=PositionSide.LONG,
    )
    print("Close Position Result:", close_result)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
