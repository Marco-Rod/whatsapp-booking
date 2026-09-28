# WhatsApp Multi-Tenant & Meta Embedded Signup

> Documento técnico vivo. Actualizado: 2026-09-28.
>
> No contiene valores de producción, tokens, secretos, teléfonos, IDs de
> activos Meta, códigos de autorización ni direcciones de red.

## 1. Objetivo

WhatsApp Booking evoluciona de una integración legacy single-business a una
plataforma multi-tenant donde cada `Business` posee su propia conexión;
inbound se enruta por ella, outbound usa sus credenciales, ningún tenant puede
usar credenciales de otro y los nuevos negocios podrán conectar WhatsApp con
Meta Embedded Signup. Los tokens no viven en frontend, el frontend no decide
arbitrariamente `business_id` y las migraciones mantienen compatibilidad
operacional segura.

## 2. Arquitectura objetivo

```text
Meta WhatsApp
    ↓
Webhook global autenticado
    ↓
phone_number_id
    ↓
WhatsAppConnection persistida
    ↓
Business → Conversation Engine → WhatsAppSender
    ↓                              ↓
    └──── credenciales cifradas de WhatsAppConnection ────→ Meta Graph API
```

```text
Administrador autenticado
    ↓
BusinessUser.business_id
    ↓
Meta Embedded Signup
    ↓
Authorization code + candidate asset IDs
    ↓
Verificación backend server-to-server
    ↓
Credenciales cifradas → WhatsAppConnection
```

## 3. Principios de seguridad

- El tenant se deriva de `admin_session` y `BusinessUser`.
- El frontend nunca aporta un `business_id` autoritativo para reclamar activos.
- HMAC del webhook se valida antes de procesar payloads.
- `phone_number_id` persistido es la identidad inbound; display phone number no
  decide el negocio.
- Tokens se cifran at-rest y App Secret queda sólo server-side.
- Authorization code se intercambia server-to-server.
- Tokens, codes y secretos no se incluyen en logs.
- Conexiones unknown/inactive fallan cerrado.
- Nunca hay fallback global cross-tenant.

## 4. Evolución A0–A5

### A0 — Architecture audit

**Estado:** completed (`documentation/research`).

El diagnóstico identificó routing y envío dependientes de configuración global.
Se decidió migrar por modelo persistido, inbound, outbound, backfill explícito
y retiro del bridge runtime.

### A1 — WhatsAppConnection

**Estado:** completed.  
**Commit:** `c1973119ffc6869726a811d83090b44e6ebb3f1b`.

Introdujo `WhatsAppConnection` por `Business`, unicidad por negocio y por
`phone_number_id`, token cifrado y resolvers credential-free para inbound.
Sólo una conexión `connected` se convierte en credencial utilizable.

### A2 — Inbound routing

**Estado:** completed.  
**Commit:** `b120f02`.

El webhook resolvió primero `phone_number_id → WhatsAppConnection →
business_id`; una conexión persistida tenía prioridad sobre el bridge temporal.
Las conexiones inactivas bloqueaban el fallback.

### A3 — Outbound sender

**Estado:** completed.  
**Commit:** `9267443e5f171908ed595e515f685fc2d9196f1d`.

Se añadió `send_for_business`: el sender resuelve la conexión del negocio y
construye el cliente Meta con credenciales explícitas. Recordatorios conservan
`appointment.business_id` hasta el sender.

### A4 — Legacy business migration

**Estado:** completed.  
**Backfill commit:** `0f9e91aea67035bef556f49bd59287b8b458ec34`.

El comando de backfill exige `--business-id`, admite dry-run, es idempotente,
no hace upserts destructivos, cifra mediante `CredentialCipher` y no imprime
secretos. Producción aplicó Alembic `0012`, creó una conexión persistida
`connected` y validó E2E real inbound/outbound. No se documentan activos ni
credenciales empleados.

### A5 — Remove legacy runtime bridge

**Estado:** completed.  
**Commit:** `ad47be1ee5d45a7f0a98a0539c3c887ae1de3640`.

Se retiraron fallback inbound por `Business.phone_number` y fallback outbound
por credenciales globales. `WhatsAppClient` recibe credenciales explícitas y
reminders envían por Business/conexión persistida. El E2E productivo posterior
al deploy confirmó webhook `200` y respuesta real. `process-reminders` terminó
con `sent=0 failed=0`: valida runtime, no un envío de reminder.

## 5. A6 — Meta Embedded Signup

### A6.0 — Research

**Estado:** completed (`documentation/research`).

**VERIFIED:** Meta mantiene Embedded Signup como vía de onboarding de clientes
de un partner y comunicó en 2026 la evolución del modelo hacia WAAC/PMA.

**INFERENCE:** el resultado del navegador es sólo candidato; backend debe
ligar un intento temporal a la sesión, verificar Meta server-to-server y
persistir activos verificados.

**UNKNOWN:** no se infirieron de ejemplos antiguos el exchange, lifecycle de
token, coexistence, subscriptions ni permisos; la documentación técnica no
estuvo disponible durante la investigación inicial.

### A6.1 — Meta Console Readiness

**Estado:** completed (`console verification`, sin commit de implementación).

