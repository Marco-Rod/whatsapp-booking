# EXPERIMENT_001 — WhatsApp Appointment Assistant

**Estado:** Planeado  
**Duración máxima del experimento:** 7 días  
**Versión:** 0.1  
**Mercado inicial:** Salones de belleza, barberías y pequeños negocios de estética  
**Objetivo principal:** Validar disposición real a pagar  
**Tipo de producto inicial:** Servicio productizado / prototipo comercial

---

# 1. Hipótesis

Pequeños negocios que actualmente reciben y administran citas manualmente mediante WhatsApp tienen suficiente fricción operativa como para estar dispuestos a pagar por una solución que permita:

- consultar disponibilidad;
- reservar citas;
- confirmar citas;
- enviar recordatorios;
- cancelar;
- reprogramar;

sin que el propietario tenga que intervenir en cada conversación.

## Hipótesis comercial

> Un salón, barbería o negocio de estética que recibe citas mediante WhatsApp estaría dispuesto a pagar por automatizar una parte significativa del proceso de reservación.

No estamos intentando demostrar todavía que podemos construir un SaaS.

Estamos intentando demostrar que:

> **alguien pagaría por resolver este problema.**

---

# 2. Problema

Actualmente muchos pequeños negocios administran citas mediante conversaciones similares a:

```text
Cliente:
Hola, ¿tienen espacio mañana?

Negocio:
Hola 😊 ¿para qué servicio?

Cliente:
Corte.

Negocio:
Sí, tengo 11:00, 13:00 y 16:30.

Cliente:
A las 13.

Negocio:
Perfecto. ¿A qué nombre?

Cliente:
Andrea.

Negocio:
Listo 😊
```

Posteriormente el negocio debe:

- registrar la cita;
- recordar la cita;
- revisar posibles conflictos;
- responder cancelaciones;
- mover citas;
- mantener actualizado el calendario.

El problema no es técnicamente complejo.

El problema es su **frecuencia**.

---

# 3. Propuesta de valor

## Mensaje comercial principal

> **Tus clientes reservan por WhatsApp aunque tú estés trabajando.**

Alternativa:

> Automatiza tus citas por WhatsApp sin cambiar la forma en que tus clientes te contactan.

El producto no debe venderse como:

> chatbot con FastAPI + WhatsApp Cloud API + Google Calendar.

El cliente compra:

> **menos tiempo respondiendo mensajes y organizando citas.**

---

# 4. Usuario objetivo

## Cliente del producto

Inicialmente:

- barberías;
- salones de belleza;
- estilistas;
- negocios de uñas;
- pestañas;
- cejas;
- maquillaje;
- pequeños spas;
- otros servicios de belleza basados en citas.

## Cliente final

Persona que quiere reservar un servicio mediante WhatsApp.

---

# 5. Alcance del MVP

El MVP deberá permitir únicamente el siguiente flujo:

```text
Cliente
   ↓
WhatsApp
   ↓
Selecciona servicio
   ↓
Selecciona fecha
   ↓
Consulta disponibilidad
   ↓
Selecciona horario
   ↓
Confirma datos
   ↓
Se crea la cita
   ↓
Google Calendar
   ↓
Confirmación por WhatsApp
   ↓
Recordatorio
```

Además:

```text
Cita existente
   ├── confirmar
   ├── cancelar
   └── reprogramar
```

---

# 6. Funcionalidades obligatorias

## 6.1 Servicios

El negocio podrá definir servicios.

Ejemplo:

```text
Corte de cabello
Duración: 45 minutos

Tinte
Duración: 120 minutos

Tratamiento
Duración: 60 minutos
```

Campos mínimos:

- nombre;
- duración;
- activo/inactivo.

---

## 6.2 Horarios del negocio

El negocio podrá indicar sus horarios.

Ejemplo:

```text
Lunes       09:00 - 18:00
Martes      09:00 - 18:00
Miércoles   09:00 - 18:00
Jueves      09:00 - 18:00
Viernes     09:00 - 19:00
Sábado      09:00 - 15:00
Domingo     Cerrado
```

No construiremos inicialmente horarios complejos por empleado.

---

# 7. Reserva

El cliente inicia la conversación.

Ejemplo:

```text
Cliente:
Hola
```

Respuesta:

```text
👋 ¡Hola!

Soy el asistente de reservas de Bella Studio 🌸

¿Qué deseas hacer?

1. Reservar una cita
2. Consultar mi cita
```

