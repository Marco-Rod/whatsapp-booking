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

## 8. A6.2 — Backend security boundary

**Estado:** completed.
**Commit:** `161a1b8b4f86bc759ec207e3fb66c9e25a6d4ac8`.
**Migración:** `0013_embedded_signup_attempts` (aditiva; aún no aplicada en
producción).

La frontera backend precede todo exchange Meta real:

```text
EmbeddedSignupAttempt
  id, business_id, nonce_hash, expires_at, consumed_at, created_at

POST /admin/whatsapp/embedded-signup/start
POST /admin/whatsapp/embedded-signup/complete
```

`start` requiere `admin_session`, deriva `business_id` del administrador y
devuelve una vez un nonce criptográficamente aleatorio. El servidor guarda
solamente su hash SHA-256, asociado al negocio, con TTL configurable (600 s
por defecto). El nonce es una correlación interna de aplicación; no afirma
ser ni reemplaza un OAuth `state` de Meta.

`complete` exige la misma sesión administrativa y recibe nonce,
authorization code y los IDs candidatos de cuenta y teléfono. Nunca acepta
un `business_id` autoritativo. La fila se consume con un `UPDATE` condicional
atómico: otro negocio, intento expirado, nonce desconocido o replay se
rechazan; dos solicitudes concurrentes sólo pueden obtener un éxito. No se
llama a Meta, no se intercambia ni persiste el code y no se crea/modifica
`WhatsAppConnection` en esta fase.

La cobertura A6.2 comprueba inicio autenticado, aislamiento Business A/B,
hash en reposo, expiración, replay, consumo concurrente, validación de
payload y rechazo temprano de body sobredimensionado sin adquirir sesión de
base de datos. Las regresiones A1–A5 continúan verificando que el runtime de
WhatsApp no usa globals legacy.

El body de `complete` está limitado a 16 KiB tanto en Caddy como mediante
lectura streaming en FastAPI. `413` y desconexiones ocurren antes de sesión
de base de datos; los errores estructurales siguen usando `422`. Los detalles
de validación no reflejan el authorization code.

Los intentos expirados o consumidos conservan por ahora sólo metadatos no
secretos para trazabilidad de la fase; no existe aún un scheduler de purga.
El TTL se aplica en la autorización y la retención/purga acotada se decidirá
antes de habilitar onboarding externo masivo.

### A6.3A — Processing leases

**Estado:** completed.
**Commit:** `68504d8e62653edcf9a081310fbe3364a550ae93`.
**Migración:** `0014_embedded_signup_processing_leases` (aditiva; aún no
aplicada en producción).

Los intentos usan tres estados persistidos:

```text
READY ── acquire ──► PROCESSING ── finalize_success ──► CONSUMED
  ▲                       │
  └──── release seguro ───┘
                          │
                    lease expira
                          │
                          └──► reacquirible si expires_at sigue vigente
```

`PROCESSING` contiene inicio, expiración y hash SHA-256 de una lease token
interna. El token no sale por API ni se persiste en claro. `acquire` usa un
`UPDATE` condicional y termina su transacción antes de cualquier I/O externo.
`finalize_success` y `release` exigen negocio, lease válida, lease vigente,
TTL global vigente y estado `processing`; un worker obsoleto no puede
finalizar ni liberar una lease recuperada.

A6.3B compondrá la persistencia de `WhatsAppConnection` y
`finalize_success` dentro de la misma transacción local. A6.3A no llama a
Meta: `/complete` valida sus límites, payload y sesión, pero devuelve `501`
para que no parezca una conexión exitosa antes de implementar el exchange.

**UNKNOWN:** Meta puede considerar el authorization code de un solo uso o
inválido tras un timeout ambiguo. Que el intento de aplicación sea
reacquirible no implica que el mismo code pueda reutilizarse. A6.3 no hará
reintentos automáticos de un code cuyo resultado remoto sea desconocido.

### A6.3B — Exchange y verificación de activos (investigación)

**Estado:** investigación documentada; no implementado ni desplegado.

**VERIFIED (colección oficial de Meta en Postman, consultada 2026-09-28):**

- `GET /{WABA_ID}/phone_numbers` devuelve los teléfonos pertenecientes a una
  WABA, incluidos su `id`, nombre verificado y número de presentación.
- `POST /{WABA_ID}/subscribed_apps` existe y la colección muestra una
  respuesta exitosa `success`; el acceso usa un bearer token.
- `POST /{PHONE_NUMBER_ID}/register` requiere `messaging_product=whatsapp` y
  un PIN de seis dígitos. La documentación también indica verificación previa
  de propiedad por SMS o voz para los escenarios aplicables.

