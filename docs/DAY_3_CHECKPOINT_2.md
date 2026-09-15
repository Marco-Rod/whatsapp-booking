Ahora sí revisé el diff completo del commit `a39071c`. Son **11 archivos modificados, +976/-27 líneas**, y corresponde exactamente al **Checkpoint 1 del Día 3: Conversation Engine persistente sin Meta**. ([GitHub][1])

## Checkpoint 1 — ✅ APROBADO

Hay varias decisiones particularmente buenas.

La persistencia quedó como queríamos: `Conversation` tiene unicidad por `(business_id, phone)` y `InboundMessage` ya queda preparado con `UNIQUE(business_id, external_message_id)`. Además, usas JSONB en PostgreSQL para `context` y `payload`, manteniendo compatibilidad JSON para otros entornos de prueba. ([GitHub][1])

El flujo ya es realmente persistente:

```text
MAIN_MENU
    ↓
SELECT_SERVICE
    ↓
SELECT_DATE
    ↓
SELECT_TIME
    ↓
CONFIRM_APPOINTMENT
    ↓
BookingService
    ↓
Appointment
    ↓
MAIN_MENU
```

y el estado vive en PostgreSQL, por lo que el `ConversationEngine` puede destruirse y recrearse entre mensajes sin perder la conversación. Eso es exactamente lo que necesitaremos cuando cada mensaje llegue como una request HTTP independiente desde Meta. ([GitHub][1])

### La atomicidad quedó especialmente bien

Esta modificación de `BookingService` fue una muy buena decisión:

```python
create_appointment()
    ↓
abre transaction
    ↓
create_appointment_in_transaction()
```

mientras que `ConversationEngine` puede hacer:

```text
BEGIN

lock Business
     ↓
actualizar Conversation
     ↓
create_appointment_in_transaction()
     ↓
crear Customer
     ↓
crear Appointment
     ↓
reset Conversation

COMMIT
```

Por tanto:

```text
Conversation + Customer + Appointment
              │
              ▼
        TODO O NADA
```

Si algo falla después del `INSERT` de Appointment, también se revierte el cambio de estado conversacional. El propio commit documenta y prueba ese rollback. ([GitHub][1])

Eso es bastante más sólido que simplemente encadenar llamadas a servicios independientes.

### También resolviste dos condiciones de carrera que me preocupaban

La primera es que todos los mensajes toman el mismo `Business lock` que utiliza `BookingService`. La segunda es que **la disponibilidad se vuelve a comprobar al confirmar**, no se confía en los horarios que se mostraron anteriormente. ([GitHub][1])

Por tanto:

```text
Cliente A ve 11:30
Cliente B ve 11:30

A confirma
   ↓
Appointment 11:30

B confirma
   ↓
recalcula availability
   ↓
11:30 ya ocupado
   ↓
"No está disponible"
   ↓
nuevos horarios
```

Exactamente el comportamiento que necesitamos.

## Un detalle que quiero conservar

Guardar en `context`:

```json
{
  "service_id": 3,
  "date": "2026-09-19",
  "starts": [
    "2026-09-19T10:00:00-06:00",
    "2026-09-19T10:30:00-06:00"
  ]
}
```

en lugar de volver a generar arbitrariamente las opciones es correcto.

Así la opción:

```text
2 → 10:30
```

sigue representando **exactamente lo que vio el usuario**, aunque mientras tanto cambie el catálogo o la disponibilidad. Y al confirmar hacemos nuevamente la validación real. ([GitHub][1])

---

# Una observación antes de conectar Meta

Encontré una cosa que **no considero blocker**, pero sí quiero que anotemos.

Ahora estamos bloqueando `Business` durante **todo mensaje conversacional**, incluso algo como:

```text
Usuario A → "1"
Usuario B → "2"
Usuario C → "1"
```

Eso serializa conversaciones independientes del mismo negocio. ([GitHub][1])

Para:

```text
salón pequeño
10-50 conversaciones/día
```

es irrelevante y además simplifica enormemente nuestra consistencia.

Pero si algún día tenemos cientos/miles de mensajes concurrentes deberíamos pasar aproximadamente a:

```text
Conversation lock
      +
Resource/Calendar lock
```

en vez de:

```text
Business lock para todo
```

**No lo cambiaría ahora.**

Es exactamente el tipo de optimización prematura que decidimos evitar.

---

# Checkpoint 2 — ahora sí conectamos WhatsApp