Elige:

```text
1
```

Sistema:

```text
¿Qué servicio deseas reservar?

1. Corte
2. Tinte
3. Tratamiento
```

Cliente:

```text
1
```

Sistema:

```text
¿Qué día prefieres?

1. Hoy
2. Mañana
3. Elegir otra fecha
```

Después:

```text
Tenemos disponibles:

1. 10:00
2. 11:30
3. 13:00
4. 16:30
```

Cliente:

```text
2
```

Sistema:

```text
Perfecto 😊

Corte
📅 19 de septiembre
🕐 11:30

¿Confirmamos tu cita?

1. Sí
2. Cambiar horario
```

---

# 8. Confirmación

Al confirmar:

1. verificar nuevamente disponibilidad;
2. crear registro en PostgreSQL;
3. crear evento en Google Calendar;
4. guardar `calendar_event_id`;
5. enviar confirmación.

Respuesta:

```text
✅ Tu cita está confirmada.

✂️ Corte
📅 Sábado 19 de septiembre
🕐 11:30

Te enviaremos un recordatorio antes de tu cita.

¡Nos vemos pronto! 🌸
```

---

# 9. Recordatorios

Versión MVP:

**un recordatorio 24 horas antes.**

Ejemplo:

```text
🌸 Recordatorio de cita

Tu cita es mañana:

✂️ Corte
🕐 11:30

¿Qué deseas hacer?

1. Confirmar
2. Reprogramar
3. Cancelar
```

No implementaremos múltiples campañas de recordatorios.

---

# 10. Cancelación

Cliente:

```text
Cancelar
```

Sistema:

```text
¿Seguro que deseas cancelar?

1. Sí
2. No
```

Al confirmar:

```text
appointment.status = CANCELLED
```

y se actualiza/elimina el evento correspondiente de Calendar.

Respuesta:

```text
Tu cita ha sido cancelada.

Si deseas reservar nuevamente, escribe:

CITA
```

---

# 11. Reprogramación

La reprogramación reutiliza el mismo motor de disponibilidad.

```text
Cita existente
       ↓
Reprogramar
       ↓
Elegir fecha
       ↓
Horarios disponibles
       ↓
Nuevo horario
       ↓
Confirmar
       ↓
Actualizar Calendar
```

No se creará un sistema separado.

---

# 12. Arquitectura

Arquitectura inicial:

```text
                   ┌──────────────────────┐
                   │ WhatsApp Cloud API   │
                   └──────────┬───────────┘
                              │
                           Webhook
                              │
                              ▼
                     ┌─────────────────┐
                     │     FastAPI     │
                     │                 │
                     │ Booking Core    │
                     └───────┬─────────┘
                             │
          ┌──────────────────┼───────────────────┐
          │                  │                   │
          ▼                  ▼                   ▼
    PostgreSQL        Google Calendar       Scheduler
                                                │
                                                ▼
                                          Reminders
                             │
                             ▼
                      React Dashboard
```

---

# 13. Stack

## Backend

- Python 3.12+
- FastAPI
- SQLAlchemy
- Alembic
- Pydantic
- PostgreSQL

## Frontend

- React
- TypeScript

## Integraciones

- WhatsApp Cloud API
- Google Calendar API

## Infraestructura

Durante el prototipo:

- Docker;
- Docker Compose;
- hosting económico;
- HTTPS;
- variables de entorno.

---

# 14. Principio arquitectónico

Aunque comercialmente vendamos:

> Sistema de citas para salones

el código deberá organizarse como:

```text
Booking Core
     +
Business Configuration
```

No:

```text
SalonBookingSystem
```

Queremos poder reutilizar el núcleo posteriormente para:

```text
barbería
salón
uñas
spa
tatuajes
masajes
taller
consultoría
clases
etc.
```

---

# 15. Modelo de datos MVP

## Business

```text
Business
--------
id
name
timezone
phone_number
created_at
updated_at
```

---

## Service

```text
Service
-------
id
business_id
name
duration_minutes
is_active
created_at
updated_at
```

---

## Customer

```text
Customer
--------
id
business_id
phone
name
created_at
updated_at
```

El teléfono será inicialmente nuestro principal identificador del cliente.

---

## BusinessHours

```text
BusinessHours
-------------
id
business_id
weekday
start_time
end_time
is_closed
```

---

## Appointment

```text
Appointment
-----------
id
business_id
customer_id
service_id

starts_at
ends_at

status

calendar_event_id

created_at
updated_at
```