Lo siguiente fue observado directamente en la consola actual de Meta:

- modalidad Independent Tech Provider;
- Business Verification para onboarding externo;
- App Review / Access Verification;
- Embedded Signup con Facebook Login for Business y Facebook JavaScript SDK;
- SDK/Graph observado `v26.0`, Embedded Signup `v4` y
  `sessionInfoVersion: 3`;
- dominios HTTPS autorizados y configuración de login propia; su ID no se
  documenta;
- customer permissions `whatsapp_business_management` y
  `whatsapp_business_messaging`;
- la UI indica configuración/token sin expiración;
- authorization code con `response_type=code` y
  `override_default_response_type=true`;
- session information por `postMessage` / `WA_EMBEDDED_SIGNUP` con candidate
  account/WABA ID y `phone_number_id`;
- validación requerida de `event.origin`;
- authorization code al backend, exchange server-to-server, suscripción de la
  app a la cuenta WhatsApp y registro Cloud API del teléfono;
- Hosted Embedded Signup disponible;
- ejemplo OAuth observado usa Graph `v25.0`.

La diferencia OAuth `v25.0` versus SDK/API `v26.0` no autoriza a unificarlas
por suposición. El token provider/admin mostrado incluye `business_management`,
`whatsapp_business_management` y `whatsapp_business_messaging`; no debe
confundirse sin evidencia con el token customer-specific persistido en
`WhatsAppConnection`.

## 6. Contrato Embedded Signup observado

Pseudocódigo sanitizado:

```javascript
FB.login(callback, {
  config_id: "<META_CONFIG_ID>",
  response_type: "code",
  override_default_response_type: true,
  extras: { version: "v4" },
})
```

```javascript
window.addEventListener("message", event => {
  validateFacebookOrigin(event.origin)
  parseEmbeddedSignupEvent(event.data) // WA_EMBEDDED_SIGNUP
  obtainCandidateAccountAndPhoneNumberIds()
})
```

Los asset IDs y code recibidos por navegador son candidatos: backend los
verifica antes de crear/modificar una conexión.

## 7. Modelo actual

`WhatsAppConnection` contiene `business_id`, `waba_id`, `phone_number_id`,
`encrypted_access_token`, `granted_scopes`, `token_expires_at`, `status` y
timestamps.

No hay cambio de schema justificado para A6. WAAC/PMA sigue siendo una
preocupación de compatibilidad; no se añadirán campos especulativos hasta que
la API verificada los requiera.

## 8. A6.2 proposed design

**Estado:** planned.

La frontera backend propuesta precede todo exchange Meta real:

```text
EmbeddedSignupAttempt
  id, business_id, opaque nonce/state, expires_at, consumed_at, created_at

POST /admin/whatsapp/embedded-signup/start
POST /admin/whatsapp/embedded-signup/complete
```

`complete` recibe authorization code y candidate account/phone number IDs,
pero nunca un `business_id` autoritativo. El negocio procede de sesión
administrativa. El snippet observado no demuestra un round-trip OAuth `state`
tradicional, por lo que no se debe inventar ese comportamiento.

## 9. Remaining external requirements

- Business Verification.
- App Review y Access Verification.
- Aprobación de usuarios externos en producción.
- Lifecycle/revocación de token por validar.
- Responsabilidades exactas provider-token vs. customer-token.
- Compatibilidad WAAC/PMA mientras Meta evoluciona.

## 10. Deployment / operational status

El runtime productivo usa exclusivamente `WhatsAppConnection` persistida.
Después de A5, globals legacy no se consumen para routing ni envío. La
configuración histórica de backfill sigue disponible durante la ventana de
rollback/recuperación. Este documento no expone valores de producción.

## 11. Phase / commit ledger

| Phase | Status | Commit | Purpose | Production validated |
| --- | --- | --- | --- | --- |
| A0 | completed | documentation/research | Architecture audit | n/a |
| A1 | completed | `c1973119ffc6869726a811d83090b44e6ebb3f1b` | Per-business model | yes |
| A2 | completed | `b120f02` | Persisted inbound routing | yes |
| A3 | completed | `9267443e5f171908ed595e515f685fc2d9196f1d` | Per-business sender | yes |
| A4 | completed | `0f9e91aea67035bef556f49bd59287b8b458ec34` | Explicit backfill | yes |
| A5 | completed | `ad47be1ee5d45a7f0a98a0539c3c887ae1de3640` | Remove runtime bridge | yes |
| A6.0 | completed | documentation/research | Flow research | n/a |
| A6.1 | completed | console verification | Meta Console Readiness | n/a |
| A6.2 | planned | planned | Backend security boundary | no |

## 12. Updating this document

Cada commit de WhatsApp multi-tenant o Embedded Signup debe actualizar este
documento con fase, fecha, hash, cambio arquitectónico, implicaciones de
seguridad, migraciones/configuración, pruebas, validación productiva,
limitaciones y siguiente checkpoint.

Nunca documentar access tokens, app secrets, webhook verify tokens, session
secrets, credenciales de base de datos, teléfonos, WABA IDs, phone number IDs,
configuration IDs, authorization codes ni IPs.
