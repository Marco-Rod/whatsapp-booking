# Day 5: reminder discovery

`ReminderService(session).find_due(now)` accepts an explicit timezone-aware
datetime. It owns a transaction, creates missing reminder records and returns
unsent, unclaimed reminders. There is no scheduler or endpoint in this checkpoint.

The due rule is `now < appointment.starts_at <= now + 24 hours`, only for
CONFIRMED appointments. `scheduled_for` is always `starts_at - 24 hours` in UTC.
This catches up late executions until the appointment starts, and includes
bookings made less than 24 hours beforehand. It never sends early. A later
sender formats the actual local date/time rather than always saying “tomorrow”.

The unique `(appointment_id, scheduled_for)` key and conflict-safe insert prevent
duplicate rows, including concurrent PostgreSQL discoveries. Pending rows are
returned again until `sent_at` is set; finding a reminder does not claim it for
delivery. ReminderProcessor provides delivery ownership and rechecks the current
booking after discovery before sending.

Rescheduling changes the schedule key. Old records remain as history and are
not returned for the new time. A sent record suppresses only the exact matching
schedule. Cancelled or already-started appointments are excluded even if they
have unsent records. No reminders are generated inside BookingService.

Migration `0005` adds the table, FK, unique constraint and timezone-aware columns.
Run `alembic upgrade head` in the API container and verify `alembic current`.
The local default test suite uses SQLite; the concurrent test requires
`TEST_DATABASE_URL` pointing to PostgreSQL and uses the existing isolated-schema
fixture (it does not mutate application bookings).

## Manual sending (checkpoint 2)

`ReminderSender` is a provider-neutral Protocol. `WhatsAppReminderSender` adapts
the existing WhatsAppClient and translates provider failures to ReminderSendError.
`ReminderProcessor(sessions, sender).process_due_reminders(now)` returns the
number of acknowledged reminders, taking an explicit aware timestamp for tests.
`sent_at=now` is written only after the sender returns successfully; it represents
API acknowledgement, not a delivery/read receipt on the user's device.

Migration 0006 adds a nullable claim_token. A conditional UPDATE claims an unsent,
unclaimed reminder in a short transaction. The processor reloads its current
appointment, customer, service and business, verifies CONFIRMED and the exact
schedule, then closes the session before calling the sender. A successful send
records sent_at and clears the token in a separate transaction. A known send
failure clears the claim but leaves sent_at NULL, allowing a later retry.
Only the matching token can finalize/release a claimed row.

There is deliberately no automatic claim expiry: process interruption or a DB
failure after sending leaves a retained claim for manual reconciliation. Do not
clear it until the external outcome is reviewed. This prevents concurrent
processors from resending a slow or interrupted operation. A transport timeout
or missing API acknowledgement can still be ambiguous; retry may duplicate a
message already accepted by Meta. This is not exactly-once external delivery.
Cancellation/reschedule is rechecked before sending, but a change during the
external call cannot recall the message. No DB transaction spans that call.

From the repository root, with backend's virtualenv:

```powershell
python scripts/prepare_reminder_test.py --phone +52...
python scripts/process_reminders.py --appointment-id ID
python scripts/process_reminders.py --appointment-id ID
```

The preparation command creates a real appointment in Bella Studio's next
available slot within 24 hours; it sends nothing. The processor sends real
WhatsApp messages. Omitting --appointment-id processes ALL due reminders.
The second acknowledged cycle should report zero. Provider failures log the
reminder ID and sanitized numeric provider error codes, and leave it pending.

This adapter uses free-form text, so the recipient must have an open WhatsApp
customer-service window. Sending business-initiated reminders outside that
window will require an approved template in a later integration step. Verify
receipt on the test phone separately from API acknowledgement. No cron, Celery,
APScheduler or background task is installed.

The adapter preserves the configured recipient exactly. Do not automatically
rewrite Mexican +52 numbers to +521: the test sender rejected that alternate
format with error 131030, while accepting the configured +52 recipient. Use
the recipient verified for the sending account; API acknowledgement alone still
does not prove delivery. HTTP failures log only status and numeric error code.

## Official command and external scheduling (checkpoint 3)

Install/update the backend package in its virtual environment from `backend/`:

```powershell
python -m pip install -e .
process-reminders
```

Equivalent entry points are `python -m app.commands.process_reminders` from
backend, or `python scripts/process_reminders.py` from the repository root.
The script is only a compatibility wrapper. All entry points run exactly one
cycle, dispose the database engine, print a summary and exit; there is no loop
and FastAPI never schedules the job. `--appointment-id ID` limits a test cycle.

Example output: `Reminder processing completed: sent=2 failed=0`.

Exit codes:

- 0: cycle completed without send failures, including an empty queue.
- 1: cycle completed with at least one recoverable send failure; other reminders
  were still processed, and failed sends remain available for a later cycle.
- 2: invalid arguments or a fatal setup/database/unexpected error. Retained
  claims require reconciliation as described above; do not blindly clear them.
- 130: interrupted by the operator.

The compatibility method `process_due_reminders(now)` still returns the sent
count. The command uses `process_once(now)` returning both sent and failed.
Neither count asserts device delivery; sent means provider acknowledgement.

Configure the external scheduler to invoke the command **every 5 minutes**.
Example crontab on a deployed Linux host (replace the path):

```cron
*/5 * * * * cd /srv/whatsapp-booking/backend && /srv/whatsapp-booking/backend/.venv/bin/process-reminders
```

Use the backend working directory for .env loading, or supply DATABASE_URL and
the WHATSAPP_* credentials through the scheduler's secret environment. Do not
embed secrets in the command. On Windows, use Task Scheduler with the absolute
`.venv\Scripts\process-reminders.exe` path, backend as “Start in”, and a five-minute
repeat trigger. This checkpoint supplies the command and deployment recipe; no
machine scheduler is installed or enabled automatically.

If the 12:00 and 12:05 invocations are missed, the 12:10 cycle still discovers
unsent reminders whose scheduled_for is earlier and appointment has not started.
Concurrent invocations retain the same database claim guarantees. External
schedulers should capture stdout/stderr and the exit code for monitoring.
