from typing import Protocol


class ReminderSendError(Exception):
    """The sender could not acknowledge the reminder."""


class ReminderSender(Protocol):
    async def send(self, *, phone: str, message: str) -> None:
        """Return only after the provider acknowledges the message."""
        ...
