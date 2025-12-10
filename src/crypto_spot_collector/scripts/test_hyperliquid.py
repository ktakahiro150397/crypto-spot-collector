import pandas as pd
from matplotlib import pyplot as plt
from pyparsing import Any

from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.exchange.types import PositionSide
from crypto_spot_collector.utils.secrets import load_config
from crypto_spot_collector.utils.trade_data import get_current_pnl_from_db


def handle_candle_data(candle_data: dict[str, Any]) -> None:
    coin = candle_data["s"]
    symbol = f"{coin}/USDC:USDC"
    highest_price = float(candle_data["h"])

    print(f"Symbol: {symbol}, Highest Price: {highest_price}")


async def main() -> None:
    import asyncio
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
        testnet=False,
    )

    try:
        # ws経由でティッカーの変動を受信
        perp_symbols = [
            "BTC/USDC:USDC",
            "ETH/USDC:USDC",
            "XRP/USDC:USDC",
            "SOL/USDC:USDC",
            "HYPE/USDC:USDC",
            "ZEC/USDC:USDC",
            "FARTCOIN/USDC:USDC",
        ]

        # サブスクリプションを設定
        for symbol in perp_symbols:
            await hyperliquid_exchange.subscribe_ohlcv_ws(
                symbol=symbol,
                interval="1m",
                callback=handle_candle_data,
            )

        print("Subscriptions set up. Starting WebSocket listener...")

        # WebSocketリスナーをバックグラウンドタスクとして起動
        listener_task = asyncio.create_task(
            hyperliquid_exchange.start_ws_listener())

        # 無限にデータを受信し続ける（Ctrl+Cで終了）
        print("Listening for candle data... Press Ctrl+C to stop")

        # 方法1: asyncio.Event を使う（推奨）
        stop_event = asyncio.Event()
        await stop_event.wait()  # Ctrl+Cまで永遠に待機

        # 方法2: while True を使う場合
        # while True:
        #     await asyncio.sleep(1)  # CPU使用率を下げるため短いsleepを入れる

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        # クリーンアップ
        await hyperliquid_exchange.close()
        if 'listener_task' in locals():
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass
        print("WebSocket connection closed.")

    # balance = await hyperliquid_exchange.fetch_balance_async()

    # print("Balance:", balance)

    # result = await hyperliquid_exchange.create_order_perp_short_async(
    #     symbol="ETH/USDC:USDC",
    #     amount=0.01,
    #     price=3000,
    # )
    # print("Order Result:", result)

    # tpsl_order = await hyperliquid_exchange.fetch_tp_sl_info(
    #     symbol="ETH/USDC:USDC",
    # )
    # print("TP/SL Order Info:", tpsl_order)

    # if tpsl_order is not None:
    #     take_profit_order_id = tpsl_order.take_profit_order_id
    #     stop_loss_order_id = tpsl_order.stop_loss_order_id

    #     # 更新
    #     new_tpsl_order = await hyperliquid_exchange.create_or_update_tp_sl_async(
    #         symbol="ETH/USDC:USDC",
    #         side=PositionSide.SHORT,
    #         takeprofit_order_id=take_profit_order_id,
    #         stoploss_order_id=stop_loss_order_id,
    #         take_profit_trigger_price=3100,
    #         stop_loss_trigger_price=3400,
    #     )
    #     print("Updated TP/SL Order Info:", new_tpsl_order)

    # positions = await hyperliquid_exchange.exchange_public.fetch_positions(["ETH/USDC:USDC"])
    # print("Positions:", positions)

    # from crypto_spot_collector.apps.buy_perp import initialize_trailing_manager
    # await initialize_trailing_manager()

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
    # close_result = await hyperliquid_exchange.close_all_positions_perp_async(
    #     side=PositionSide.LONG,
    #     close_symbol="BTC/USDC:USDC",
    # )
    # print("Close Position Result:", close_result)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
