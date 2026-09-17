# Dashboard de Bella Studio

React + TypeScript + Vite, CSS normal. Pantalla de solo lectura que consume el
contrato real de `GET /api/v1/businesses/{id}/dashboard?date=YYYY-MM-DD`.

## Desarrollo (PowerShell)

Con PostgreSQL y el backend configurados, desde `backend/`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

En otra terminal, desde `frontend/`:

```powershell
Copy-Item .env.example .env
npm ci
npm run dev
```

Abre http://127.0.0.1:5173. `VITE_API_BASE_URL` es el origen del backend, sin
`/api/v1`; todas las variables VITE son públicas, no pongas secretos en ellas.
El ID, nombre y timezone inicial del negocio se configuran en `.env` porque
este contrato no incluye el nombre del negocio. Las horas se muestran usando
el timezone devuelto por la API. Reinicia Vite al cambiar `.env`.

FastAPI permite por defecto GET desde localhost:5173 y 127.0.0.1:5173.
`CORS_ALLOWED_ORIGINS` en el entorno del backend permite sustituir esa lista
(array JSON). CORS no sustituye autenticación; este checkpoint es local.

## Verificación

```powershell
npm run build
npx playwright install chromium
npm run test:e2e
```

Las tres pruebas de navegador requieren ambos servidores y la BD de desarrollo
con las citas reales de Bella Studio. No crean ni modifican citas ni envían
mensajes. Usan el 17/09/2026 (citas confirmadas y recordatorios enviados) y el
18/09/2026 (cita cancelada vinculada a Calendar); el día 01/01/2040 debe estar vacío.
Solamente se simula un fallo de red para comprobar Reintentar: la recuperación
y las capturas consultan la API real, sin JSON mock.

URLs alternativas: `DASHBOARD_UI_URL` y `DASHBOARD_API_URL`.
Las capturas desktop y móvil se guardan en `docs/screenshots/`.

`calendar_synced` se muestra como «Calendar vinculado»: la API indica que existe
un ID asociado, incluso si la cita está cancelada. `reminder_sent` conserva la
semántica de la API: existe algún recordatorio enviado, incluido el histórico.
No se muestran teléfonos, IDs externos ni controles para modificar reservas.
