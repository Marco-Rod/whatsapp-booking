# Dashboard API

`GET /api/v1/admin/dashboard?date=2026-09-18`

Authentication is required through `admin_session`. The business identity comes
exclusively from that session; clients cannot provide or select a business ID.

`date` is required and represents the business's LOCAL day. The service constructs
both local midnights using Business.timezone and queries the half-open UTC range
`start <= Appointment.starts_at < end`. It does not use SQL DATE(starts_at) or
assume all local days are 24 hours. The date is based on appointment start, not
overlap with the day; a visit starting on the preceding day is excluded.

The response contains date, timezone, summary (total/confirmed/cancelled), and
appointments ordered by starts_at then id. Only CONFIRMED and CANCELLED records
are included. Summary counts use exactly that same result set. Each appointment
has local ISO datetimes with UTC offsets, uppercase status, service id/name,
customer id/name (or null for legacy appointments without a customer), and two
booleans:

- calendar_synced: calendar_event_id is not NULL. This represents a stored link,
  not a live provider health check; cancelled appointments retain that link.
- reminder_sent: ANY reminder for this appointment has sent_at set, including
  historical schedules. It represents API acknowledgement, not device receipt.

No phone numbers, calendar event IDs, reminder timestamps or claims are returned.
Phone-as-name placeholders from WhatsApp are displayed as “Sin nombre”.
After validating the administrative session, the dashboard retrieval makes two
SELECTs regardless of appointment count: business lookup, then a joined
projection with a correlated EXISTS for sent reminders. Multiple reminder rows
do not duplicate appointments. All appointment results and joined
service/customer data are scoped to the authenticated business.

A valid empty day returns 200 with zero counts and an empty list. Invalid dates
or unsupported calendar boundaries return 422. The endpoint performs no
mutations or external calls.