**OBSERVED (consola Meta actual):** la configuración es Embedded Signup `v4`
con Session Information `3`. La consola indica que el flujo puede crear o
seleccionar una cuenta WhatsApp Business, agregar/verificar/compartir un
teléfono y entregar identificadores candidatos de cuenta y teléfono al
navegador. Esos identificadores siguen siendo datos no confiables hasta la
verificación server-to-server.

El ejemplo de integración generado actualmente muestra un exchange
server-to-server por `POST` a `https://graph.facebook.com/v25.0/oauth/access_token`
con JSON y los campos visibles `client_id`, `client_secret`,
`grant_type=authorization_code` y `redirect_uri`. También indica que el
authorization code participa en el exchange y que el app secret nunca puede
estar en código cliente. La interfaz no mostró cómo serializa el `code`, por
lo que ese detalle permanece **UNKNOWN**. SDK/webhook observados usan `v26.0`;
esto no prueba que las versiones sean intercambiables ni fija aún la versión
Graph del backend.

La consola describe el resultado conceptual como una cuenta WhatsApp
seleccionada/compartida con un access token asociado. Asimismo muestra una
operación para recuperar cuentas WhatsApp propias o compartidas por el cliente
con el negocio proveedor que exige un *system-user access token*. No se ha
establecido que ese token sea idéntico al token asociado a la cuenta que
produce Embedded Signup.

**INFERENCE:** A6.3B debe intercambiar el code sólo en servidor, mantener el
token únicamente en memoria durante la verificación, enumerar los activos
autorizados con ese token, exigir que ambos IDs candidatos estén en la misma
relación WABA → teléfono y suscribir la app antes de persistir una conexión
`connected`. La secuencia propuesta es:

```text
browser: code + candidate WABA + candidate phone
  → /complete: body limitado y admin_session
  → acquire processing lease
  → exchange server-to-server
  → verificar cuenta/credencial
  → GET /{WABA_ID}/phone_numbers
  → comprobar membership del phone candidato
  → POST /{WABA_ID}/subscribed_apps
  → registro de teléfono sólo si el escenario lo requiere
  → transacción local: persistir conexión cifrada + finalize_success
```

Ninguna llamada HTTP externa puede ocurrir mientras una transacción local
permanezca abierta. Ningún ID recibido del navegador basta por sí solo.

**UNKNOWN (bloquea implementación):** la documentación técnica primaria de
Meta devolvió límites de acceso durante esta investigación; por tanto aún no
se ha verificado de forma primaria el contrato exacto del exchange, el tipo y
vida del token emitido por la configuración actual, la semántica de reuso del
authorization code, la idempotencia/inspección de `subscribed_apps` y qué
escenarios de alta/registro de teléfono resuelve automáticamente Embedded
Signup. El bloqueo explícito abarca: serialización del `code`; tipo, duración
y revocación del token; duración/single-use/idempotencia/reconciliación del
code; reintentos tras rechazo, timeout, reset, `5xx` o `429`; relación entre
el token de cliente y el system-user token de discovery; necesidad real de
discovery provider-level; circunstancias de `/register`; inspección y
repetibilidad de la suscripción; y recuperación de éxito remoto seguido de
caída antes de persistencia local. No se implementará un cliente Graph hasta
confirmar esos contratos con documentación accesible o consola/soporte
oficial.

**Seguridad y recuperación:** un timeout, reset o caída después de enviar el
code tiene resultado remoto ambiguo. La lease A6.3A puede volver a adquirirse
tras expirar, pero eso **no** autoriza reintentar el mismo code. Hasta que
Meta documente lo contrario, la UI debe reiniciar el signup y no debe haber
reintento automático del code. Tampoco se persistirá el authorization code
para facilitar reintentos. Si Meta confirma éxito y el proceso cae antes de
persistir localmente, la arquitectura necesitará reconciliación o staging
cifrado y con expiración; no se añadirá ese almacenamiento especulativo en
A6.3B sin contrato verificado.

**Fuentes consultadas (2026-09-28):**

- Colección oficial de Meta: WhatsApp Cloud API en Postman —
  `https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api`
- Colección oficial de Meta: Embedded Signup en Postman —
  `https://www.postman.com/meta/whatsapp-business-platform/documentation/du6gzjv/embedded-signup`
- Referencia oficial de Meta: Embedded Signup —
  `https://developers.facebook.com/docs/whatsapp/embedded-signup`
  (no disponible para lectura automatizada durante esta consulta).
- Referencia oficial de Meta: Cloud API —
  `https://developers.facebook.com/docs/whatsapp/cloud-api`
  (no disponible para lectura automatizada durante esta consulta).