Ahora aparece una frontera nueva:

```text
                 NUESTRO SISTEMA

WhatsApp ──→ Webhook ──→ InboundMessage
                            │
                       deduplicación
                            │
                            ▼
                    ConversationEngine
                            │
                            ▼
                       Booking Core
                            │
                            ▼
                       PostgreSQL
                            │
                            ▼
                     WhatsAppClient
                            │
                            ▼
                        Cliente
```

Aquí tenemos **cuatro responsabilidades** nuevas y nada más:

1. verificar webhook;
2. parsear mensajes;
3. deduplicar `message_id`;
4. enviar respuestas.

No vamos a modificar el Conversation Engine para que “entienda WhatsApp”.

---

## La idempotencia ahora sí es crítica

El commit incluso documenta correctamente que todavía no existe: un texto repetido después de confirmar sería interpretado como un nuevo mensaje porque el estado ya volvió a `MAIN_MENU`. ([GitHub][1])

`InboundMessage` ahora resolverá eso.

Queremos:

```text
Meta
 │
 │ wamid.123
 ▼
Webhook
 │
 ▼
INSERT InboundMessage
 │
 ├── nuevo ──────────→ procesar
 │
 └── ya existe ──────→ 200 OK
```

Y el test estrella será:

```text
POST webhook
message_id = wamid.123
text = "1"

POST webhook
message_id = wamid.123
text = "1"

                ↓

ConversationEngine.handle_message()
ejecutado exactamente UNA vez
```

Después llevaremos esto hasta el escenario peligroso:

```text
CONFIRM_APPOINTMENT

wamid.XYZ → "1"
wamid.XYZ → "1" retry

           ↓

Appointment COUNT = 1
```

Ese es el test realmente importante.

---

## Estructura que implementaría ahora

```text
app/
├── api/v1/
│   └── whatsapp.py
│
├── integrations/
│   └── whatsapp/
│       ├── client.py
│       ├── parser.py
│       └── schemas.py
│
├── repositories/
│   └── inbound_messages.py
│
└── services/
    └── whatsapp/
        └── webhook.py
```

Y mantendría el router extremadamente delgado:

```text
GET /webhooks/whatsapp
        ↓
verify

POST /webhooks/whatsapp
        ↓
WebhookService.process()
```

No:

```text
router
 ├── parsear Meta
 ├── consultar DB
 ├── manejar conversación
 ├── crear citas
 └── llamar Graph API
```

---

## Configuración

Añadimos únicamente:

```text
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_API_VERSION=
```

y nunca imprimimos `ACCESS_TOKEN` en logs.

También separaría desde ahora:

```python
WhatsAppClient.send_text(...)
```

del procesamiento del webhook.

Eso nos permitirá mockear completamente Meta en tests.

---

# Objetivo del siguiente commit

No necesitamos todavía probarlo desde tu teléfono.

Quiero primero que el siguiente commit demuestre:

```text
GET webhook verification             ✅

POST webhook                          ✅
      ↓
parse Meta payload                    ✅
      ↓
extract message_id                    ✅
extract phone                         ✅
extract text                          ✅
      ↓
InboundMessage                        ✅
      ↓
deduplicate                           ✅
      ↓
ConversationEngine                    ✅
      ↓
WhatsAppClient.send_text              ✅
```

Todo con `WhatsAppClient` mockeado.

Después hacemos **Checkpoint 3**, configuramos Meta/WhatsApp Cloud API y probamos desde un teléfono real.

Ahí sí tendremos el momento divertido:

```text
📱 "Hola"
     ↓
☁️ Meta
     ↓
⚡ FastAPI
     ↓
🧠 ConversationEngine
     ↓
📅 Booking Core
     ↓
🐘 PostgreSQL
     ↓
☁️ Meta
     ↓
📱 "¿Qué servicio deseas reservar?"
```

Si completamos esa conversación hasta `Appointment CONFIRMED`, podremos declarar **Día 3 ✅ DONE** y pasar al Día 4 con Google Calendar.

Así que este commit está aprobado; **no tocaría más el Conversation Engine salvo que los tests de integración con WhatsApp descubran un bug.** ([GitHub][1])

[1]: https://github.com/Marco-Rod/whatsapp-booking/commit/a39071ca04eb36063d01fefc5a5d892e7cebb184 "Add persistent conversation engine with atomic booking confirmation · Marco-Rod/whatsapp-booking@a39071c · GitHub"
