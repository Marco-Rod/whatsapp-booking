# Dashboard de Bella Studio

React + TypeScript + Vite, CSS normal. Pantalla de solo lectura que consume el
contrato autenticado de `GET /api/v1/admin/dashboard?date=YYYY-MM-DD`.
La identidad del negocio se resuelve exclusivamente desde `admin_session`.

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
El nombre y timezone inicial del negocio se configuran en `.env` porque este
contrato no incluye el nombre del negocio. Las horas se muestran usando el
timezone devuelto por la API. Reinicia Vite al cambiar `.env`.

FastAPI permite por defecto GET desde localhost:5173 y 127.0.0.1:5173.
`CORS_ALLOWED_ORIGINS` en el entorno del backend permite sustituir esa lista
(array JSON). CORS no sustituye autenticación; este checkpoint es local.

## Verificación

```powershell
npm run build
npx playwright install chromium
npm run test:e2e
```

Las pruebas de navegador usan fixtures deterministas y mockean las rutas
administrativas; no requieren citas reales, no modifican datos ni envían
mensajes. Solamente se simula un fallo de red para comprobar Reintentar.

URLs alternativas: `DASHBOARD_UI_URL` y `DASHBOARD_API_URL`.
Las capturas desktop y móvil se guardan en `docs/screenshots/`.

`calendar_synced` se muestra como «Calendar vinculado»: la API indica que existe
un ID asociado, incluso si la cita está cancelada. `reminder_sent` conserva la
semántica de la API: existe algún recordatorio enviado, incluido el histórico.
No se muestran teléfonos, IDs externos ni controles para modificar reservas.
