Vamos. Para el **Día 2** cambia el objetivo: ayer respondíamos *“¿qué horarios están libres?”*; hoy debemos poder **reservarlos de verdad y mantener el ciclo de vida de una cita**.

Además, revisé implementaciones actuales similares y hay una decisión que vale la pena incorporar desde ahora: la prevención de doble reserva debe vivir también en la capa de persistencia/transacción, no únicamente en un `if` del servicio. Proyectos de booking más maduros aplican precisamente constraints/locking para evitar carreras concurrentes. ([GitHub][1])

## Día 2 — Booking Lifecycle

La meta de hoy es terminar con esto:

```text
AvailabilityService ─────────────┐
                                 │
Customer ────────────────┐       │
                         ▼       ▼
                    BookingService
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
            CREATE     CANCEL   RESCHEDULE
              │
              ▼
          PostgreSQL
              │
       concurrency-safe
```

### 1. Agregamos `Customer`

Mantendría el modelo pequeño:

```text
Customer
────────────────────
id
business_id
phone
name
created_at
updated_at
```

Con una restricción importante:

```text
UNIQUE (business_id, phone)
```

Porque el mismo teléfono podría aparecer en negocios distintos.

Todavía **no** necesitamos email, notas, preferencias, cumpleaños, tags, marketing, etc.

---

## 2. Ahora `Appointment` sí se convierte en entidad real

Ya existe como soporte de disponibilidad. Hoy completaremos su ciclo de vida:

```text
Appointment
────────────────────
id
business_id
customer_id
service_id

starts_at
ends_at

status

created_at
updated_at
```

Estados:

```python
PENDING = "pending"
CONFIRMED = "confirmed"
CANCELLED = "cancelled"
COMPLETED = "completed"
```

Para el MVP, cuando alguien reserva correctamente podemos crear directamente:

```text
CONFIRMED
```

`PENDING` será útil más adelante cuando WhatsApp esté esperando la confirmación final.

---

# 3. Primera operación: CREATE

Quiero que nuestro endpoint sea:

```http
POST /api/v1/appointments
```

Request:

```json
{
  "business_id": 1,
  "service_id": 1,
  "customer": {
    "name": "Andrea",
    "phone": "+523312345678"
  },
  "starts_at": "2026-09-19T11:30:00-06:00"
}
```

No pediría `ends_at`.

Eso lo calcula el servidor:

```python
ends_at = starts_at + timedelta(
    minutes=service.duration_minutes
)
```

El cliente tampoco manda:

```text
status
calendar_event_id
duration
```

porque son responsabilidad del backend.

Respuesta:

```http
201 Created
```

```json
{
  "id": 42,
  "business_id": 1,
  "service_id": 1,
  "customer": {
    "id": 8,
    "name": "Andrea",
    "phone": "+523312345678"
  },
  "starts_at": "2026-09-19T11:30:00-06:00",
  "ends_at": "2026-09-19T12:30:00-06:00",
  "status": "confirmed"
}
```

---

# 4. BookingService

No metería la lógica en el router.

```text
API
 ↓
BookingService
 ↓
Repositories
 ↓
PostgreSQL
```

Su interfaz inicial podría quedar conceptualmente así:

```python
class BookingService:

    async def create_appointment(...):
        ...

    async def cancel_appointment(...):
        ...

    async def reschedule_appointment(...):
        ...

    async def get_appointment(...):
        ...
```

Y una regla fundamental:

> `BookingService` es dueño de las reglas del ciclo de vida de las citas.

WhatsApp, React y posteriormente Google Calendar **lo consumirán**.

---

# 5. Validaciones de CREATE

Aquí es donde empieza lo divertido.

Una solicitud debe fallar si:

```text
Business no existe                  → 404
Service no existe                   → 404
Service pertenece a otro Business   → 400/404
Service inactivo                    → 409
Día cerrado                         → 409
Fuera de horario                    → 409
No cabe duración completa           → 409
Existe colisión                     → 409
```

Pero hay algo todavía más importante.

No debemos implementar:

```python
if slot_is_available:
    await create()
```

y pensar que estamos protegidos.

Porque puede suceder:

```text
Request A                         Request B
─────────                         ─────────

check 11:30
   ↓
FREE

                                  check 11:30
                                     ↓
                                   FREE

INSERT
                                  INSERT

        💥 DOBLE RESERVA
```

Ambas solicitudes consultaron antes de que existiera la otra cita.

---

# 6. Concurrencia será requisito del Día 2

Quiero un test explícito:

```text
             11:30 disponible
                    │
          ┌─────────┴─────────┐
          │                   │
      Request A           Request B
          │                   │
          └─────────┬─────────┘
                    ▼
                PostgreSQL
                    │
            ┌───────┴───────┐
            ▼               ▼
       201 Created      409 Conflict
```

Y después:

```sql
SELECT COUNT(*)
FROM appointments
WHERE ...
```

debe devolver:

```text
1
```

Este test eventualmente deberá ejecutarse contra **PostgreSQL real**, no SQLite.

De hecho, proyectos actuales similares hacen explícitamente la prevención de double-booking mediante mecanismos de PostgreSQL, lo cual refuerza nuestra decisión de no dejar esto exclusivamente en Python. ([GitHub][1])

---

# 7. CANCEL

Endpoint:

```http
POST /api/v1/appointments/{id}/cancel
```

