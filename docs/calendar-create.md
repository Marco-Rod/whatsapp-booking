# Calendar CREATE checkpoint

WhatsApp creation and REST reschedule/cancel are connected. REST creation
is unchanged. `ConversationResult.appointment_id` is set only for a newly
created appointment. `WebhookService` syncs after committing the conversation,
appointment and processed inbound message; it closes its read transaction before
calling Google and saves the external ID in a separate transaction.

A null `Business.calendar_id` disables Calendar. Existing event IDs are skipped.
Duplicate processed inbound messages only resume pending WhatsApp delivery;
they do not retry Calendar, even if an earlier sync failed. Google failures leave
the confirmed appointment intact and do not suppress the WhatsApp reply.

## Local setup and verification

The API reads `GOOGLE_CALENDAR_TOKEN_FILE` (default `../token.json`, relative to
the backend working directory). Authorize manually using the OAuth test script
first. The API never opens a browser. Each SDK operation gets fresh credentials
and an independent HTTP transport with a 20-second socket timeout.

Run from `backend/` with its virtual environment:

```powershell
python -m pytest -q
python ../scripts/replay_google_calendar.py
```

The replay enables `primary` on Bella Studio, creates one real confirmed booking
and Calendar event, reads the event back, and checks a duplicate confirmation.
It captures WhatsApp replies locally; no WhatsApp messages are sent. It leaves
the test records in place and refuses to reuse its fictional test customer.
It uses local code and the configured database, not a rebuilt Docker API.
Container deployment requires its own configured token path and secret mount;
credentials must never be copied into the image.

## Recovery boundary

There is no outbox or automatic Calendar retry yet. A crash after the booking
commit can leave an unsynced appointment. An insert timeout, or failure to save
the returned ID, can leave an external event without a stored link. Checking
`calendar_event_id` prevents recreation of a linked event but does not provide
exactly-once creation across those failures or independently concurrent syncs.
Reconciliation/idempotent retry is a later checkpoint; do not blindly retry an
ambiguous insert. Customer phones, including provisional phone-as-name values,
are omitted from Calendar descriptions.

## RESCHEDULE checkpoint

The REST reschedule endpoint commits through BookingService first, then invokes
BookingCalendarSync. Its read transaction also ends before Calendar is called.
CalendarService updates the existing event only when both calendar_id and
calendar_event_id exist; it never falls back to CREATE or changes the stored ID.
If Google fails, the endpoint still returns the committed new booking times.
Rejected reschedules never reach Calendar. Independent simultaneous reschedules
are not serialized across Google calls yet; eventual reconciliation remains a
future concern, as with recovery from a failed update.

From backend, `python ../scripts/replay_calendar_reschedule.py` exercises the
actual REST handler in-process against the configured PostgreSQL and Google. It
moves test appointment #3 to September 18, 2026, 16:00–17:00 Mexico City time and
reads the same event back, checking ID equality and both times. It does not
rebuild Docker, send WhatsApp messages, or change cancellation behavior.

## CANCEL checkpoint

`cancel_appointment_with_result` reports `was_cancelled_now`, calculated under
the same business lock as the transition and returned only after commit. The
existing `cancel_appointment` method preserves its original response contract.
The REST endpoint invokes Calendar only for a CONFIRMED -> CANCELLED transition.
A repeated cancellation returns the same response without deleting again.

`calendar_event_id` is retained after deletion for traceability: it identifies
the associated external resource, not necessarily an active event. A failed
Google delete does not undo cancellation or clear this ID. Repeating the cancel
endpoint does not retry a failed Google deletion; explicit reconciliation is
still pending. CalendarService needs only Appointment and Business for deletion.

From backend, `python ../scripts/replay_calendar_cancel.py` cancels test booking
#3, repeats the request, verifies only one sync, and checks via events.get that
the original event is absent (404/410) or has status=cancelled. It leaves the
cancelled appointment and its original ID in PostgreSQL. This lifecycle script
is intended to run once after the CREATE and RESCHEDULE replays.
