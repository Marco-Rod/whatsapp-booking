Vamos con el **Día 3 — WhatsApp + Conversation Engine**. Aquí conviene mantener la misma disciplina: primero hacemos que la conversación funcione perfectamente sin depender de Meta y solo después conectamos WhatsApp.

## Checkpoint 1 — Conversation Engine

Hoy empezaría agregando dos entidades:

```text
Conversation
────────────
id
business_id
phone
state
context JSONB
created_at
updated_at
```

y:

```text
InboundMessage
──────────────
id
business_id
external_message_id
phone
payload JSONB
processed_at
created_at

UNIQUE(business_id, external_message_id)
```

`InboundMessage` será nuestra barrera de idempotencia cuando conectemos Meta. Aunque todavía no lo utilicemos en este checkpoint, prefiero que la migración del Día 3 deje preparado el modelo.

Para `Conversation.state`, mantendría una máquina pequeña:

```python
class ConversationState(str, Enum):
    MAIN_MENU = "main_menu"
    SELECT_SERVICE = "select_service"
    SELECT_DATE = "select_date"
    SELECT_TIME = "select_time"
    CONFIRM_APPOINTMENT = "confirm_appointment"
```

No necesitamos `BOOKED` como estado persistente. Una vez creada la cita podemos limpiar el contexto y regresar a `MAIN_MENU`.

El `context` irá acumulando únicamente IDs/valores necesarios:

```json
{
  "service_id": 3,
  "date": "2026-09-19",
  "starts_at": "2026-09-19T11:30:00-06:00"
}
```

No guardaría ahí objetos completos.

## La pieza central

Crearía algo como:

```text
app/services/conversation/
├── engine.py
├── states.py
├── messages.py
└── result.py
```

con una interfaz deliberadamente independiente de WhatsApp:

```python
result = await conversation_engine.handle_message(
    business_id=1,
    phone="+523312345678",
    text="1",
)
```

y devolvería algo como:

```python
ConversationResult(
    messages=[
        "¿Qué servicio deseas reservar?\n\n"
        "1. Corte\n"
        "2. Tinte\n"
        "3. Tratamiento"
    ]
)
```

La regla arquitectónica será:

```text
WhatsApp ──┐
           │
Tests ─────┼──→ ConversationEngine
           │           │
Future UI ─┘           ├── AvailabilityService
                       └── BookingService
```

**ConversationEngine no debe conocer HTTP ni la estructura de los webhooks de Meta.**

## Flujo completo del Checkpoint 1

Un test deberá poder simular esto sin WhatsApp:

```text
handle("hola")
      ↓
¿Qué deseas hacer?
1. Reservar cita

handle("1")
      ↓
¿Qué servicio?
1. Corte
2. Tinte

handle("1")
      ↓
¿Qué día?
1. Hoy
2. Mañana
3. Otra fecha

handle("2")
      ↓
Horarios disponibles:
1. 10:00
2. 11:30
3. 13:00

handle("2")
      ↓
Corte
Mañana
11:30

¿Confirmar?
1. Sí
2. No

handle("1")
      ↓
BookingService.create_appointment()

      ↓

✅ Tu cita está confirmada.
```

Y al final debemos comprobar directamente PostgreSQL:

```text
Appointment
────────────
customer = teléfono usado
service = Corte
starts_at = horario seleccionado
status = confirmed
```

Eso será nuestro primer **conversation integration test**.

### Fechas

Aquí no quiero introducir parsing libre todavía.

Para el MVP:

```text
¿Qué día prefieres?

1. Hoy
2. Mañana
3. Pasado mañana
```

Con eso tenemos tres días suficientes para la demo.

`Otra fecha` puede quedar fuera del primer checkpoint. Después podremos introducir listas, date picker interactivo de WhatsApp o lenguaje natural.

### Input inválido

No debemos resetear la conversación por cualquier error.

Por ejemplo:

```text
SELECT_SERVICE

Usuario:
"8"

Sistema:
No reconocí esa opción.

¿Qué servicio deseas reservar?

1. Corte
2. Tinte
3. Tratamiento
```

El estado sigue siendo:

```text
SELECT_SERVICE
```

Lo mismo para horario, fecha y confirmación.

Y agregaría desde ahora una salida universal:

```text
CANCELAR
```

que haga:

```text
cualquier estado
      ↓
limpiar context
      ↓
MAIN_MENU
```

Esto nos dará una forma muy sencilla de recuperar conversaciones atascadas.