**Siguiente checkpoint:** confirmar contrato primario del code exchange y
token lifecycle; después implementar un cliente Graph aislado, con timeouts,
límites de respuesta, errores sanitizados y pruebas completamente mockeadas.

### A6.3B-0.2 — Identidad de token y contrato de verificación

**Estado:** investigación documentada; no implementado ni desplegado.

**VERIFIED (colección oficial Meta Embedded Signup en Postman, consultada
2026-09-28):** `GET /{Version}/debug_token` acepta `input_token`, descrito
como el token devuelto tras completar Embedded Signup. El ejemplo de la
colección autoriza esa llamada con un bearer *System-User Access Token*. Su
respuesta documentada contiene `app_id`, `type`, `is_valid`, `expires_at`,
`data_access_expires_at`, `scopes`, `granular_scopes` y `target_ids`. El
ejemplo muestra `type=USER` para el token de Embedded Signup.

**INFERRED:** comprobar token válido, app esperada, scopes requeridos y
`target_ids` del scope granular, seguido de `GET /{WABA_ID}/phone_numbers`,
es la cadena adecuada para verificar el onboarding tenant-specific. Un ID del
navegador o el acceso aislado a una WABA no demuestran por sí solos toda la
cadena de autorización.

| Credencial | Representa | Obtención | Uso | ¿Persistir en `WhatsAppConnection`? |
| --- | --- | --- | --- | --- |
| Token OAuth/User de Embedded Signup | Token devuelto al finalizar el flujo; debug lo clasifica `USER` | Exchange server-to-server observado | Verificar token y activos del cliente | **UNKNOWN:** el schema puede cifrarlo, pero lifecycle/revocación no están confirmados |
| Token system-user del proveedor | System user del negocio proveedor | Gestión Meta del proveedor | `debug_token` y discovery provider-level según la colección | No; no representa una conexión tenant |
| App secret | Credencial de la app proveedora | Configuración Meta server-side | Exchange observado | No; nunca en frontend ni en la conexión |

**VERIFIED:** la colección Embedded Signup muestra
`GET /{Business-ID}/client_whatsapp_business_accounts` para WABAs compartidas
con el negocio proveedor y usa un *System-User Access Token* en su ejemplo.
La colección Cloud API muestra el mismo edge con un bearer denominado
*User-Access-Token*. Esta inconsistencia queda **UNKNOWN**. **INFERRED:**
shared-WABAs sirve para discovery/reconciliación provider-level, no como el
control primario tenant-specific, que debe partir del token de Embedded Signup.

**VERIFIED:** la colección Embedded Signup indica Advanced Access/App Review
para `business_management` y `whatsapp_business_management`. La consola
observada muestra `whatsapp_business_management` y
`whatsapp_business_messaging`. La diferencia queda documentada; no se
añadirá un scope automáticamente.

**VERIFIED:** `expires_at` y `data_access_expires_at` aparecen en debug. Eso
permite guardar la expiración devuelta para un token concreto, pero no prueba
una duración normativa ni una política de renovación. Los campos actuales
`encrypted_access_token`, `token_expires_at` y `granted_scopes` siguen siendo
suficientes para esos datos observables.

**VERIFIED:** Cloud API indica que un teléfono de Embedded Signup debe
registrarse dentro de 14 días; de lo contrario debe pasar de nuevo por el
signup antes de registrarse. El registro sigue siendo condicional: no hay
evidencia de que nuestro flujo deba llamar `/register` después de cada signup.

**Crash/reconciliación:** `debug_token` sólo inspecciona un token que el
backend aún posee; no recupera uno perdido antes de persistencia. El hueco de
éxito remoto seguido de fallo local permanece. Staging cifrado con TTL lo
reduciría, pero añade secretos, cleanup y recuperación; forzar un nuevo signup
es más simple. Ambas opciones requieren primero confirmar la semántica del
code y token; ninguna se implementa aún.

**Bloqueadores restantes del code:** serialización exacta; lifetime;
single-use; reuso tras rechazo o fallo ambiguo; idempotencia del exchange; y
reconciliación del resultado. No se infieren de OAuth genérico.

**READY_FOR_A6_3B_1 = NO.** Falta evidencia primaria para implementar el
exchange sin inventar semántica del authorization code. El mínimo pendiente
es el payload exacto del exchange y la política de lifetime, replay, retry e
inspección/reconciliación del resultado.

### A6.3B-0.3 — Cierre del contrato de authorization code

**Estado:** investigación documentada; no implementado ni desplegado.

