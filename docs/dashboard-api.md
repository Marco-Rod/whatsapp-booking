# Dashboard API (Day 5, checkpoint 4)

`GET /api/v1/businesses/{business_id}/dashboard?date=2026-09-18`

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
The endpoint makes two SELECTs regardless of appointment count: business lookup,
then a joined projection with a correlated EXISTS for sent reminders. Multiple
reminder rows do not duplicate appointments. All appointment results and joined
service/customer data are scoped to the requested business.

An unknown business returns 404. A valid empty day returns 200 with zero counts
and an empty list. Invalid dates or unsupported calendar boundaries return 422.
No mutations, external calls, new migrations, authentication implementation or
React changes are included in this checkpoint.
