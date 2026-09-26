# Booking Core — Día 3, checkpoint 2.5: firma del webhook

## Día 6, checkpoint 1: preparar la demo

Guion, prerrequisitos y datos ficticios de Bella Studio en [demo/DEMO.md](demo/DEMO.md).
Con dependencias y migraciones instaladas, desde la raíz:

```powershell
python scripts/seed_demo.py --date today
python scripts/seed_demo.py --date 2026-09-18
```

Usa el Python del backend. El seed es idempotente por fecha, conserva los datos
existentes y no envía mensajes ni crea eventos de Calendar.

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

La conexión real con Meta, Calendar y dashboard siguen pendientes.

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

## Día 3: conversación sin Meta

La migración `0003` añade Conversation (una por negocio/teléfono) e InboundMessage
con `UNIQUE(business_id, external_message_id)`. Context y payload usan JSONB en
PostgreSQL. InboundMessage queda preparado, sin procesamiento de webhooks todavía.

```python
from app.core.database import Session
from app.services.conversation.engine import ConversationEngine

async with Session() as session:
    result = await ConversationEngine(session).handle_message(
        business_id=1, phone="+523312345678", text="hola")
    print(result.messages)
```

Cada llamada posee una transacción y requiere una sesión sin transacción activa.
El engine no depende de HTTP ni de Meta. Puede recrearse entre mensajes porque
el estado reside en PostgreSQL.

- Flujo: menú → servicio → hoy/mañana/pasado mañana → horario → confirmación.
- Los días se calculan en la zona del negocio; los horarios vienen de AvailabilityService.
  La conversación descarta horarios pasados, también al confirmar.
- El contexto conserva IDs, fechas y listas de inicios ISO para mantener la
  correspondencia de las opciones numéricas mostradas; nunca objetos ORM completos.
- Una entrada inválida conserva estado y contexto y repite las opciones.
- `CANCELAR` limpia el flujo en cualquier estado; no cancela citas existentes.
  Responder `2` en confirmación también descarta el flujo.
- El catálogo vacío vuelve al menú; un día sin horarios permite elegir otro día.
  Si alguien ocupa el horario antes de confirmar, el motor vuelve a ofrecer disponibilidad.
- Una confirmación exitosa crea una cita real, limpia contexto y vuelve al menú.
- El flujo no solicita nombre: para clientes nuevos se usa el teléfono como nombre
  provisional. Si el cliente existe, se conserva su nombre.
- Todas las transiciones toman el mismo bloqueo de Business que BookingService.
  La confirmación utiliza `create_appointment_in_transaction`, que no confirma una
  transacción propia. Cita, Customer y Conversation se guardan o revierten juntos.
- Esto no implementa idempotencia de mensajes. Un texto repetido después de confirmar
  se interpreta en el nuevo estado; el futuro gateway deberá deduplicar por message_id.

Prueba del checkpoint contra PostgreSQL (esquemas temporales aislados):

```powershell
cd backend
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://booking:booking@localhost:5432/booking'
.venv/Scripts/python.exe -m pytest tests/test_conversation_engine.py -q
```

Incluye el flujo completo con Appointment persistida, continuidad entre sesiones,
inputs inválidos, zona horaria, aislamiento, horario ocupado, confirmaciones
concurrentes y un fallo simulado después del INSERT para verificar rollback.
La integración del siguiente checkpoint se describe a continuación.

## Día 3, checkpoint 2: gateway probado sin Meta real

Endpoints:

- `GET /api/v1/webhooks/whatsapp`: verifica `hub.mode=subscribe` y
  `hub.verify_token`; devuelve `hub.challenge` como texto (200), o 403 si no coincide.
- `POST /api/v1/webhooks/whatsapp`: parsea todos los mensajes de texto del lote,
  deduplica, llama al engine y envía sus respuestas mediante WhatsAppClient.
  Devuelve 200 también para duplicados, estados de entrega y formatos no textuales
  ignorados. Un texto mal formado devuelve 400.