Se consultaron de nuevo los recursos oficiales Meta alcanzables el
2026-09-28, incluida la colección Embedded Signup y referencias enlazadas.
No apareció material primario de WhatsApp Embedded Signup que muestre la
serialización completa del `code` en el exchange actual. La documentación de
otros productos Meta no se usa como sustituto de ese contrato.

**OBSERVED — consola Meta Embedded Signup actual:** al introducir un
placeholder deliberadamente falso y no secreto, sin ejecutar el request, la
consola generó esta forma sanitizada:

```http
POST https://graph.facebook.com/v25.0/oauth/access_token
Content-Type: application/json
```

```json
{
  "client_id": "<APP_ID>",
  "client_secret": "<APP_SECRET>",
  "code": "<AUTHORIZATION_CODE>",
  "grant_type": "authorization_code",
  "redirect_uri": "<META_OAUTH_REDIRECT_URI>"
}
```

Por tanto, para el flujo actualmente observado, `code` es la propiedad
`code` del JSON body; `client_id`, `client_secret`, `grant_type` y
`redirect_uri` están en el mismo body. `config_id` y `code_verifier`/PKCE no
aparecen en el request generado actualmente. Esto no afirma que Meta nunca
pueda requerirlos en otra versión o flujo. Siguen **UNKNOWN** la coincidencia
normativa de `redirect_uri`, response JSON y estructura de errores.

**VERIFIED:** el contrato `debug_token` ya documentado permite validar después
del exchange un token que el backend posee. En una futura implementación, son
**REQUIRED** `is_valid` y `app_id` esperado; son **RECOMMENDED** scopes,
`granular_scopes.target_ids` y las expiraciones devueltas; no se justifica aún
suponer que esos campos sustituyen la verificación de teléfono dentro de la
WABA. `debug_token` no recupera un token que se perdió antes de persistirse.

**INFERRED:** si se confirma el request, el cliente deberá realizar sólo un
exchange por code, sin middleware de retries. Usará host Graph explícito,
HTTPS con validación TLS, versión explícita, timeouts separados de conexión y
lectura, límite de respuesta, redirects deshabilitados salvo contrato Meta,
transporte inyectable/mockeable y errores sanitizados. Code, token y secret no
deben entrar en repr, logs, errores ni persistencia; el token sólo se cifra al
decidir una persistencia duradera verificada.

**INFERRED:** la versión del exchange debe ser configuración dedicada, con
default igual a la versión observada en la consola, no reutilizar ni elevar
silenciosamente la versión observada para SDK/webhook. No se añadirá esa
configuración hasta que el payload quede verificado.

El hueco de crash después de respuesta Meta exitosa sigue separado del retry
del code. Sin staging, un crash exige reiniciar el signup; staging cifrado y
con TTL, o una `WhatsAppConnection` en estado no operativo, mejoraría
recuperación pero añade superficie, cleanup y una distinción adicional entre
credencial verificada/no verificada. La opción mínima justificada hoy es no
staging y reinicio manual tras un crash irrecuperable; se reevaluará al tener
semántica primaria de token/code.

```text
EXCHANGE_REQUEST_VERIFIED = YES
IMPLEMENT_ONCE = YES
AUTO_RETRY = NO
CRASH_RECOVERY_DESIGN_REQUIRED = YES
READY_FOR_A6_3B_1 = YES
```

`EXCHANGE_REQUEST_VERIFIED=YES` significa que la construcción exacta de un
request fue observada directamente en la consola Meta actual, no que su
lifecycle esté verificado mediante documentación normativa. Permanecen
**UNKNOWN** lifetime, single-use, replay, idempotencia, reintentos tras fallo
ambiguo, reconciliación del resultado, lifecycle/revocación del token y el
contrato detallado de respuesta/error.

**Límite congelado A6.3B-1:** cliente de exchange *one-shot* y frontera de
respuesta de token. Hará exactamente un `POST` Graph `v25.0` con el JSON
observado, TLS, timeouts estrictos de conexión/lectura, límite de respuesta,
redirects deshabilitados salvo nueva evidencia y transporte inyectable. No
tendrá retries automáticos, no persistirá el code, no registrará code/token/
secret y rechazará respuestas ausentes o inesperadas. No modificará todavía
`WhatsAppConnection`, ni consultará teléfonos, suscribirá WABA, registrará
teléfono o implementará reconciliación automática.

### A6.3B-1 — Cliente one-shot de exchange

**Estado:** completed.
**Commit:** `270bcfe16711b211ca080c351e86ce1740cd7c8a`.

