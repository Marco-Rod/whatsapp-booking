Ahora sí. El commit `e938f7f` está visible y corresponde exactamente al **Checkpoint 1 del Día 2**. Revisé el diff y son **11 archivos modificados, +915/-3 líneas**. ([GitHub][1])

## Veredicto: Checkpoint 1 ✅

La implementación está bastante alineada con lo que definimos.

**Customer quedó bien modelado.** Tienes `UNIQUE(business_id, phone)`, relaciones `Business → Customer → Appointment`, y la migración `0002` mantiene `customer_id` nullable para no romper las citas creadas durante el Día 1. Las reservas nuevas, sin embargo, sí pasan obligatoriamente por Customer. Esa es una migración compatible y sensata para esta etapa. ([GitHub][1])

El `POST /api/v1/appointments` también tiene una frontera limpia:

```text
Router
  ↓
BookingService
  ├── BookingRepository
  ├── CustomerRepository
  └── AvailabilityService
```

El request no permite que el cliente controle `ends_at`, `status`, etc.; `starts_at` exige timezone; el servidor calcula el final usando el slot válido; y el teléfono usa un formato internacional razonablemente estricto. ([GitHub][1])

### La parte más importante: concurrencia

Aquí sí hiciste lo que queríamos.

```python
select(Business)
    .where(Business.id == business_id)
    .with_for_update()
```

y todo ocurre dentro de:

```python
async with self.session.begin():
```

Por tanto:

```text
Request A ──┐
            ├── lock Business
Request B ──┘        │
                     ▼
               A verifica slot
                     │
               A crea reserva
                     │
                  COMMIT
                     │
                     ▼
               B obtiene lock
                     │
               B recalcula
               availability
                     │
                 11:30 ❌
                     │
                409 Conflict
```

Eso explica el resultado documentado de la prueba PostgreSQL:

```text
Request A → 201
Request B → 409

appointments persistidas → 1
```

Además, la comprobación de disponibilidad ocurre **después de adquirir el lock**, que es el detalle fundamental. ([GitHub][1])

## Una observación arquitectónica importante

El locking actual es correcto para nuestro modelo:

> **una agenda por Business.**

Pero serializa **todas las escrituras de reservas de un negocio**.

Por ejemplo:

```text
Reserva 09:00 ─┐
Reserva 12:00 ─┼── mismo Business lock
Reserva 17:00 ─┘
```

Aunque no compitan por el mismo horario.

Para un salón pequeño esto es completamente aceptable y, de hecho, prefiero esta solución ahora porque es fácil de razonar y difícil de romper.

Cuando eventualmente tengamos:

```text
Business
   ├── Employee A
   ├── Employee B
   ├── Employee C
   └── Employee D
```

probablemente el lock deberá moverse hacia la **agenda/recurso**, no al negocio entero.

Pero eso es un problema futuro. **No lo cambiaría ahora.**

También está muy bien que hayas documentado la limitación: SQL directo u otra futura ruta de escritura que ignore este protocolo podría saltarse esta protección. ([GitHub][1])

---

# Checkpoint 2 — terminemos el Día 2

Ahora sí atacaría **Cancel + Reschedule**. Ya no necesitamos tocar Customer ni la creación salvo que aparezca un bug.

Añadiremos:

```http
GET  /api/v1/appointments/{id}

POST /api/v1/appointments/{id}/cancel

POST /api/v1/appointments/{id}/reschedule
```

El corazón será:

```text
                    Appointment
                         │
             ┌───────────┴───────────┐
             ▼                       ▼
          CANCEL                  RESCHEDULE
             │                       │
             ▼                       ▼
        CANCELLED              validar nuevo slot
             │                       │
             ▼                       ▼
       libera horario          actualizar intervalo
```

### Cancelación

Quiero que sea **idempotente a nivel de dominio**.

Primera llamada:

```text
CONFIRMED → CANCELLED
200 OK
```

Segunda llamada:

```text
CANCELLED → CANCELLED
200 OK
```

No veo valor en devolver `409` porque un eventual retry de WhatsApp no debería convertir una operación que ya consiguió su objetivo en un error.

Esto nos prepara muy bien para el Día 3.

Y el test fundamental será:

```python
create(11_30)

assert 11_30 not in availability

cancel()

assert 11_30 in availability
```

### Reprogramación

Request:

```http
POST /api/v1/appointments/42/reschedule
```

```json
{
  "starts_at": "2026-09-19T15:30:00-06:00"
}
```

Debe adquirir **el mismo Business lock** antes de verificar el nuevo slot.

Pero aparece una sutileza.

Actualmente `AvailabilityService` verá la cita que estamos reprogramando como ocupada. Por tanto necesitamos permitir:

```python
exclude_appointment_id=appointment.id
```

Conceptualmente:

```text
Andrea
11:30–12:30

reprogramar → 11:30

Availability normal:
11:30 ❌ porque existe Andrea

Availability para reschedule:
ignorar Appointment #42
11:30 ✅
```

Esto también permitirá que reprogramar al mismo horario sea una operación válida.

### Estados

Definamos desde ahora estas reglas:

```text
CONFIRMED
   ├── cancel      → CANCELLED
   └── reschedule  → CONFIRMED

CANCELLED
   ├── cancel      → CANCELLED
   └── reschedule  → ❌ 409

COMPLETED
   ├── cancel      → ❌ 409
   └── reschedule  → ❌ 409
```

`PENDING` podemos dejarlo fuera del ciclo HTTP por ahora.

---

## Definition of Done del Día 2

Después del siguiente commit quiero comprobar solamente estas cinco propiedades:

```text
CREATE
  ✓ crea Customer/cita
  ✓ evita double booking concurrente

CANCEL
  ✓ cambia estado
  ✓ libera slot

RESCHEDULE
  ✓ mueve intervalo
  ✓ libera slot anterior
  ✓ ocupa slot nuevo
  ✓ evita conflicto concurrente
```

Y particularmente quiero otro test PostgreSQL:

```text
Appointment A → 11:30
Appointment B → 15:30

A intenta moverse a 15:30
          ↓
        409

A sigue → 11:30
B sigue → 15:30
```

Esto comprueba algo importante: **una reprogramación fallida no debe modificar parcialmente la cita original.**

Si cerramos eso, yo sí declararía:

> **DÍA 2 — BOOKING LIFECYCLE ✅ DONE**

Y entonces el Día 3 cambia completamente el proyecto, porque por primera vez dejaremos de hablarle nosotros directamente al Booking Core y empezará a hablarle **WhatsApp mediante webhooks y una máquina de estados conversacional**. Ahí el experimento empezará a parecerse al producto que queremos vender. ([GitHub][1])

[1]: https://github.com/Marco-Rod/whatsapp-booking/commit/e938f7f3f4340a918dcb333602ef401763b87db4 "Customer, relaciones y migración aplicados. · Marco-Rod/whatsapp-booking@e938f7f · GitHub"