Las cuatro variables de `.env.example` se pasan al contenedor por Compose:
`WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` y
`WHATSAPP_API_VERSION`. Se dejan vacías; la versión Graph deberá elegirse en la
configuración real de Meta. El cliente utiliza Bearer Auth y `POST /{version}/{phone_number_id}/messages`.

El `phone_number_id` recibido debe coincidir con el configurado. El
`metadata.display_phone_number` se normaliza a formato internacional y debe
coincidir con exactamente un `Business.phone_number` (guardado como `+5233...`).
Un número sin negocio configurado, o un mapeo ambiguo, devuelve 503. No se asume
`business_id=1`. Los eventos de otros números de WhatsApp se ignoran.

### Transacciones y reintentos

1. Bajo el bloqueo de Business, se consulta/crea InboundMessage por la clave única
   `(business_id, external_message_id)`.
2. El engine participa en la transacción mediante `handle_message_in_transaction`.
   InboundMessage, Conversation, Customer y Appointment se confirman juntos.
3. `processed_at` indica que el procesamiento de negocio terminó. `payload`
   conserva un mensaje normalizado, las respuestas y `sent_count`. No contiene
   headers ni tokens de acceso; sí contiene teléfono/texto del cliente.
4. Después del commit se envían las respuestas. Un bloqueo de InboundMessage
   serializa entregas concurrentes del mismo mensaje, sin retener el bloqueo de
   Business durante la llamada de red. Cada respuesta aceptada actualiza el contador.
5. Si el envío falla, POST devuelve 503. El retry envía solo las respuestas pendientes,
   sin reprocesar el mensaje ni recrear la cita. Si todo fue entregado, devuelve 200
   sin volver a llamar al engine ni al cliente.

No se añade infraestructura de colas: las respuestas pendientes se guardan en el
JSONB existente. Un fallo de proceso después de que Meta acepte un envío pero antes
de confirmar el contador puede repetir ese texto en un retry; la operación de negocio
permanece deduplicada. La entrega de texto exactamente una vez no está garantizada.

### Verificación del checkpoint

```powershell
cd backend
.venv/Scripts/python.exe -m pytest tests/test_whatsapp.py -q
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://booking:booking@localhost:5432/booking'
.venv/Scripts/python.exe -m pytest tests/test_whatsapp.py -q
```

El cliente está mockeado en las pruebas HTTP. La prueba del adaptador Graph utiliza
`httpx.MockTransport`; no se envían mensajes reales. Se verifican el handshake,
parseo de lotes, números, ignorados, duplicados, confirmación repetida/concurrente,
rollback completo, fallos de envío y recuperación parcial.

Referencias de contrato: [payloads oficiales de Meta](https://www.postman.com/meta/whatsapp-business-platform/folder/tduohwq/webhook-payload-reference)
y [API de mensajes](https://www.postman.com/meta/whatsapp-business-platform/folder/o48mro7/messages).

### Checkpoint 2.5: autenticación del POST

`META_APP_SECRET` se configura como secreto en `.env` y se pasa al contenedor por
Compose. Es el App Secret de Meta, distinto del access token y del verify token.
No se incluye ningún valor real en el repositorio.

Antes de parsear JSON, el POST calcula HMAC SHA-256 sobre los bytes originales de
la petición y valida `X-Hub-Signature-256: sha256=<digest hexadecimal>` mediante
comparación en tiempo constante. No se reserializa el JSON para verificarlo.

- Firma correcta: continúa el procesamiento normal.
- Firma ausente, mal formada, incorrecta o cuerpo modificado: 403, sin procesar.
- `META_APP_SECRET` vacío: 503, sin procesar (fail closed).
- Firma válida con JSON inválido: 400.

Las pruebas del gateway firman sus requests. `tests/test_whatsapp_signature.py`
prueba además que un rechazo no invoca WebhookService, incluso con JSON inválido.
La verificación GET conserva su contrato y utiliza `WHATSAPP_VERIFY_TOKEN`.

Antes del checkpoint 3 faltan configurar los secretos reales, el número receptor
y una URL HTTPS, y probar recepción/envío desde un teléfono. No se ha configurado
una URL pública ni realizado envíos reales.
