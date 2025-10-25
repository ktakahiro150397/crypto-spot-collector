import json
from io import TextIOWrapper

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
