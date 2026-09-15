# Booking Core — Día 1

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
- Appointment es únicamente el soporte de intervalos; crear, cancelar,
  reprogramar y proteger contra reservas simultáneas corresponden al día dos.

No se han implementado WhatsApp, Calendar, dashboard ni Customer.