Se añadió un cliente aislado para construir exactamente un `POST` a la versión
de Graph observada con JSON, sin query parameters adicionales. El cliente usa
host Graph controlado, `trust_env=False`, TLS de `httpx`, redirects
deshabilitados y timeouts explícitos. Envía `Accept-Encoding: identity` y
rechaza cualquier Content-Encoding diferente de identidad, por lo que no
depende de descompresión transparente para interpretar el token.

El body se consume con streaming raw: Content-Length sobredimensionado se
rechaza antes de leerlo y, sin confiar en ese header, cada chunk se mide antes
de añadirse. La aplicación no acumula más de 16 KiB antes de JSON parsing; no
afirma controlar buffers internos de red, TLS o `httpx`. Content-Encoding,
errores de streaming y `httpx.RequestError`/decoding se traducen a errores de
dominio sanitizados. Un `access_token` sólo de espacios se rechaza, pero un
token válido no se normaliza.

Cada invocación emite como máximo un request: no hay middleware ni lógica de
retry para timeouts, transporte, `4xx`, `429`, `5xx`, redirects, JSON inválido
ni respuesta malformada. Sus errores son tipados y sanitizados; code, token y
app secret están protegidos en `repr` y no se registran. Las pruebas usan sólo
transporte mock y valores ficticios: no ejecutan requests Meta. Incluyen
streams async controlados para verificar límites por chunks y que no se
consume el resto tras rebasar el máximo.

La frontera de éxito es intencionalmente mínima: HTTP `200`, Content-Type JSON
y objeto con `access_token` string no vacío. Campos adicionales se ignoran y
no se inventa semántica de expiración, scopes o token type. A6.3B-1 no está
integrado en `/complete`, no adquiere leases ni persiste ningún secreto o
conexión. Aún faltan validación con `debug_token`, activos, suscripción,
registro condicional y reconciliación.

### A6.3B-2 — Inspección de token con `debug_token`

**Estado:** implementado localmente, pendiente de revisión/commit.

Se añade un inspector Graph aislado que ejecuta exactamente un `GET` a
`/{version}/debug_token`: el token customer-specific recibido por Embedded
Signup se entrega sólo como `input_token`, mientras un token separado de
proveedor/system-user autoriza la petición mediante Bearer. No se reutiliza
ninguna credencial de cliente como token de inspección.

La versión Graph del inspector se configura explícitamente y por separado,
con default `v25.0`, alineado con el request observado de exchange; no queda
acoplada a la versión del webhook sin evidencia. El cliente conserva las
propiedades de B-1: host controlado, TLS de `httpx`, `trust_env=False`,
timeouts explícitos, redirects y reintentos deshabilitados, `Accept-Encoding:
identity`, rechazo de respuestas comprimidas y lectura raw incremental con
límite de respuesta a nivel aplicación.

La respuesta exige `data`, `is_valid: true` y el `app_id` esperado. Preserva
de forma tipada `type`, expiraciones, `scopes`, granular scopes y
`target_ids` cuando se presentan y son válidos; no deriva lifetime normativo,
no acepta aún activos por `target_ids` como autoridad final y no sustituye la
verificación futura WABA → teléfono. Los tokens y respuestas upstream no se
persisten ni se incluyen en logs, errores o `repr`.

A6.3B-2 no se integra en `/complete`, no adquiere ni modifica leases, no
crea/modifica `WhatsAppConnection`, y sus pruebas usan exclusivamente
transporte mock con credenciales ficticias. Siguen pendientes la verificación
de activos, suscripción, registro condicional, persistencia cifrada y
reconciliación de fallos ambiguos.

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
| A6.2 | completed | `161a1b8b4f86bc759ec207e3fb66c9e25a6d4ac8` | Ephemeral signup asset-correlation boundary | no |
| A6.3A | completed | `68504d8e62653edcf9a081310fbe3364a550ae93` | Processing leases before external exchange | no |
| A6.3B-1 | completed | `270bcfe16711b211ca080c351e86ce1740cd7c8a` | One-shot authorization-code exchange | no |
| A6.3B-2 | implemented locally, pending review/commit | pending review/commit | `debug_token` validation; asset verification pending | no |

## 12. Updating this document

Cada commit de WhatsApp multi-tenant o Embedded Signup debe actualizar este
documento con fase, fecha, hash, cambio arquitectónico, implicaciones de
seguridad, migraciones/configuración, pruebas, validación productiva,
limitaciones y siguiente checkpoint.

Nunca documentar access tokens, app secrets, webhook verify tokens, session
secrets, credenciales de base de datos, teléfonos, WABA IDs, phone number IDs,
configuration IDs, authorization codes ni IPs.