Estados iniciales:

```text
PENDING
CONFIRMED
CANCELLED
COMPLETED
```

---

## Conversation

Para conservar el paso actual del flujo:

```text
Conversation
------------
id
business_id
customer_id

state
context

created_at
updated_at
```

Ejemplo:

```json
{
  "state": "WAITING_FOR_TIME",
  "context": {
    "service_id": 3,
    "date": "2026-09-19"
  }
}
```

---

# 16. Máquina de estados

No utilizaremos IA inicialmente.

La conversación será determinística.

Ejemplo:

```text
START
  ↓
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
BOOKED
```

Otros flujos:

```text
BOOKED
   ├── CANCEL
   └── RESCHEDULE
```

Esto hará que el comportamiento sea:

- predecible;
- testeable;
- barato;
- fácil de depurar.

---

# 17. Booking Core

El Booking Core no debe conocer WhatsApp.

Deberá poder ejecutar operaciones como:

```python
get_available_slots(
    business_id,
    service_id,
    date,
)
```

```python
create_appointment(...)
```

```python
cancel_appointment(...)
```

```python
reschedule_appointment(...)
```

```python
get_customer_appointments(...)
```

Así podremos cambiar posteriormente la interfaz:

```text
WhatsApp
Web
App
Instagram
Telegram
```

sin reescribir las reglas de citas.

---

# 18. Cálculo de disponibilidad

Ejemplo:

Negocio:

```text
09:00 - 18:00
```

Servicio:

```text
60 minutos
```

Citas existentes:

```text
10:00 - 11:00
14:00 - 15:00
```

El sistema deberá generar slots disponibles evitando colisiones.

Regla:

```text
appointment.starts_at < candidate.end
AND
appointment.ends_at > candidate.start
```

Si se cumple:

```text
hay conflicto
```

---

# 19. Protección contra doble reserva

Antes de confirmar cualquier cita:

```text
1. cliente selecciona horario
2. sistema vuelve a consultar disponibilidad
3. comienza transacción
4. valida conflicto
5. crea appointment
6. confirma transacción
```

Nunca confiar únicamente en el horario mostrado previamente.

---

# 20. API inicial

Prefijo:

```text
/api/v1
```

## Services

```http
GET    /services
POST   /services
PATCH  /services/{id}
```

---

## Availability

```http
GET /availability
```

Ejemplo:

```text
GET /availability
    ?service_id=123
    &date=2026-09-19
```

Respuesta:

```json
{
  "date": "2026-09-19",
  "slots": [
    "10:00",
    "11:30",
    "13:00",
    "16:30"
  ]
}
```

---

## Appointments

```http
GET    /appointments
POST   /appointments
GET    /appointments/{id}
POST   /appointments/{id}/cancel
POST   /appointments/{id}/reschedule
```

---

## WhatsApp

```http
GET  /webhooks/whatsapp
POST /webhooks/whatsapp
```

---

# 21. Dashboard

El dashboard NO será un CRM.

Solamente tendrá:

## Pantalla principal

```text
Hoy

09:00  Corte       Laura
10:00  Tinte       Andrea
12:30  Tratamiento Sofia
15:00  Corte       Fernanda
```

---

## Citas

Filtros:

- hoy;
- próximas;
- canceladas.

---

## Servicios

CRUD mínimo:

```text
Servicio
Duración
Activo
```

---

## Horarios

Configuración semanal básica.

Eso es suficiente.

---

# 22. Dashboard — wireframe conceptual

```text
┌───────────────────────────────────────────────┐
│ Bella Studio                         ⚙        │
├───────────────────────────────────────────────┤
│                                               │
│  Hoy · 19 septiembre                         │
│                                               │
│  09:00   Laura     Corte          Confirmada │
│  10:30   Andrea    Tinte          Confirmada │
│  13:00   Sofía     Tratamiento    Confirmada │
│                                               │
│  + Nueva cita                                │
│                                               │
├───────────────────────────────────────────────┤
│ Citas       Servicios       Horarios          │
└───────────────────────────────────────────────┘
```

Debe ser extremadamente simple.

---

# 23. Multi-tenancy

Durante el experimento:

El modelo de datos incluirá:

```text
business_id
```

para facilitar evolución futura.

Sin embargo:

**NO construiremos todavía un sistema SaaS completo multiempresa.**

No habrá:

- registro público;
- onboarding automático;
- planes;
- organizaciones;
- miembros;
- roles avanzados.

