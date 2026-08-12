from io import BytesIO
from typing import Any

import pytest
from loguru import logger

from crypto_spot_collector.notification.discord import discordNotification


class _Response:
    status_code = 204
    text = ""


@pytest.mark.asyncio
async def test_discord_accepts_all_successful_http_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def post(_url: str, **kwargs: Any) -> _Response:
        calls.append(kwargs)
        return _Response()

    monkeypatch.setattr(
        "crypto_spot_collector.notification.discord.requests.post", post
    )
    messages: list[str] = []
    sink = logger.add(messages.append, level="DEBUG", format="{message}")
    notification = discordNotification("https://example.invalid/webhook")
    try:
        await notification.send_notification_async("started", [])
        image_result = await notification.send_notification_with_image_async(
            "image", [(BytesIO(b"image"), "image.png")]
        )
        embed_result = await notification.send_notification_embed_with_file(
            "embed", {}, [(BytesIO(b"image"), "image.png")]
        )
    finally:
        logger.remove(sink)

    assert image_result is True
    assert embed_result is True
    assert len(calls) == 3
    assert all("Error:" not in message for message in messages)
