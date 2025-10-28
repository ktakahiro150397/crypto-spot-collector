import json
from io import BytesIO, TextIOWrapper

import requests

from crypto_spot_collector.notification.NotificationBase import NotificationBase


class discordNotification(NotificationBase):
    pass

    def __init__(self, webhook_url: str) -> None:
        super().__init__()

        self.webhook_url: str = webhook_url

    async def send_notification_async(self,
                                      message: str,
                                      files: list[TextIOWrapper]) -> None:
        """Send a notification with the given message."""

        payload = {
            "content": message
        }

        payloadFiles = [(f"file_{i}", (file.name, file, "image/png"))
                        for i, file in enumerate(files)]
        print(payloadFiles)

        response = requests.post(self.webhook_url,
                                 data={
                                     "payload_json": json.dumps(payload),
                                 },
                                 files=payloadFiles)
        print(response.status_code)
        pass

    async def send_notification_with_image_async(
            self,
            message: str,
            image_buffers: list[tuple[BytesIO, str]]) -> bool:
        """Send a notification with images from memory buffers.

        Args:
            message: The message to send
            image_buffers: List of tuples containing (BytesIO buffer, filename)
        """

        payload = {
            "content": message
        }

        # 複数の画像バッファからファイルデータを構築
        files = {}
        for i, (buffer, filename) in enumerate(image_buffers):
            image_data = buffer.getvalue()
            files[f"file_{i}"] = (filename, image_data, "image/png")

        response = requests.post(
            self.webhook_url,
            data={"payload_json": json.dumps(payload)},
            files=files
        )

        print(f"Discord notification sent: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")

        return bool(response.status_code == 200)

    async def send_notification_embed_with_file(self,
                                                message: str,
                                                embeds: dict,
                                                image_buffers: list[tuple[BytesIO, str]]) -> bool:
        """Send a notification with embeds and images from memory buffers."""

        payload = {
            "content": message,
            "embeds": embeds
        }

        # 複数の画像バッファからファイルデータを構築
        files = {}
        for i, (buffer, filename) in enumerate(image_buffers):
            image_data = buffer.getvalue()
            files[f"file_{i}"] = (filename, image_data, "image/png")

        response = requests.post(
            self.webhook_url,
            data={"payload_json": json.dumps(payload)},
            files=files
        )

        print(f"Discord notification with embed sent: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
        return bool(response.status_code == 200)

    def embed_object_create_helper(symbol: str,
                                   price: float,
                                   amount: float,
                                   freeUsdt: float,
                                   order_value: float,
                                   order_id: str,
                                   footer: str) -> dict:
        """Create a Discord embed object for notifications."""
        embed = {
            "title": f":satellite: {symbol} パラボリックSARの上昇トレンドを検知しました！",
            "color": 3066993,  # 緑色
            "fields": [
                {
                    "name": "指値価格",
                    "value": f"`{price}`",
                    "inline": True
                },
                {
                    "name": f"購入した{symbol}数量",
                    "value": f"`{amount}`",
                    "inline": True
                },
                {
                    "name": "注文合計金額",
                    "value": f"`{order_value}`",
                    "inline": True
                },
                {
                    "name": "残りUSDT",
                    "value": f"`{freeUsdt}`",
                    "inline": True
                },
                {
                    "name": "オーダーID",
                    "value": f"`{order_id}`",
                    "inline": True
                }
            ],
            "footer": {
                "text": f"{footer}"
            }
        }
        return embed
