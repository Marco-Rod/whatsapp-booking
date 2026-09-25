# Recordatorios de citas por WhatsApp

## Objetivo

WhatsApp Booking puede enviar un recordatorio automático al cliente antes de
una cita confirmada.

El objetivo es ayudar a reducir olvidos y ausencias sin enviar mensajes
innecesarios o repetitivos al cliente.

## Política actual

### Un recordatorio por cita

Cada cita puede generar como máximo un recordatorio automático para su horario
actual.

El horario objetivo del recordatorio es:

> 24 horas antes del inicio de la cita.

Por ejemplo:

- Cita: viernes 10:00.
- Recordatorio objetivo: jueves 10:00.

El sistema procesa periódicamente los recordatorios pendientes. El primer
intento de envío puede ocurrir hasta 10 minutos después del horario objetivo.

### Reservas realizadas con menos de 24 horas de anticipación

Si un cliente reserva cuando ya pasó el momento en que habría correspondido
enviar el recordatorio de 24 horas, el sistema **no envía un recordatorio
inmediatamente**.

En estos casos, la confirmación de la reserva enviada por WhatsApp se considera
suficiente.

Ejemplo:

- Reserva realizada: jueves 17:27.
- Cita: viernes 09:00.
- Momento ideal del recordatorio: jueves 09:00.

Como la reserva se realizó después del momento ideal, no se envía un
recordatorio adicional.

Esto evita que el cliente reciba una confirmación y, pocos minutos después,
otro mensaje recordándole una cita que acaba de reservar.

### Reservas con mucha anticipación

Una cita puede reservarse con varios días o semanas de anticipación.

El sistema no envía el recordatorio al momento de reservarla. Esperará hasta
aproximadamente 24 horas antes de la cita.

### Citas canceladas

Las citas canceladas no reciben recordatorios.

### Reintentos

Si ocurre un problema temporal al intentar enviar un recordatorio por WhatsApp,
el sistema puede volver a intentarlo mientras la cita siga siendo válida y
todavía no haya comenzado.

Los reintentos no generan recordatorios adicionales intencionalmente.

## Google Calendar

Los recordatorios de WhatsApp son independientes de Google Calendar.

Un negocio puede utilizar WhatsApp Booking sin conectar Google Calendar.

Si Google Calendar está conectado, sirve como apoyo para la agenda del negocio,
pero no controla los recordatorios enviados por WhatsApp a los clientes.

## Filosofía

Los recordatorios están diseñados para ser útiles y no intrusivos.

La política actual prioriza:

- un solo recordatorio;
- evitar mensajes inmediatamente después de reservar;
- no enviar recordatorios para citas canceladas;
- no depender de Google Calendar;
- evitar mensajes repetitivos al cliente.

## Configuración futura

En futuras versiones se podrá evaluar que cada negocio configure opciones como:

- activar o desactivar los recordatorios;
- elegir cuánto tiempo antes de la cita enviarlos;
- definir horarios en los que no deben enviarse mensajes;
- definir el comportamiento para reservas realizadas con poca anticipación.

Estas opciones no forman parte todavía de la política actual.

## Implementación y operación

`ReminderService(session).find_due(now)` recibe una fecha con zona horaria y
trabaja internamente en UTC. La creación de un reminder nuevo ocurre únicamente
durante esta ventana:

```text
scheduled_for = appointment.starts_at - 24 horas
scheduled_for <= now < scheduled_for + 10 minutos
```

La ventana de 10 minutos tolera el retraso de un ciclo del scheduler que se
ejecuta cada cinco minutos. No es una ventana de catch-up general: si no existe
un reminder al terminar esos 10 minutos, un ciclo posterior no lo crea.

Una vez creado, un reminder pendiente puede devolverse después de la ventana
hasta que sea enviado o comience la cita. Esta separación permite reintentar
fallos reconocidos de WhatsApp sin habilitar recordatorios inmediatos para
reservas tardías.

La restricción única `(appointment_id, scheduled_for)` y el insert tolerante a
conflictos evitan filas duplicadas, incluso con descubrimientos concurrentes en
PostgreSQL. Reprogramar cambia la clave de horario; los registros anteriores se
conservan como historial y no se usan para el horario nuevo.

`ReminderProcessor` reclama cada fila con `claim_token` mediante una actualización
condicional. Después vuelve a comprobar la cita, el cliente, el servicio, el
negocio, el estado `CONFIRMED` y el horario esperado. Ninguna transacción de base
de datos permanece abierta durante la llamada externa a WhatsApp.

`sent_at` se guarda sólo cuando el proveedor reconoce el envío. Esto representa
aceptación de la API, no confirmación de entrega o lectura en el teléfono.

Un fallo reconocido libera el claim y mantiene `sent_at` vacío para permitir un
reintento. Una interrupción o fallo de base de datos después de un resultado
externo ambiguo conserva el claim para reconciliación manual; no existe expiración
automática porque un reintento ciego podría duplicar un mensaje aceptado por Meta.

### Ejecución programada

El comando oficial procesa un ciclo y termina:

```powershell
cd backend
process-reminders
```

También puede ejecutarse como:

```powershell
python -m app.commands.process_reminders
```

`--appointment-id ID` limita una ejecución diagnóstica a una cita. Sin ese
argumento procesa todos los reminders pendientes elegibles.

El scheduler externo debe ejecutar el comando aproximadamente cada cinco
minutos. FastAPI no instala ni ejecuta un cron interno.

Ejemplo para Linux, sustituyendo la ruta:

```cron
*/5 * * * * cd /srv/whatsapp-booking/backend && /srv/whatsapp-booking/backend/.venv/bin/process-reminders
```

No deben incluirse secretos en el comando. El proceso necesita su configuración
de base de datos y WhatsApp mediante el entorno privado del servidor.

Los códigos de salida son:

- `0`: ciclo terminado sin fallos de envío, incluida una cola vacía;
- `1`: ciclo terminado con al menos un fallo recuperable;
- `2`: error fatal de configuración, base de datos o ejecución;
- `130`: proceso interrumpido por el operador.

El adaptador actual envía texto libre. Fuera de la ventana de atención al cliente
de WhatsApp será necesaria una plantilla aprobada. Los números de teléfono se
envían con el formato configurado; no se reescriben automáticamente.

La tabla `appointment_reminders` fue incorporada por la migración `0005`; la
migración `0006` añadió `claim_token` para coordinar workers concurrentes.
