from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


ROOT = Path(__file__).resolve().parents[1]

CREDENTIALS_FILE = ROOT / "secrets" / "google_credentials.json"
TOKEN_FILE = ROOT / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]


def get_credentials() -> Credentials:
    credentials = None

    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(
            TOKEN_FILE,
            SCOPES,
        )

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_FILE,
            SCOPES,
        )

        credentials = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

    return credentials


def main() -> None:
    credentials = get_credentials()

    service = build(
        "calendar",
        "v3",
        credentials=credentials,
    )

    calendar = service.calendars().get(
        calendarId="primary",
    ).execute()

    print("Google Calendar connection OK")
    print("Calendar:", calendar.get("summary"))
    print("Timezone:", calendar.get("timeZone"))

    timezone = ZoneInfo("America/Mexico_City")

    start = datetime.now(timezone) + timedelta(days=1)
    start = start.replace(
        hour=12,
        minute=0,
        second=0,
        microsecond=0,
    )

    end = start + timedelta(hours=1)

    event = {
        "summary": "Corte - Bella Studio [TEST]",
        "description": "Evento de prueba creado por WhatsApp Booking.",
        "start": {
            "dateTime": start.isoformat(),
            "timeZone": "America/Mexico_City",
        },
        "end": {
            "dateTime": end.isoformat(),
            "timeZone": "America/Mexico_City",
        },
    }

    created_event = (
        service.events()
        .insert(
            calendarId="primary",
            body=event,
        )
        .execute()
    )

    print()
    print("Event created successfully")
    print("Event ID:", created_event["id"])
    print("Start:", created_event["start"]["dateTime"])
    print("Link:", created_event.get("htmlLink"))


if __name__ == "__main__":
    main()