Configuraremos inicialmente el negocio manualmente.

---

# 24. Autenticación

Para el dashboard:

implementación mínima.

Un único usuario administrador por negocio es suficiente.

No construir:

```text
owner
manager
employee
receptionist
admin
superadmin
```

durante este experimento.

---

# 25. IA

## NO utilizar IA en v0.1

No necesitamos interpretar:

> “Hola guapa, fíjate que quiero ir como por ahí del martes después de comer para un corte si tienes chance.”

Eso puede llegar después.

Inicialmente utilizaremos menús y respuestas controladas.

Cuando validemos la demanda podremos incorporar:

```text
mensaje libre
      ↓
LLM
      ↓
intent detection
      ↓
Booking Core
```

Pero el Booking Core seguirá siendo determinístico.

---

# 26. Cosas que NO vamos a construir

Durante estos siete días queda explícitamente prohibido implementar:

- pagos;
- Stripe;
- Mercado Pago;
- facturación;
- inventario;
- CRM;
- programa de puntos;
- múltiples sucursales;
- empleados individuales;
- comisiones;
- nómina;
- estadísticas avanzadas;
- campañas masivas;
- marketing automation;
- IA generativa;
- chatbot abierto;
- recomendaciones;
- aplicación móvil;
- PWA;
- integración con Instagram;
- integración con Messenger;
- roles complejos;
- permisos avanzados;
- planes de suscripción;
- billing;
- onboarding self-service;
- white-label;
- marketplace;
- Kafka;
- RabbitMQ;
- microservicios;
- Kubernetes.

Si una función no ayuda directamente a:

```text
reservar
confirmar
recordar
cancelar
reprogramar
```

no pertenece a EXPERIMENT_001.

---

# 27. Criterio de producto

Cada funcionalidad nueva deberá responder:

> ¿Esta funcionalidad es necesaria para demostrar que alguien pagaría por automatizar sus citas?

Si la respuesta es:

```text
No
```

se pospone.

---

# 28. Métricas comerciales

El experimento no termina cuando el software funciona.

Termina cuando intentamos venderlo.

## Meta inicial

Contactar al menos:

```text
20 negocios
```

del mercado objetivo.

Ideal:

```text
30 negocios
```

---

# 29. Señales

## Señal débil

```text
"Está padre."
```

No cuenta.

---

## Señal moderada

```text
"¿Cómo funciona?"
```

Cuenta como interés.

---

## Señal fuerte

```text
"¿Cuánto cuesta?"
```

Muy buena señal.

---

## Señal excelente

```text
"¿Me lo puedes instalar?"
```

---

## Validación definitiva

```text
alguien paga
```

Incluso un pago pequeño vale muchísimo más que 100 likes.

---

# 30. Criterios de éxito

### 🟢 Continuar

Si sucede cualquiera de estos:

- 1 negocio paga;
- 2+ negocios piden instalación;
- 3+ negocios preguntan precio seriamente;
- varias conversaciones muestran claramente el mismo dolor.

Entonces:

> EXPERIMENT_001 pasa a Fase 2.

---

# 31. Criterios de pivot

### 🟡 Modificar

Si encontramos interés pero la necesidad dominante es distinta.

Ejemplo:

```text
"No necesito reservas automáticas,
pero sí recordatorios."
```

Eso podría convertirse en:

```text
WhatsApp Reminder Assistant
```

Otro ejemplo:

```text
"Yo ya tengo agenda,
lo que odio es confirmar citas."
```

Entonces el producto puede reducirse todavía más.

---

# 32. Criterios de abandono

### 🔴 Detener

Si después de:

```text
20-30 contactos relevantes
```

obtenemos:

```text
0 conversaciones serias
0 preguntas de precio
0 solicitudes de demo
```

no invertimos otras tres semanas intentando convencer al mercado.

Archivamos:

```text
EXPERIMENT_001
```

documentamos lo aprendido y pasamos a:

```text
EXPERIMENT_002
WhatsApp Lead Assistant
```

---

# 33. Costos

Durante validación queremos mantener:

```text
Costo de desarrollo:
nuestro tiempo

Infraestructura:
mínima

Publicidad:
$0 inicialmente
```

Primero distribución orgánica/directa.

Solo invertiremos dinero en publicidad si existe señal previa de interés.

---

# 34. Demo comercial

La demo debe comprenderse en máximo:

```text
30-60 segundos
```