---

## Checkpoint 2 — WhatsApp Gateway

Cuando el engine pase sus tests, conectamos Meta.

Necesitaremos:

```text
app/integrations/whatsapp/
├── client.py
├── parser.py
└── schemas.py
```

y:

```http
GET  /api/v1/webhooks/whatsapp
POST /api/v1/webhooks/whatsapp
```

El `GET` será exclusivamente para la verificación del webhook.

El `POST` hará:

```text
Meta
 │
 ▼
Webhook
 │
 ├─ extraer message_id
 ├─ extraer phone
 ├─ extraer text
 │
 ▼
Idempotency
 │
 ▼
ConversationEngine
 │
 ▼
WhatsAppClient.send_message()
```

Nada de lógica de reservas dentro del router.

### Idempotencia

Aquí usaremos `InboundMessage`.

Supongamos que Meta entrega:

```text
wamid.ABC123
```

Primera vez:

```text
INSERT inbound_message
        ↓
procesar
        ↓
crear cita
        ↓
200
```

Retry:

```text
INSERT inbound_message
        ↓
UNIQUE violation / ya existe
        ↓
NO procesar nuevamente
        ↓
200
```

Especialmente importante:

```text
Meta retry
    ↓
NO segunda Appointment
NO segundo cambio de Conversation
NO segunda operación de negocio
```

Y **seguimos devolviendo `200`**, porque queremos indicar al proveedor que el evento ya está atendido.

## Configuración

Prepararía `.env.example` con nombres como:

```text
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_API_VERSION=
```

Nada de tokens hardcodeados ni payloads completos con secretos en logs.

---

# Checkpoint 3 — End-to-end

Aquí juntamos todo.

La prueba manual del Día 3 será literalmente sacar el teléfono.

```text
Tú
 │
 │ "Hola"
 ▼
WhatsApp
 │
 ▼
Meta
 │
 ▼
POST /webhooks/whatsapp
 │
 ▼
ConversationEngine
 │
 │
 ├── ServiceRepository
 ├── AvailabilityService
 └── BookingService
          │
          ▼
      PostgreSQL
```

Y la conversación deberá terminar en algo parecido a:

```text
🌸 Tu cita está confirmada.

✂️ Corte
📅 Martes 15 de septiembre
🕐 11:30 AM

¡Nos vemos pronto!
```

Mientras que:

```http
GET /api/v1/appointments/{id}
```

debe mostrar exactamente esa cita.

Todavía **NO Google Calendar**. Eso corresponde al Día 4.

---

## Definition of Done — Día 3

Para cerrar el día quiero poder comprobar:

| Comportamiento              | Resultado                       |
| --------------------------- | ------------------------------- |
| Primera conversación        | crea `Conversation`             |
| Conversación existente      | continúa estado                 |
| Servicio inválido           | permanece en estado             |
| Fecha                       | calcula fecha correcta          |
| Slots                       | provienen del Booking Core real |
| Slot inválido               | no avanza                       |
| Confirmar                   | crea Appointment                |
| Cancelar flujo              | vuelve al menú                  |
| Context después de reservar | limpio                          |
| Webhook verification        | funciona                        |
| Webhook entrante            | parseado                        |
| `message_id` repetido       | no reprocesado                  |
| Envío WhatsApp              | funciona                        |
| Reserva desde teléfono      | funciona                        |
| Retry                       | nunca crea doble cita           |

Y mantengamos fuera:

```text
❌ IA
❌ lenguaje natural
❌ Calendar
❌ reminders
❌ React
❌ Redis
❌ Celery
❌ botones sofisticados
❌ imágenes
❌ pagos
```

### Empecemos por este commit

No conectaría Meta todavía. El siguiente incremento que quiero ver en el repo es exclusivamente:

```text
0003_conversations.py

Conversation
InboundMessage

ConversationRepository
ConversationState
ConversationEngine

tests/
  test_conversation_engine.py
```

Con un test estrella:

```text
"hola"
  → "1"
  → servicio
  → mañana
  → horario
  → confirmar
       ↓
Appointment real
```

Cuando eso esté verde, me pasas el commit y revisamos especialmente **transiciones, manejo del contexto y atomicidad entre `ConversationEngine` y `BookingService`** antes de abrir nuestro backend a los webhooks de Meta.

Ese checkpoint nos permite detectar errores en la parte conversacional sin tener que preguntarnos todavía si el problema viene de nuestro código o de WhatsApp.
