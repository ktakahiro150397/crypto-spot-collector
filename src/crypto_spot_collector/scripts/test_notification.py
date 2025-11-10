from io import BytesIO
from pathlib import Path

from crypto_spot_collector.exchange.bybit import SpotOrderResult
from crypto_spot_collector.notification.discord import discordNotification
from crypto_spot_collector.utils.secrets import load_config


async def main() -> None:
    # Load configuration from JSON files
    secrets_path = Path(__file__).parent.parent / "apps" / "secrets.json"
    settings_path = Path(__file__).parent.parent / "apps" / "settings.json"
    secrets = load_config(secrets_path, settings_path)

    notificator: discordNotification = discordNotification(
        webhook_url=secrets["discord"]["discordWebhookUrl"])

    test_file_path: str = str(
        Path(__file__).resolve().parent / "test_notification.png")
    test_file_path2: str = str(
        Path(__file__).resolve().parent / "test_notification2.png")

    file_wrapper: list[tuple[BytesIO, str]] = []
    with open(test_file_path, "rb") as f:
        with open(test_file_path2, "rb") as f2:
            # file_wrapper.append((f, "test_notification.png"))
            # file_wrapper.append((f2, "test_notification2.png"))
            file_wrapper = [
                (BytesIO(f.read()), "test_notification.png"),
                (BytesIO(f2.read()), "test_notification2.png")
            ]

#             symbol = "TEST"
#             amountUsdt = 3
#             freeUsdt = 10
#             message = f"""パラボリックSARでの買いシグナルを確認しました！

# {symbol}を{amountUsdt}USDT分購入しました。
# 残りUSDT: {freeUsdt}USDT"""

#             await notificator.send_notification_async(message, file_wrapper)

            # symbol = "BTC"
            # price = 1234.56
            # amount = 1.23
            # freeUsdt = 10.2345678
            # message = ""
            # footer = "buy_spot.py | bybit"

            # embed = [
            #     {
            #         "title": f":satellite: {symbol} パラボリックSARの上昇トレンドを検知しました！",
            #         "color": 3066993,
            #         "fields": [
            #             {
            #                 "name": "指値価格",
            #                 "value": f"`{price}`"
            #             },
            #             {
            #                 "name": f"購入した{symbol}数量",
            #                 "value": f"`{amount}`"
            #             },
            #             {
            #                 "name": "残りUSDT",
            #                 "value": f"`{freeUsdt}`"
            #             }
            #         ],
            #         "footer": {
            #             "text": f"{footer}"
            #         }
            #     }
            # ]

            test_result: SpotOrderResult = SpotOrderResult(
                symbol="BTC",
                amount=1.23,
                price=1234.56,
                order_value=1518.88,
                original_order={},
                order_id="ORDER123456"
            )
            freeusdt = 10.2345678

            message = ""
            embed = discordNotification.embed_object_create_helper(
                symbol="BTC",
                price=test_result.price,
                amount=test_result.amount,
                freeUsdt=freeusdt,
                order_value=test_result.order_value,
                order_id=test_result.order_id,
                footer="buy_spot.py | bybit",
                timeframe="1h"
            )
            result = await notificator.send_notification_embed_with_file(embeds=[embed],
                                                                         message=message,
                                                                         image_buffers=file_wrapper)
            print(f"Notification result: {result}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
