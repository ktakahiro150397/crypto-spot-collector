import pandas as pd
from matplotlib import pyplot as plt

from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.utils.secrets import load_config


async def main() -> None:
    from pathlib import Path

    # Use the secrets.json and settings.json from the apps directory
    secrets_path = Path(__file__).parent.parent / "apps" / "secrets.json"
    settings_path = Path(__file__).parent.parent / "apps" / "settings.json"
    secrets = load_config(secrets_path, settings_path)

    bybit_exchange = BybitExchange(
        apiKey=secrets["bybit"]["apiKey"],
        secret=secrets["bybit"]["secret"]
    )

    # average = bybit_exchange.fetch_average_buy_price_spot("LTC")
    # print(f"ltc average buy price: {average}")

    # ltc = bybit_exchange.get_current_spot_pnl("LTC")
    # print(f"ltc pnl: {ltc:+.5f} USDT")

    # all_orders = bybit_exchange.fetch_close_orders_all(
    #     symbol="LTC"
    # )
    # print(f"all ltc orders: {all_orders}")

    # portfolio = bybit_exchange.get_spot_portfolio()
    # print("spot portfolio:")
    # for asset in portfolio:
    #     print(
    #         f"Asset: {asset.symbol} | Total Amount: {asset.total_amount} | Current Value: {asset.current_value} | PnL: {asset.profit_loss}"
    #     )

    # # ポートフォリオデータをDataFrameに変換
    # portfolio_data = []
    # for asset in portfolio:
    #     portfolio_data.append({
    #         'Symbol': asset.symbol,
    #         'Total_Amount': asset.total_amount,
    #         'Current_Value': asset.current_value,
    #         'PnL': asset.profit_loss
    #     })

    # df = pd.DataFrame(portfolio_data)
    # print("\nPortfolio DataFrame:")
    # print(df)

    # # グラフの表示
    # if not df.empty:
    #     # 日本語フォントの設定
    #     plt.rcParams['font.family'] = 'DejaVu Sans'

    #     # サブプロットの作成
    #     fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    #     fig.suptitle('Cryptocurrency Portfolio Analysis', fontsize=16)

    #     # 1. 現在価値の棒グラフ
    #     axes[0].bar(df['Symbol'], df['Current_Value'])
    #     axes[0].set_title('Current Value by Asset')
    #     axes[0].set_ylabel('Value (USDT)')
    #     axes[0].tick_params(axis='x', rotation=45)

    #     # 2. PnLの棒グラフ（正負で色分け）
    #     colors = ['green' if x >= 0 else 'red' for x in df['PnL']]
    #     axes[1].bar(df['Symbol'], df['PnL'], color=colors)
    #     axes[1].set_title('Profit & Loss by Asset')
    #     axes[1].set_ylabel('PnL (USDT)')
    #     axes[1].tick_params(axis='x', rotation=45)
    #     axes[1].axhline(y=0, color='black', linestyle='-', alpha=0.3)

    #     plt.tight_layout()

    #     # 画像として保存
    #     plt.savefig('portfolio_analysis.png', dpi=300, bbox_inches='tight')
    #     print("\nグラフを 'portfolio_analysis.png' として保存しました")

    #     # グラフを表示
    #     plt.show()
    # else:
    #     print("ポートフォリオデータが空です")

    # overall_pnl = 0.0
    # for asset in portfolio:
    #     result = bybit_exchange.get_current_spot_pnl("XAUT")
    #     print(f"{asset} PnL: {result}")
    #     overall_pnl += result
    # print(f"Overall PnL: {overall_pnl}")

    # xrp = bybit_exchange.fetch_price("XRP/USDT")
    # print(f"xrp price : {xrp}")
    # print(f"xrp last price : {xrp['last']}")

    result = bybit_exchange.create_order_spot(1, "DOGE")
    print(f"order result : {result}")

    # bnb_average = bybit_exchange.fetch_average_buy_price_spot("BNB")
    # print(f"bnb average price : {bnb_average}")

    # print(datetime.now())
    # # 過去1日のOHLCVデータを取得して登録
    # toDateUtc = datetime.now(timezone.utc)
    # fromDateUtc = toDateUtc - timedelta(days=1)
    # xrp_ohlcv = bybit_exchange.fetch_ohlcv(
    #     symbol="XRP/USDT",
    #     timeframe="4h",
    #     fromDate=fromDateUtc,
    #     toDate=toDateUtc,
    # )
    # print(f"xrp ohlcv : {xrp_ohlcv}")

    # # OHLCVデータの登録
    # importer = HistoricalDataImporter()
    # importer.register_data('XRP', xrp_ohlcv)

    # balance = bybit_exchange.fetch_balance()

    # for value in balance["info"]["result"]["list"]:
    #     for coin in value["coin"]:
    #         equity = float(coin["equity"])
    #         locked = float(coin["locked"])

    #         print(
    #             f"{coin['coin']}: equity : {equity} | locked: {locked} | free: {equity - locked}")

    # order_result = bybit_exchange.create_order_spot(
    #     amountByUSDT=1,
    #     symbol="XRP"
    # )
    # print(order_result)

    # order_result = bybit_exchange.create_order_spot(
    #     amountByUSDT=1,
    #     symbol="SOL"
    # )
    # print(order_result)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
