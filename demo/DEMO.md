# Bella Studio · Demo de 2–3 minutos

**Tus clientes reservan por WhatsApp. Tu agenda se organiza automáticamente.**

Este checkpoint prepara una agenda ficticia y el recorrido. La landing y el
despliegue se realizan después, en el checkpoint de infraestructura.

## Preparación local

Necesitas PostgreSQL disponible, dependencias de `backend/pyproject.toml`, las
migraciones hasta `0006`, y el dashboard React. Usa preferentemente una base de
demo aislada. El script usa `DATABASE_URL` del entorno o del `.env` existente;
no cambia archivos de configuración, secretos, teléfonos del negocio ni Calendar.

La secuencia completa en Windows, sin activar el entorno, es:

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
cd ..
.\backend\.venv\Scripts\python.exe scripts/seed_demo.py --date today
# O una fecha concreta:
.\backend\.venv\Scripts\python.exe scripts/seed_demo.py --date 2026-09-18
```

Con el entorno activo basta `python scripts/seed_demo.py`; `--date` omite por
defecto `today`, calculado en `America/Mexico_City`.

El script imprime `VITE_BUSINESS_ID`. Configura ese ID en `frontend/.env`, con
`VITE_BUSINESS_NAME=Bella Studio`, `VITE_BUSINESS_TIMEZONE=America/Mexico_City` y
`VITE_API_BASE_URL=http://127.0.0.1:8000`. No asumas que el ID es 1. Arranca:

```powershell
# Terminal 1, desde backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# Terminal 2, desde frontend
npm ci
npm run dev
```

Abre http://127.0.0.1:5173 y selecciona la fecha del seed en la agenda.

| Hora local | Servicio | Cliente ficticia | Estado |
| --- | --- | --- | --- |
| 09:00 | Corte | Mariana | Confirmada |
| 10:30 | Manicure | Sofía | Confirmada |
| 12:00 | Peinado | Daniela | Confirmada |
| 15:00 | Corte | Andrea | Cancelada |
| 17:00 | Manicure | Fernanda | Confirmada |

Los tres servicios duran 60 minutos. En una base nueva se abre de 09:00 a 18:00
los siete días para permitir grabar cualquier fecha. Se conservan horarios y
servicios existentes: si son incompatibles, el seed falla y revierte todo.
Quedan huecos, por ejemplo 13:30–14:30 o 16:00–17:00, para la reserva en vivo.

## Repetición y aislamiento

- Repetir una fecha conserva las cinco citas y sus IDs; no duplica negocio,
  servicios ni clientes. Otra fecha agrega su propia agenda.
- No borra ni renombra citas anteriores, incluidos datos de desarrollo. Si ya
  existen otras citas, el total puede superar cinco. Para una grabación limpia,
  utiliza una base de demo nueva y migrada; no vacíes la base habitual.
- Conserva cancelaciones y cambios hechos después del seed. No es un comando
  de reset. Si reprogramas una cita ficticia a otro día, al preparar de nuevo
  el día original puede agregarse una cita para ese día.
- Los contactos usan identificadores `demo:bella:*`, no números de teléfono.
  El runner los excluye y el cliente WhatsApp rechaza su envío antes de acceder
  a la red. No se crean recordatorios enviados ni eventos Calendar ficticios.
- Las ejecuciones PostgreSQL se serializan; un conflicto de horario con una
  cita existente revierte toda la ejecución sin alterar esa cita.

## Prerrequisitos para grabar el recorrido real

1. Usa hoy, mañana o pasado mañana: son las fechas ofrecidas por la conversación.
   Elige un hueco futuro disponible; después de las 17:00 conviene preparar mañana.
2. El número receptor de Meta debe estar asociado al mismo negocio que muestra el
   dashboard, con webhook HTTPS y firma configurados. Esta vinculación se prepara
   por separado: el seed no cambia números existentes ni lee credenciales externas.
3. Configura el Calendar del negocio y su autorización según
   [calendar-create.md](../docs/calendar-create.md). Una reserva nueva debe crear
   su evento real; las cinco citas del seed aparecen sin vincular.
4. Prepara antes un recordatorio recibido en un teléfono de prueba propio, siguiendo
   [reminders.md](../docs/reminders.md), con envío limitado a esa cita. No uses
   contactos reales de clientes. Mantén esa cita en otro día para conservar el
   inicio de cinco citas. No ejecutes el runner global en una base con clientes
   reales como parte de este ensayo.
5. La conversación no solicita nombre: un cliente nuevo aparece como «Sin nombre»
   en el dashboard. No prometas captura de nombre. Evita mostrar teléfonos, tokens,
   consolas o información personal al grabar WhatsApp y Calendar.

## Guion

| Tiempo | Acción y narración |
| --- | --- |
| 0:00–0:15 | Dashboard en la fecha preparada: «Bella Studio tiene cinco citas: cuatro confirmadas y una cancelada». |
| 0:15–0:50 | En WhatsApp escribe «Hola». Sigue las opciones reales: Reservar cita → Corte → fecha preparada → hora libre → Confirmar. Lee las opciones; sus números pueden cambiar. |
| 0:50–1:00 | Muestra la respuesta real de cita confirmada. |
| 1:00–1:20 | Recarga el dashboard; selecciona de nuevo la fecha si era mañana. Muestra el paso de cinco a seis citas y la nueva reserva. La pantalla se actualiza al recargar, no en tiempo real. |
| 1:20–1:40 | Abre Google Calendar en esa fecha y comprueba el servicio y la misma hora local. |
| 1:40–2:00 | Muestra el recordatorio real preparado: «Este mensaje se recibió previamente; se programa unas 24 horas antes». No atribuyas el mensaje a la reserva recién creada. |
| 2:00–2:20 | Vuelve a la agenda: «Reservas por WhatsApp, agenda, Google Calendar y recordatorios. Tus clientes reservan por WhatsApp. Tu agenda se organiza automáticamente». |

Si falla Calendar o no hay recordatorio real, corrige la integración antes de
grabar esa parte. «Calendar vinculado» indica una asociación guardada; no verifica
que un evento siga activo. «Recordatorio enviado» puede corresponder al historial.

## Criterios de cierre

- [ ] Seed ejecutado dos veces sin duplicados; fecha y zona correctas.
- [ ] Agenda inicial de cinco citas en una base limpia, con nombres ficticios.
- [ ] Reserva real adicional visible al recargar y evento real en Calendar.
- [ ] Recordatorio real preparado y guion ensayado en menos de tres minutos.

La preparación de datos puede verificarse sin Meta. Las tres últimas integraciones
del recorrido solo se dan por verificadas después del ensayo real. El Checkpoint 2
revisará costos vigentes y créditos antes de elegir alojamiento para React, FastAPI,
PostgreSQL y `process-reminders`.