Ejemplo:

### Segundo 0

Mensaje:

```text
Hola, quiero una cita
```

### Segundo 10

WhatsApp muestra servicios.

### Segundo 20

Seleccionamos día y hora.

### Segundo 30

Confirmamos.

### Segundo 40

Aparece automáticamente:

```text
Google Calendar
```

### Segundo 50

Mostramos dashboard:

```text
Andrea — Corte — 11:30
```

### Segundo 60

Texto:

> Tus clientes reservan mientras tú trabajas.

Eso será suficiente para publicar.

---

# 35. Estrategia inicial de venta

No ofrecer:

> Software personalizado.

Ofrecer:

> **Sistema de citas automáticas por WhatsApp.**

Una oferta inicial experimental podría estructurarse como:

```text
Instalación
+
mensualidad
```

Ejemplo conceptual:

```text
Configuración inicial
$X

Servicio mensual
$Y
```

Los precios definitivos se determinarán después de hablar con negocios reales.

No fijarlos todavía basándonos únicamente en nuestra intuición.

---

# 36. Estrategia de adquisición

Primeros clientes:

- negocios locales encontrados en Google Maps;
- Instagram;
- Facebook;
- conocidos;
- grupos de emprendedores;
- negocios de belleza;
- contacto directo.

Mensaje de apertura enfocado en investigación:

```text
Hola 👋

Estoy probando una herramienta para negocios que reciben
citas por WhatsApp.

Permite que el cliente consulte horarios, reserve y reciba
recordatorios automáticamente.

Estoy buscando algunos negocios para mostrarles una demo
muy corta y entender si realmente les sería útil.

¿Ustedes actualmente manejan las citas por WhatsApp?
```

No empezar vendiendo agresivamente.

Primero entender el proceso real.

---

# 37. Preguntas para entrevistas

Preguntar:

1. ¿Cómo reciben normalmente sus citas?
2. ¿WhatsApp es el principal medio?
3. ¿Quién responde los mensajes?
4. ¿Cuántos mensajes de citas reciben aproximadamente?
5. ¿Dónde registran las citas?
6. ¿Utilizan agenda física, Calendar o alguna aplicación?
7. ¿Cuánto tiempo creen que gastan respondiendo?
8. ¿Tienen clientes que olvidan su cita?
9. ¿Envían recordatorios?
10. ¿Qué parte del proceso les resulta más molesta?
11. ¿Ya pagan por algún sistema de agenda?
12. ¿Qué tendría que hacer una herramienta para que valiera la pena pagarla?

---

# 38. Información que debemos registrar

Crear posteriormente nuestro:

```text
VALIDATION_LOG.md
```

Campos:

```text
Business
Niche
Contact Date
Current Process
Appointments / Week
Main Pain
Current Tool
Interested?
Asked Price?
Requested Demo?
Would Pay?
Notes
```

---

# 39. Plan de 7 días

## Día 1 — Foundation

Objetivo:

tener funcionando el Booking Core.

### Tareas

- crear repositorio;
- Docker Compose;
- FastAPI;
- PostgreSQL;
- SQLAlchemy;
- Alembic;
- modelos básicos;
- servicios;
- horarios;
- cálculo de disponibilidad;
- tests del motor de slots.

### Resultado

```text
GET /availability
```

funcionando.

---

# 40. Día 2 — Booking

Implementar:

- Customer;
- Appointment;
- creación de cita;
- validación de colisiones;
- cancelación;
- reprogramación;
- tests.

Resultado:

```text
Booking Core funcional
```

independientemente de WhatsApp.

---

# 41. Día 3 — WhatsApp

Implementar:

```text
Webhook verification
Webhook receiver
Send message
Conversation state
```

Flujo mínimo:

```text
WhatsApp
→ servicio
→ fecha
→ horario
→ confirmación
```

Resultado:

cliente puede crear una cita desde WhatsApp.

---

# 42. Día 4 — Calendar

Integrar:

```text
Google Calendar
```

Implementar:

- crear evento;
- modificar evento;
- cancelar evento;
- guardar external event ID.

Resultado:

```text
WhatsApp
→ Booking Core
→ Calendar
```

---

# 43. Día 5 — Reminders + Dashboard

Implementar:

- scheduler;
- recordatorio 24h;
- dashboard React;
- lista de citas;
- CRUD servicios;
- horarios.

No dedicar tiempo excesivo al diseño.

Debe verse:

```text
limpio
creíble
usable
```

