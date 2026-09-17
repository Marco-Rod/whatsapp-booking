from app.services.reminder_sender import ReminderSendError

from .client import WhatsAppClient, WhatsAppConfigurationError, WhatsAppSendError


class WhatsAppReminderSender:
    def __init__(self, client: WhatsAppClient):
        self.client = client

    async def send(self, *, phone: str, message: str) -> None:
        try:
            await self.client.send_text(phone, message)
        except (WhatsAppSendError, WhatsAppConfigurationError):
            raise ReminderSendError("WhatsApp did not acknowledge the reminder") from None
