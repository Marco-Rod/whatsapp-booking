import asyncio
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from google.auth.exceptions import GoogleAuthError
from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from httplib2 import HttpLib2Error

from .errors import GoogleCalendarError


class GoogleCalendarClient:
    """Async adapter for the synchronous Calendar SDK.

    service_factory must return a NEW authorized Calendar v3 Resource (including
    its own credentials/HTTP transport) per call, with a finite HTTP timeout.
    Construction, requests and cleanup all run in the same worker thread.
    OAuth setup belongs to the caller; this client never opens a login browser.
    No automatic retries: a failed insert may already have created the event.
    """

    def __init__(self, service_factory: Callable[[], Resource]):
        self._service_factory = service_factory

    async def create_event(self, calendar_id: str, event: dict[str, Any]) -> str:
        """Insert an event and return its Google ID."""
        return await asyncio.to_thread(
            self._execute, "insert", calendarId=calendar_id, body=deepcopy(event)
        )

    async def update_event(
        self, calendar_id: str, event_id: str, event: dict[str, Any]
    ) -> str:
        """Replace an event using its full writable payload; return its ID."""
        return await asyncio.to_thread(
            self._execute, "update", calendarId=calendar_id,
            eventId=event_id, body=deepcopy(event),
        )

    async def delete_event(self, calendar_id: str, event_id: str) -> None:
        """Delete an event. HTTP errors propagate, including 404/410.

        Missing-event/idempotency policy belongs to the future CalendarService.
        """
        await asyncio.to_thread(
            self._execute, "delete", calendarId=calendar_id, eventId=event_id
        )

    def _execute(self, operation: str, **kwargs: Any) -> str | None:
        try:
            with self._service_factory() as service:
                result = getattr(service.events(), operation)(**kwargs).execute(
                    num_retries=0
                )
                if operation == "delete":
                    return None
                if not isinstance(result, dict) or not isinstance(result.get("id"), str) or not result["id"]:
                    raise GoogleCalendarError(operation)
                return result["id"]
        except HttpError as exc:
            raise GoogleCalendarError(operation, status_code=exc.resp.status) from None
        except (GoogleAuthError, HttpLib2Error, OSError) as exc:
            raise GoogleCalendarError(operation) from None
