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
