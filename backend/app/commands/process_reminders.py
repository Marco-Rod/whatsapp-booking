import argparse
import asyncio
from datetime import datetime, timezone
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.integrations.whatsapp.client import WhatsAppClient
from app.integrations.whatsapp.reminder_sender import WhatsAppReminderSender
from app.services.reminder_processor import ReminderProcessor, ReminderProcessingResult


async def run_once(appointment_id: int | None = None) -> ReminderProcessingResult:
    from app.core.config import Settings

    config = Settings()
    engine = create_async_engine(config.database_url)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        sender = WhatsAppReminderSender(WhatsAppClient(config))
        return await ReminderProcessor(sessions, sender).process_once(
            datetime.now(timezone.utc), appointment_id=appointment_id,
        )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process due reminders once and exit. Sends real WhatsApp messages.")
    parser.add_argument("--appointment-id", type=int, help="Limit this cycle to one appointment")
    args = parser.parse_args(argv)
    if args.appointment_id is not None and args.appointment_id <= 0:
        parser.error("--appointment-id must be positive")
    try:
        result = asyncio.run(run_once(args.appointment_id))
    except KeyboardInterrupt:
        print("Reminder processing interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        # Exception strings may contain credentials or personal information.
        print(f"Reminder processing failed: error={type(exc).__name__}", file=sys.stderr)
        return 2
    print(f"Reminder processing completed: sent={result.sent} failed={result.failed}")
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
