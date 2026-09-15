# Booking Core — Día 2, ciclo de reservas

FastAPI + SQLAlchemy async + PostgreSQL + Alembic. Consulta disponibilidad de un
servicio según el horario semanal y las citas pendientes o confirmadas.

## Ejecutar con Docker Compose

Desde la raíz:

```powershell
docker compose up --build -d
docker compose exec api python -m app.seed
```

El inicio aplica la migración. El seed imprime los IDs y no modifica un negocio
demo ya existente. En una base nueva son `business_id=1` y `service_id=1`.

Abrir http://localhost:8000/docs o consultar:

```powershell
Invoke-RestMethod 'http://localhost:8000/api/v1/availability?business_id=1&service_id=1&date=2026-09-19'
```

## Ejecutar backend local (Windows)

Con PostgreSQL disponible, copiar `.env.example` a `.env` en la raíz y ajustar
`DATABASE_URL` si es necesario. Las credenciales del ejemplo son solo locales.

```powershell
docker compose up -d db
cd backend
.venv/Scripts/python.exe -m pip install -e '.[test]'
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m app.seed
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

## Pruebas

Desde `backend`:

```powershell
.venv/Scripts/python.exe -m pytest -q
```

Incluyen reglas de intervalos y pruebas HTTP con SQLAlchemy/SQLite en memoria.
Estas pruebas no sustituyen la verificación de migraciones en PostgreSQL.

## Reglas del día uno

- Una agenda por negocio; todas sus citas activas bloquean, sin importar servicio.
- Inicios cada 30 minutos desde la apertura; duración independiente del intervalo.
- Lunes es 0 y domingo 6. Un horario ausente o cerrado devuelve `slots: []`.
- Un único tramo diario, sin horarios nocturnos ni pausas en esta versión.
- Los intervalos que solo se tocan son compatibles; todo el servicio debe caber.
- Citas en UTC; respuesta con fecha completa y zona del negocio.
- Servicio inexistente, inactivo o de otro negocio: 404. Parámetros inválidos: 422.
- Disponibilidad por fecha solicitada; todavía no se filtran horas pasadas.
- Negocio, servicios y horarios se configuran mediante seed o base de datos.
- El ciclo de Appointment se describe en las secciones del día dos.

No se han implementado WhatsApp, Calendar ni dashboard.

## Día 2: crear reservas

`POST /api/v1/appointments` devuelve 201, calcula el fin del servicio y crea una
cita confirmada. Customer se reutiliza por `(business_id, phone)`; una reserva
posterior conserva el nombre del cliente existente. El teléfono debe incluir
prefijo internacional, sin espacios ni guiones, por ejemplo `+523312345678`.

```json
{
  "business_id": 1,
  "service_id": 1,
  "customer": {"name": "Andrea", "phone": "+523312345678"},
  "starts_at": "2026-09-19T11:30:00-06:00"
}
```

- Se exige zona horaria en `starts_at`; se acepta UTC u otro offset y se convierte
  al día local del negocio. Se conservan los inicios cada 30 minutos del día uno.
- Servicio inactivo, horario cerrado, inicio no ofrecido o colisión: 409.
- Negocio/servicio inexistente o servicio de otro negocio: 404.
- Campos controlados por el servidor (`ends_at`, `status`, etc.) se rechazan con 422.
- Estados en la base: mayúsculas, compatibles con día uno. Respuesta API: minúsculas.
- Creación de cliente y cita se confirman en una sola transacción; un rechazo
  no deja clientes ni citas parciales.
- PostgreSQL bloquea la fila del negocio con `FOR UPDATE` hasta finalizar la
  transacción. Las creaciones por este servicio se serializan por negocio y
  vuelven a consultar disponibilidad después del bloqueo. Cualquier futura ruta
  de escritura debe respetar el mismo protocolo; SQL directo no queda protegido
  de solapamientos por este bloqueo.
- La migración 0002 conserva citas antiguas sin cliente (`customer_id` nullable).
  La API exige Customer en toda reserva nueva; no inventa identidades para datos antiguos.

Actualizar el backend local con `docker compose up --build -d` aplica la migración.
Las pruebas PostgreSQL crean y eliminan únicamente esquemas aislados con nombre
aleatorio; requieren permiso de creación de esquemas en la base de pruebas:

```powershell
cd backend
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://booking:booking@localhost:5432/booking'
.venv/Scripts/python.exe -m pytest tests/test_booking.py -q
```

La prueba concurrente envía dos solicitudes al mismo horario y comprueba 201/409
y una sola cita persistida. Sin `TEST_DATABASE_URL`, se omite explícitamente.
Concurrencia de reservas (día dos) e idempotencia de webhooks (día tres) son
garantías distintas; todavía no existe idempotencia para reintentos de creación.

## Día 2: consultar, cancelar y reprogramar

| Endpoint | Resultado |
| --- | --- |
| `GET /api/v1/appointments/{id}` | 200 con la cita, cliente e intervalo en zona local |
| `POST /api/v1/appointments/{id}/cancel` | 200, estado `cancelled`; repetir devuelve 200 |
| `POST /api/v1/appointments/{id}/reschedule` | 200 con el nuevo intervalo y el mismo ID |

Una cita inexistente devuelve 404 en las tres operaciones. La reprogramación
acepta solamente `{"starts_at": "2026-09-19T15:30:00-06:00"}` y recalcula el fin
con la duración actual del servicio. Cancelación no requiere cuerpo.

| Estado actual | Cancelar | Reprogramar |
| --- | --- | --- |
| CONFIRMED | CANCELLED | CONFIRMED |
| CANCELLED | CANCELLED (idempotente) | 409 |
| COMPLETED | 409 | 409 |
| PENDING | 409 | 409 |

Ambas escrituras adquieren el mismo bloqueo de Business usado por CREATE y leen
el estado mutable de la cita después de adquirirlo. Reprogramar excluye únicamente
su propia cita del cálculo interno de disponibilidad; esa exclusión no se expone
en la consulta pública. El mismo horario, o un intervalo que se solape solo con
la propia cita, es válido si cumple las reglas actuales del servicio y negocio.

Un conflicto o validación fallida revierte toda la operación y conserva el
intervalo original. Cancelar libera el horario y reprogramar libera el anterior
y ocupa el nuevo. Las citas antiguas sin Customer se devuelven con `customer: null`.
No se requiere una migración adicional para este checkpoint.

Las pruebas PostgreSQL cubren también reprogramaciones simultáneas al mismo slot,
CREATE contra RESCHEDULE, CANCEL contra RESCHEDULE y conservación de ambas citas
cuando una intenta moverse al horario de otra.