no perfecto.

---

# 44. Día 6 — Demo

Preparar un negocio ficticio:

```text
Bella Studio
```

Servicios:

```text
Corte
Tinte
Tratamiento
```

Crear:

- datos demo;
- conversaciones demo;
- landing mínima;
- video 30-60 s;
- screenshots.

---

# 45. Día 7 — Validación

No programar nuevas features.

### Actividades

Contactar negocios.

Publicar demo.

Obtener conversaciones reales.

Registrar feedback.

Nuestro trabajo ese día será:

```text
vender
observar
escuchar
medir
```

no programar.

---

# 46. Regla del Día 7

Si encontramos un bug que destruye la demo:

```text
se arregla
```

Si alguien propone una funcionalidad:

```text
se anota
```

pero:

```text
NO SE IMPLEMENTA
```

durante ese día.

---

# 47. Estructura inicial del repositorio

```text
whatsapp-booking/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   │
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   └── database.py
│   │   │
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── repositories/
│   │   ├── services/
│   │   │   ├── booking/
│   │   │   ├── calendar/
│   │   │   └── whatsapp/
│   │   │
│   │   ├── integrations/
│   │   └── main.py
│   │
│   ├── alembic/
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
│
├── frontend/
│   ├── src/
│   ├── Dockerfile
│   └── package.json
│
├── docs/
│   ├── EXPERIMENT_001.md
│   └── VALIDATION_LOG.md
│
├── docker-compose.yml
├── .env.example
└── README.md
```

---

# 48. Separación de responsabilidades

```text
API
 ↓
Service
 ↓
Repository
 ↓
Database
```

Integraciones externas:

```text
BookingService
       │
       ├── CalendarGateway
       └── WhatsAppGateway
```

El BookingService no debe depender directamente de SDKs externos.

---

# 49. Tests prioritarios

No buscamos cobertura de 100%.

Prioridades:

### Availability

```text
horario libre
conflicto parcial
conflicto total
fuera de horario
duración del servicio
día cerrado
```

### Booking

```text
creación
doble reserva
cancelación
reprogramación
```

### Conversation

```text
transición correcta de estados
input inválido
reinicio
```

---

# 50. Definición de terminado

EXPERIMENT_001 está técnicamente listo cuando una persona puede:

```text
abrir WhatsApp
      ↓
seleccionar servicio
      ↓
seleccionar día
      ↓
seleccionar horario
      ↓
confirmar
      ↓
ver confirmación
```

y automáticamente:

```text
PostgreSQL contiene la cita
Google Calendar contiene el evento
Dashboard muestra la cita
```

y posteriormente:

```text
recibe recordatorio
```

Eso es todo.

---

# 51. North Star

Nuestra métrica más importante durante el experimento NO será:

```text
usuarios registrados
```

ni:

```text
mensajes procesados
```

ni:

```text
líneas de código
```

Será:

> **Cantidad de negocios dispuestos a pagar.**

---

# 52. Filosofía del experimento

No estamos construyendo nuestro próximo gran SaaS.

Estamos comprando información barata.

Cada resultado es válido:

```text
🟢 Sí existe demanda
🟡 El problema era ligeramente diferente
🔴 No existe suficiente interés
```

El único resultado malo sería:

> pasar meses construyendo sin preguntarle al mercado.

---

# 53. Decisión posterior

Al terminar el experimento:

## Si funciona

```text
EXPERIMENT_001
      ↓
PRODUCT_001
```

y comenzamos:

- multiempresa real;
- onboarding;
- empleados;
- pagos;
- configuración;
- analítica;
- IA opcional;
- planes comerciales.

Solo entonces.

---

## Si no funciona

Archivamos.

Reutilizamos:

```text
WhatsApp Gateway
Conversation Engine
Webhook infrastructure
Deployment
Dashboard components
```

y comenzamos:

```text
EXPERIMENT_002

WhatsApp Lead Assistant
```

La inversión técnica no se pierde completamente.

---

# 54. Primera misión

Nuestra primera misión de ingeniería será:

> **Conseguir que el Booking Core pueda decir qué horarios están disponibles para un servicio determinado en una fecha determinada.**

Antes de WhatsApp.

Antes de React.

Antes de Calendar.

Si esa pieza funciona correctamente, tendremos el corazón del producto.

---

# 55. Regla final

Durante los próximos siete días:

> **No optimizamos para construir más. Optimizamos para aprender más rápido.**