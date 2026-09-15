Perfecto. **Día 1 comienza por el corazón del producto, no por WhatsApp.** Hoy queremos terminar pudiendo preguntarle al backend: *“Para este servicio, en esta fecha, ¿qué horarios puedo ofrecer?”*

### Día 1 — objetivo

Al terminar debemos tener esta cadena funcionando:

```text
FastAPI
   ↓
PostgreSQL
   ↓
Business + Service + BusinessHours + Appointment
   ↓
AvailabilityService
   ↓
GET /api/v1/availability
   ↓
Tests ✓
```

Yo usaría **Python 3.12 + FastAPI + SQLAlchemy 2 async + asyncpg + PostgreSQL + Alembic + Pydantic v2 + pytest**. Mantendremos arquitectura modular, pero sin sobrearquitectura.

### Paso 1 — Crear el proyecto

```bash
mkdir whatsapp-booking
cd whatsapp-booking

mkdir backend
cd backend

python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
# source .venv/bin/activate

pip install fastapi uvicorn sqlalchemy asyncpg alembic \
    pydantic-settings psycopg2-binary \
    pytest pytest-asyncio httpx
```

Y crea inicialmente:

```text
whatsapp-booking/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   ├── core/
│   │   ├── models/
│   │   ├── repositories/
│   │   ├── schemas/
│   │   ├── services/
│   │   │   └── booking/
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── docs/
│   └── EXPERIMENT_001.md
├── docker-compose.yml
├── .env
├── .env.example
└── .gitignore
```

Para **Día 1**, no crearía todavía `frontend/`, `whatsapp/` ni `calendar/`. No los necesitamos.

### Paso 2 — Primera decisión importante del modelo

Aunque nuestro primer cliente conceptual sea `Bella Studio`, **no debemos hardcodear nada relacionado con salones**.

Nuestra unidad será:

```text
Business
   │
   ├── Service
   ├── BusinessHours
   └── Appointment
```

Y aquí haría una pequeña mejora respecto al documento original: `Appointment` debe tener sus propios `starts_at` y `ends_at`, y la disponibilidad debe calcularse usando **intervalos reales**, no simplemente una lista de horas ocupadas.

Supongamos:

```text
Negocio:
09:00 ───────────────────────── 18:00

Servicio solicitado:
60 min

Citas existentes:

       10:00────11:00
                    13:30────────15:30
```

Nuestro motor deberá ser capaz de generar:

```json
{
  "business_id": 1,
  "service_id": 1,
  "date": "2026-09-19",
  "timezone": "America/Mexico_City",
  "slots": [
    {"starts_at": "09:00", "ends_at": "10:00"},
    {"starts_at": "11:00", "ends_at": "12:00"},
    {"starts_at": "12:00", "ends_at": "13:00"},
    {"starts_at": "15:30", "ends_at": "16:30"},
    {"starts_at": "16:30", "ends_at": "17:30"}
  ]
}
```

Hay una decisión que debemos tomar desde ahora: **granularidad**.

Yo propongo:

```python
SLOT_INTERVAL_MINUTES = 30
```

Eso significa que un servicio de 60 minutos puede comenzar a:

```text
09:00
09:30
10:00
10:30
...
```

siempre que sus 60 minutos completos estén disponibles.

No confundiremos:

```text
duración del servicio = 60 min
```

con:

```text
intervalo entre posibles inicios = 30 min
```

Esa separación será importante después.

### Paso 3 — Los primeros modelos

Hoy implementaremos solamente:

```text
Business
Service
BusinessHours
Appointment
```

`Customer` puede esperar hasta mañana porque **no es necesario para calcular disponibilidad**.

Y pondría desde ya una regla importante:

```text
Todo datetime almacenado en PostgreSQL
              ↓
             UTC

Business.timezone
              ↓
     America/Mexico_City

Disponibilidad
              ↓
    timezone del negocio
```

Eso nos ahorrará muchos problemas cuando eventualmente un negocio esté en Guadalajara y otro en Bogotá.

### Paso 4 — El algoritmo que realmente importa

Nuestro `AvailabilityService` conceptualmente hará:

```python
async def get_available_slots(
    business_id: int,
    service_id: int,
    target_date: date,
) -> list[AvailableSlot]:
    ...
```

Internamente:

```text
1. obtener Business
2. obtener Service
3. obtener BusinessHours para weekday
4. si está cerrado → []
5. construir apertura/cierre
6. obtener appointments activos del día
7. generar candidatos cada 30 minutos
8. calcular candidate_end
9. descartar si candidate_end > closing_time
10. comprobar colisiones
11. devolver candidatos válidos
```

La regla de colisión será:

```python
candidate_start < appointment_end \
and candidate_end > appointment_start
```

Esto captura correctamente solapamientos parciales y completos.

Por ejemplo:

```text
Cita:
10:00 ─────────── 11:00

09:30 ─────────── 10:30   ❌
10:00 ─────────── 11:00   ❌
10:30 ─────────── 11:30   ❌
11:00 ─────────── 12:00   ✅
```

Fíjate en el último caso: `11:00` es válido porque los intervalos **se tocan pero no se solapan**.

### Paso 5 — Endpoint objetivo

Solo necesitamos inicialmente:

```http
GET /api/v1/availability?business_id=1&service_id=1&date=2026-09-19
```

Con algo parecido a:

```json
{
  "date": "2026-09-19",
  "service": {
    "id": 1,
    "name": "Corte",
    "duration_minutes": 60
  },
  "slots": [
    {
      "starts_at": "2026-09-19T09:00:00-06:00",
      "ends_at": "2026-09-19T10:00:00-06:00"
    },
    {
      "starts_at": "2026-09-19T11:00:00-06:00",
      "ends_at": "2026-09-19T12:00:00-06:00"
    }
  ]
}
```

Prefiero devolver timestamps completos en la API. Después WhatsApp podrá convertirlos a:

> **11:00 AM**

pero el Booking Core conserva información temporal inequívoca.

### Paso 6 — Definition of Done de hoy

No avanzaremos a WhatsApp hasta que pasen como mínimo estos casos:

| Caso                                | Esperado          |
| ----------------------------------- | ----------------- |
| Día normal sin citas                | slots disponibles |
| Día cerrado                         | `[]`              |
| Servicio inexistente                | `404`             |
| Negocio inexistente                 | `404`             |
| Cita exactamente sobre un slot      | excluido          |
| Solapamiento al inicio              | excluido          |
| Solapamiento al final               | excluido          |
| Cita termina al iniciar slot        | permitido         |
| Servicio termina después del cierre | excluido          |
| Cita cancelada                      | no bloquea        |
| Diferentes duraciones               | slots correctos   |

Y añadiría desde ahora un caso especialmente importante:

```text
Horario:
09:00 ─────────────── 18:00

Servicio:
120 minutos

último inicio posible:
16:00 ✅

16:30 ❌
17:00 ❌
```

Eso evita uno de esos bugs que parecen obvios hasta que aparecen en producción.

---

Te propongo que lo hagamos como hemos estado trabajando el ETL de **Deck at the Plate**: **implementamos Día 1 juntos por pequeños checkpoints y probamos cada uno antes de continuar**, en lugar de que te arroje 25 archivos de código de golpe.

**Checkpoint 1:** crea `whatsapp-booking`, el entorno virtual y la estructura inicial anterior. Una vez ahí, seguimos inmediatamente con `docker-compose.yml`, PostgreSQL y la configuración async de SQLAlchemy.
