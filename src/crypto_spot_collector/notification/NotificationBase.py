from abc import ABC, abstractmethod
from io import TextIOWrapper


class NotificationBase(ABC):
    """Base class for notifications."""

    def __init__(self) -> None:
        pass

    @abstractmethod
    async def send_notification_async(
        self, message: str, files: list[TextIOWrapper]
    ) -> None:
        """Send a notification with the given message."""
        pass
