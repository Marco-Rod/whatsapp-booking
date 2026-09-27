# WhatsApp Booking

WhatsApp Booking permite a negocios de servicios gestionar reservas desde
WhatsApp. El cliente consulta disponibilidad, reserva, cancela o reprograma su
cita; el negocio administra su configuración, agenda e integraciones desde un
dashboard web.

## Estado actual

MVP funcional y desplegado. Incluye el flujo de reservas por WhatsApp,
integración opcional con Google Calendar, recordatorios y onboarding autónomo
para negocios.

## Funcionalidades

- Reservas por WhatsApp mediante conversación guiada.
- Disponibilidad basada en servicios, horarios y citas activas.
- Cancelación y reprogramación de citas.
- Sincronización opcional con Google Calendar.
- Recordatorios por WhatsApp.
- Dashboard de agenda y estado de integraciones.
- Google Admin Sign-In con sesión administrativa.
- Self-service onboarding para configurar un negocio.

Los recordatorios se procesan en una ventana estricta de 10 minutos alrededor
de T−24h. Los fallos permanecen pendientes para reintento hasta el inicio de
la cita; no se envían recordatorios retrospectivos para citas creadas fuera de
esa ventana.

## Flujo del producto

```text
Cliente WhatsApp → Booking Core → PostgreSQL
                         ↓
                 Google Calendar
                         ↓
                    Dashboard
```

## Stack

- **Backend:** Python, FastAPI, SQLAlchemy async, Alembic y PostgreSQL.
- **Frontend:** React, TypeScript y Vite.
- **Infraestructura:** Docker Compose, Caddy, Lightsail y Vercel.
- **Integraciones:** Meta WhatsApp Cloud API, Google Identity y Google Calendar.

## Arquitectura

El backend mantiene las reglas de disponibilidad, reservas, conversaciones,
recordatorios y seguridad. PostgreSQL conserva la información transaccional por
negocio. El frontend ofrece el dashboard y la configuración inicial.

Las integraciones externas se mantienen separadas del núcleo de reservas:
WhatsApp entrega mensajes al gateway, y Calendar refleja las citas sólo cuando
el negocio decide conectarlo.

## Onboarding de un negocio

Después del Google login administrativo, el propietario configura:

```text
Google login
  → Negocio
  → Servicios
  → Horarios
  → Google Calendar (opcional)
  → Finalizar
  → Dashboard
```

Los tres primeros pasos son obligatorios. Google Calendar no bloquea el uso de
WhatsApp Booking ni la finalización del onboarding.

## Desarrollo local

### Docker Compose

Desde la raíz, copia `.env.example` a `.env`, completa sólo las variables que
necesites para las integraciones locales y levanta la API con PostgreSQL:

```powershell
docker compose up --build -d
```

El contenedor de la API aplica `alembic upgrade head` al iniciar.

### Backend

Con PostgreSQL disponible:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### Frontend

En otra terminal:

```powershell
cd frontend
Copy-Item .env.example .env
npm ci
npm run dev
```

Para el flujo de cookies de desarrollo, usa `localhost` de forma consistente
para frontend y backend.

## Variables de entorno

Los archivos `.env.example` enumeran los nombres permitidos; nunca se versionan
valores reales.

- **Base de datos y API:** `DATABASE_URL`, `SLOT_INTERVAL_MINUTES`,
  `CORS_ALLOWED_ORIGINS`, `FRONTEND_URL`.
- **Meta / WhatsApp:** `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN`,
  `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_API_VERSION`, `META_APP_SECRET`.
- **Google:** `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
  `GOOGLE_OAUTH_REDIRECT_URI`, `GOOGLE_IDENTITY_CLIENT_ID`.
- **Seguridad:** `CREDENTIAL_ENCRYPTION_KEY`, `ADMIN_SESSION_SECRET`,
  `ADMIN_SESSION_MAX_AGE_SECONDS`, `ADMIN_SESSION_COOKIE_SECURE`,
  `ADMIN_SESSION_COOKIE_SAMESITE`.
- **Frontend público:** `VITE_API_BASE_URL`, `VITE_GOOGLE_IDENTITY_CLIENT_ID`,
  `VITE_BUSINESS_NAME` y `VITE_BUSINESS_TIMEZONE`.

No coloques secretos en variables `VITE_*`: se incluyen en el bundle del
frontend.

## Migraciones

Las migraciones viven en `backend/alembic`. Para aplicarlas manualmente:

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

## Tests

### Backend

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

### Frontend

```powershell
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

Las pruebas E2E requieren el frontend, la API y PostgreSQL de desarrollo en
ejecución; usan datos de demo y no envían mensajes ni ejecutan OAuth real.

## Producción

La API y PostgreSQL se ejecutan con Docker Compose en Lightsail. Caddy actúa
como reverse proxy HTTPS para la API. El frontend se despliega en Vercel; su
configuración de rewrites permite abrir directamente rutas como `/onboarding`.

Los recordatorios se procesan mediante el comando `process-reminders`,
ejecutado periódicamente por un scheduler externo (cron en el despliegue
actual); no existe un worker Celery persistente.

La configuración de producción vive fuera del repositorio y aporta los secretos
de Meta, Google, cifrado y sesión administrativa.

## Seguridad

- Verificación HMAC SHA-256 de los webhooks de Meta.
- `admin_session` HttpOnly para resolver la identidad administrativa y su
  negocio.
- Google Identity para el inicio de sesión administrativo.
- OAuth de Google Calendar con PKCE, `state` firmado y destinos de retorno
  permitidos.
- Credenciales de Calendar cifradas en reposo.
- Aislamiento por negocio: las operaciones administrativas resuelven el negocio
  desde la sesión y no aceptan un `business_id` controlado por el wizard.

## Limitaciones actuales

- Una agenda por negocio.
- Sin empleados, recursos ni sucursales.
- Sin pagos.
- Google Calendar es opcional y se sincroniza con una sola agenda por negocio.
- El onboarding de Meta/WhatsApp continúa siendo asistido.
- Un fallo de sincronización con Calendar no revierte una reserva confirmada;
  actualmente no existe reconciliación automática posterior.
- El procesamiento de recordatorios depende actualmente de un scheduler externo.

## Demo

Consulta [demo/DEMO.md](demo/DEMO.md) para preparar y recorrer la demostración
con datos ficticios.

## Roadmap

Los siguientes bloques se decidirán a partir del uso real del MVP y de los
primeros pilotos. Las prioridades inmediatas son estabilización operacional,
onboarding de Meta/WhatsApp y reducción de deuda técnica antes de ampliar el
alcance funcional.

El diario técnico de los primeros checkpoints se conserva en
[docs/DEVELOPMENT_HISTORY.md](docs/DEVELOPMENT_HISTORY.md).