No DELETE.

Porque una cita cancelada es información de negocio que queremos conservar.

Transición:

```text
CONFIRMED
    │
    ▼
CANCELLED
```

Y entonces ocurre algo importante para nuestro Día 1:

```text
antes

11:30 ❌ ocupado

cancel()

11:30 ✅ disponible
```

Por lo tanto tendremos un integration test:

```python
create_appointment()
assert slot_not_available()

cancel_appointment()

assert slot_available()
```

Esto conecta perfectamente Día 1 con Día 2.

---

# 8. RESCHEDULE

Endpoint:

```http
POST /api/v1/appointments/{id}/reschedule
```

Request:

```json
{
  "starts_at": "2026-09-19T15:30:00-06:00"
}
```

El backend:

```text
obtiene appointment
        ↓
obtiene service
        ↓
calcula nuevo ends_at
        ↓
valida disponibilidad
        ↓
protege concurrencia
        ↓
actualiza appointment
```

Respuesta:

```json
{
  "id": 42,
  "starts_at": "2026-09-19T15:30:00-06:00",
  "ends_at": "2026-09-19T16:30:00-06:00",
  "status": "confirmed"
}
```

Y aquí hay una pequeña trampa:

cuando verificamos disponibilidad debemos **ignorar la propia cita que estamos reprogramando**.

Conceptualmente:

```python
get_conflicting_appointments(
    ...,
    exclude_appointment_id=appointment.id,
)
```

---

# 9. Idempotencia

También quiero preparar esto pensando en WhatsApp.

El Día 3 Meta podrá reenviar webhooks si no obtiene la respuesta esperada. Sistemas reales de WhatsApp necesitan tratar explícitamente la idempotencia de webhooks/reintentos. ([GitHub][1])

Pero **hoy no construiremos todavía la infraestructura de webhook idempotency**.

Sí quiero que anotemos la regla:

```text
Día 2:
Booking concurrency

Día 3:
Webhook idempotency
```

Son problemas relacionados, pero diferentes.

---

# 10. Tests obligatorios

Nuestro Definition of Done será más exigente que ayer:

| Test                         | Resultado               |
| ---------------------------- | ----------------------- |
| crear cita válida            | `201`                   |
| Customer nuevo               | creado                  |
| mismo teléfono mismo negocio | reutilizado             |
| mismo teléfono otro negocio  | Customer independiente  |
| service inexistente          | `404`                   |
| business inexistente         | `404`                   |
| servicio inactivo            | rechazo                 |
| fuera de horario             | rechazo                 |
| día cerrado                  | rechazo                 |
| colisión completa            | `409`                   |
| colisión parcial izquierda   | `409`                   |
| colisión parcial derecha     | `409`                   |
| intervalos adyacentes        | permitido               |
| cancelar cita                | `CANCELLED`             |
| cancelar dos veces           | comportamiento definido |
| cita cancelada libera slot   | sí                      |
| reprogramar                  | funciona                |
| reprogramar a slot ocupado   | `409`                   |
| reprogramar al mismo horario | permitido               |
| dos requests concurrentes    | **solo una reserva**    |

Y añadiría un test especialmente importante:

```text
Service = 120 min

16:30 solicitado
Business cierra 18:00

16:30 → 18:30

409 Conflict
```

Aunque el `starts_at` esté dentro del horario.

---

# 11. Lo que NO hacemos hoy

La regla de scope sigue vigente:

```text
❌ WhatsApp
❌ Google Calendar
❌ React
❌ reminders
❌ Celery
❌ Redis
❌ pagos
❌ empleados
❌ múltiples agendas
❌ IA
❌ login
```

Hay implementaciones actuales que añaden Redis, Celery, IA, recordatorios y muchas otras capas desde el principio. ([GitHub][2]) Para nuestro experimento eso sería contraproducente: todavía estamos intentando validar el Booking Core.

---

## Primer checkpoint del Día 2

Empezaría únicamente con:

```text
1. Customer model
2. relationship Business → Customer
3. Appointment → Customer
4. migration Alembic
5. CustomerRepository
6. BookingService.create_appointment()
7. POST /appointments
```

Y **todavía no cancelación/reprogramación**.

Primero debemos conseguir este recorrido:

```text
POST /appointments
       ↓
buscar Business
       ↓
buscar Service
       ↓
get-or-create Customer
       ↓
validar horario
       ↓
validar conflicto
       ↓
crear Appointment
       ↓
201
```

Cuando ese checkpoint pase los tests, atacamos la parte más interesante del Día 2: **hacer que dos reservas simultáneas del mismo horario no puedan ganar las dos**. Esa será nuestra primera garantía seria de consistencia del Booking Core.

[1]: https://github.com/Hiberius/whatsapp-receptionist?utm_source=chatgpt.com "GitHub - Hiberius/whatsapp-receptionist: Open-source AI receptionist for WhatsApp. Books real appointments on Google Calendar, transcribes voice notes, escalates to a human. Multi-tenant Next.js 15 + Supabase + Claude SaaS starter, GDPR-first, self-hostable, MIT. · GitHub"
[2]: https://github.com/Gooda97/WABooker?utm_source=chatgpt.com "GitHub - Gooda97/WABooker: Automated booking system powered by WhatsApp chatbot with dashboard and notification engine. · GitHub"
