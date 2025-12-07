import asyncio
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.utils.secrets import load_config

# ログ設定
# ログフォルダのパスを取得（プロジェクトルート/logs）
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ログファイル名（日付付き）
log_file = LOG_DIR / \
    f"hyperliquid_test_{datetime.now().strftime('%Y%m%d')}.log"

# loguruのログ設定
# デフォルトのハンドラーを削除
logger.remove()

# 標準出力にログを表示（INFOレベル以上、docker logsで確認可能）
logger.add(
    sink=sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="DEBUG",
    colorize=True,
)

# ファイルにログを保存（DEBUGレベル以上、日次ローテーション）
logger.add(
    sink=log_file,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    rotation="00:00",  # 毎日0時にローテーション
    retention="30 days",  # 30日間保持
    compression="zip",  # 古いログファイルをzip圧縮
    encoding="utf-8",
)


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

    # ロング作成
    result = await hyperliquid_exchange.create_order_perp_long_async(
        symbol="ETH/USDC:USDC",
        amount=0.01,
        price=3000,
    )
    print("Order Result:", result)

    # TP/SLのID・価格を取得
    current_orders = await hyperliquid_exchange.fetch_open_orders_all_async(
        symbol="ETH/USDC:USDC",
    )
    print("Current Orders:", current_orders)

    stop_loss_orders = [
        order for order in current_orders if order.get("info", {}).get("orderType") == "Stop Market"
    ]
    print("Current Stop Loss Orders:", stop_loss_orders)
    take_profit_orders = [
        order for order in current_orders if order.get("info", {}).get("orderType") == "Take Profit Market"
    ]
    print("Current Take Profit Orders:", take_profit_orders)

    stoploss_order_id = stop_loss_orders[0].get("id", "")
    stoploss_trigger_price = stop_loss_orders[0].get("triggerPrice", 0)
    takeprofit_order_id = take_profit_orders[0].get("id", "")
    takeprofit_trigger_price = take_profit_orders[0].get("triggerPrice", 0)

    # SL/TPのキャンセルと再作成
    cancel_result = await hyperliquid_exchange.cancel_orders_async(
        order_ids=[stoploss_order_id, takeprofit_order_id],
        symbol="ETH/USDC:USDC",
    )
    print("Cancel SL Result:", cancel_result)

    create_sl_result = await hyperliquid_exchange.create_take_profit_stop_loss_order_async(
        symbol="ETH/USDC:USDC",
        sl_trigger_price=stoploss_trigger_price - 100,
        tp_trigger_price=takeprofit_trigger_price + 100,
    )
    print("Create SL Result:", create_sl_result)

if __name__ == "__main__":
    asyncio.run(main())
