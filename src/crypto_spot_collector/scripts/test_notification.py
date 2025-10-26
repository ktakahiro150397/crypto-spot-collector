from pathlib import Path

from crypto_spot_collector.notification.discord import discordNotification

webhook_url: str = "https://discord.com/api/webhooks/1126667309612793907/uEnoqjxaAk7ZHdNDFVnJaVtfpwSalKf2FEZrB_T1XX4T7HAKMkueISJjb5tztJ3eb1pp"


async def main() -> None:

    notificator: discordNotification = discordNotification(
        webhook_url=webhook_url)

    test_file_path: str = str(
        Path(__file__).resolve().parent / "test_notification.png")
    test_file_path2: str = str(
        Path(__file__).resolve().parent / "test_notification2.png")

    file_wrapper: list = []
    with open(test_file_path, "rb") as f:
        with open(test_file_path2, "rb") as f2:
            file_wrapper.append(f)
            file_wrapper.append(f2)

            symbol = "TEST"
            amountUsdt = 3
            freeUsdt = 10
            message = f"""パラボリックSARでの買いシグナルを確認しました！

{symbol}を{amountUsdt}USDT分購入しました。
残りUSDT: {freeUsdt}USDT"""

            await notificator.send_notification_async(message, file_wrapper)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
