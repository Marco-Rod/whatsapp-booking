from app.services.reminder_sender import ReminderSendError

from app.services.whatsapp_sender import WhatsAppSender


class WhatsAppReminderSender:
    def __init__(self, sessions, config, *, sender_factory=WhatsAppSender):
        self.sessions = sessions
        self.config = config
        self.sender_factory = sender_factory

    async def send_for_business(self, business_id: int, phone: str, message: str) -> None:
        try:
            async with self.sessions() as session:
                await self.sender_factory(session, self.config).send_for_business(
                    business_id,
                    phone,
                    message,
                )
        except (WhatsAppSendError, WhatsAppConfigurationError):
            raise ReminderSendError("WhatsApp did not acknowledge the reminder") from None
