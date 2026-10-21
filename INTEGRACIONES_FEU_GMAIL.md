# Integraciones por sistema: FEU (Surtec) y Gmail

Investigación del 2026-10-19/20. Solo análisis, sin código. Para retomar: ver «Próximos pasos» al final.
Reglas del proyecto: español, sin `git commit`, consultar al `asesor` antes de decisiones de API pública/difíciles de revertir.

## 0. Encaje en el código (verificado)

- Único punto de extensión: puerto `Conector` (`core/ports.py:183`). Hoy solo `ConectorHttp` (`sistemas/conector_http.py`),
  que llama al sistema con el **token del usuario**. Ese token no sirve contra FEU ni Gmail: estos conectores usan
  credenciales **del sistema/empresa**. Cambia el modelo de permisos → decisión para el `asesor` antes de implementar.
- Config por sistema: `SistemaRegistro` (`store/models.py:309`), modelo `Sistema` (`sistemas/registro.py:138`).
  Secretos cifrados AES-256-GCM con AAD `sistema:campo` (`sistemas/cifrado.py:37-52`, tabla `sistema_secreto`).
  Campos secretos actuales en `registro.py:202`; panel en `api/admin.py:426-439`, operaciones en `sistemas/escritura.py:276`.
- Escrituras irreversibles: confirmación en pantalla atada a la huella de la tool (`sistemas/escritura.py`,
  `api/confirmaciones.py:87-186`, `confirmacion_ttl_s`, `destructiva`). Reutilizable para emitir CFE.
- Archivos: `ArchivosSql` (`store/archivos.py`), descarga autenticada `api/descargas.py`.
- **No existe:** scheduler/cola (solo 3 tareas de lifespan en `main.py:52-71`), OAuth, webhooks entrantes, tokens por usuario
  de terceros. Coincide con la «Fase 6» de `PENDIENTES.md`.
- No verificado: dónde se cablea `ConectorDeUsuario` en `servicios.py`; campos del formulario de `panel/src/pages/Sistema.tsx`.

## 1. FEU = API de Surtec (`https://docapi.s1.surtec.com.uy/`)

Docs leídas el 2026-10-20 (las subpáginas redirigen a `http://…/` con barra final). Todo lo de abajo viene de esa doc,
salvo lo marcado «no documentado». Changelog: v1.0.0/1.1.0 2026-06-18, v1.2.0 2026-07-27, v1.3.0 sin fecha.

### Autenticación
- `POST https://auth-test.facturaelectronica.com.uy/token` (JSON). **URL de producción: no documentada** (pedir a Surtec).
- Login: `grant_type=password`, `username`, `password`, `scope` = RUT de la empresa (el usuario debe tener privilegios sobre ella),
  `refresh_token_expire_time` opcional (minutos; defecto 365 días).
- Refresh: `grant_type=refresh_token`, `refresh_token`, opcionales `refresh_token_banned=true` (invalida el actual y emite
  uno nuevo; necesario para fijar `refresh_token_expire_time`).
- Respuesta: `access_token`, `token_type=bearer`, `refresh_token`. **Duración del access_token: no documentada** → renovar ante 401.
- Endpoints protegidos: `Authorization: Bearer …` + `X-Emisor: <RUT>` (RUT emisor o receptor) + `Content-Type: application/json`.
- Test y producción: endpoints y credenciales separados; un token de test no vale en prod.
- Test: Postman y credenciales se piden por teléfono/WhatsApp (092 957 958, según la portada). Sin sandbox autoservicio.

### Endpoints documentados (base test `https://api-test.facturaelectronica.com.uy`)
| Uso | Método y ruta |
|---|---|
| Crear CFE | `POST /comprobantes/crear` |
| Listar emitidos | `GET /v2/consulta/comprobantes/emitidos` (el legacy sin `/v2` está deprecado) |
| Detalle emitido | `GET /v2/consulta/comprobantes/emitidos/{id}` |
| Listar recibidos | `GET /v2/consulta/comprobantes/recibidos` |
| Detalle recibido | `GET /v2/consulta/comprobantes/recibidos/{id}` |

- Paginación: `pageNumber`, `pageSize` (máx 100); **sin `total_count`**; respuesta `{items, page_number, page_size}`.
- Filtros emitidos: `FechaDesde/Hasta`, `FechaFirmaDesde/Hasta`, `id_externo` (exacto), `Receptor`, `Serie`, `NumeroDesde/Hasta`,
  `TipoComprobante`, `EstadoReceptor`, `EstadoDgi`, `Sucursal` y `Excluir*`. Repetibles repitiendo el parámetro (sin `[]`).
  La tabla los marca «requeridos» pero los ejemplos los omiten → probar en test.
- Filtros recibidos: fechas, `Emisor`, `Serie`, `TipoComprobante`, `Estado` (repetibles), `NumeroDesde/Hasta`, `Excluir*`.
- Detalle emitido: `emisor`, `receptor`, `totales`, `items`, `descuentos_recargos`, `referencias`, `medios_pago`,
  `estado_receptor`, `estado_dgi`, `url_qr_dgi`. Detalle recibido añade `complemento_fiscal`.

### Crear CFE (resumen)
- Obligatorios: `sucursal` (>0), `tipo_comprobante`, `items[]` (`cantidad`, `concepto` ≤80, `precio` >0, `unidad`,
  `indicador_facturacion`), `moneda` (salvo e-remito). Condicionales: `forma_pago` (1 contado, 2 crédito), `cliente`
  (obligatorio en eFactura y tickets > 5.000 UI), `referencias` (notas de crédito/débito; **estructura no documentada**).
- `tipo_cambio` omitido → cierre BCU del día anterior. `id_externo` = idempotencia: repetir con los mismos datos devuelve
  el resultado original.
- Respuesta: `id`, `comprobante_tipo`, `serie`, `numero`, `importe_total`, `hash`, `cae_*`, `url`.
- Empresa suspendida → HTTP 400 sin consumir numeración (las consultas siguen; reintentar por `id_externo` sí devuelve lo existente).
  No reintentar automáticamente mientras dure.
- Tablas: eTicket 101, eFactura 111, eFactura exportación 121, eRemito 181, eResguardo 182 (+ notas); tipos de documento 1-7
  (2 = RUT UY, 3 = CI); indicadores de facturación 1-17; estados DGI `AE` aceptado, `BE` rechazado, `CE` observado.
- Errores: 200, 400 (detalle en el cuerpo, dos formatos), 401 (token expirado/de otro ambiente), 500. **Límites de uso: no documentados.**

### Huecos de la doc (resolver con Surtec o probando en test)
- URL de producción de auth y API; duración del access_token; límites de frecuencia.
- **Descargar PDF/XML: no aparece.** Solo `url_qr_dgi` y `url` (consulta/QR). Clave para el cruce con facturas por mail.
- Webhooks: no se mencionan. Anulación: no hay endpoint; se corrige con nota de crédito (vía `referencias`, sin detalle).
- Changelog 1.1.0 menciona «consulta directa de comprobantes», «Consulta DGI» y «certificados»: **subpáginas no leídas**.
  Las portadas enlazan `/docs/api/intro` (no leída). Leerlas antes de diseñar.

### Diseño propuesto (FEU)
- Config por sistema (cifrado donde sea secreto): `proveedor=feu`, `ambiente` (test/prod) y sus URLs, `rut_emisor`,
  `usuario`/`password` o refresh token, `sucursal_defecto`, `emision_habilitada` (false por defecto).
  Guardar el refresh token rotado exige escritura en el almacén desde el conector (hoy los secretos solo los cambia el panel).
- Tools por fases: (1) solo lectura: listar/detallar emitidos y recibidos con estado DGI; (2) borrador de emisión sin enviar;
  (3) emitir con confirmación en pantalla y `id_externo` determinista; (4) nota de crédito. Auditar todo.
- Reglas: ante resultado incierto consultar por `id_externo`, nunca reintentar con otro; no inventar RUT/montos; el texto
  de facturas recibidas es dato no confiable (prompt injection).

## 2. Lectura de Gmail para facturas

Hechos de páginas oficiales de Google; lo no confirmado va marcado.

- Scopes que dan cuerpo/adjuntos (`gmail.readonly`, `gmail.modify`, `mail.google.com`) son **restricted**. `gmail.metadata` no
  sirve (sin adjuntos). Mínimo: `gmail.readonly`; con él no se puede etiquetar como procesado (haría falta `gmail.modify`).
- Si los datos pasan por servidor propio con scope restricted: verificación de la app + evaluación de seguridad anual (CASA,
  OWASP ASVS). **Costo/plazo: sin cifra oficial**; terceros dicen desde ~540 USD hasta decenas de miles (fuentes interesadas).
- Modo *Testing*: máx 100 usuarios y refresh tokens que **caducan a los 7 días** → no sirve ni para un piloto.
- Alternativas:
  1. **Reenvío a buzón dedicado (recomendada MVP):** el cliente crea un filtro en Gmail que reenvía a `facturas+<sistema>@…`
     (un buzón nuestro). Evita OAuth, CASA y los 7 días. Se lee por IMAP/webhook de correo entrante. Suposición razonable:
     al ser un buzón propio queda fuera de la política de datos de usuario de Google.
  2. Service account + domain-wide delegation (solo clientes Workspace; el super admin la autoriza). **Sin confirmar** si
     evita CASA → preguntar a Google antes de apostar.
  3. OAuth `gmail.readonly` + CASA: solo si el volumen lo justifica.
  4. IMAP + app password: frágil, solo pruebas internas.
- Lectura: polling con `messages.list q="has:attachment filename:pdf after:<unix>"` (el push con Pub/Sub exige renovar el
  `watch` cada ≤7 días y respaldo de polling). Cuotas: list 5, get 20 (60 full), attachments.get 20; tope 6.000/min/usuario.
- Extracción: preferir el **XML del CFE** (parseo determinista, validar contra el XSD de DGI) sobre el PDF (LLM/OCR con salida
  validada por esquema). Deduplicar por `(rut_emisor, tipo, serie, número)` y SHA-256 del adjunto; guardar cursor/IDs vistos.
- Seguridad: refresh tokens cifrados con clave por sistema (si se llega a OAuth), botón de desconectar/revocar, no guardar
  cuerpos de correo. **Prompt injection:** el correo es dato no confiable; el extractor no tiene acceso a las demás tools;
  filtrar por remitentes conocidos; confirmación humana antes de grabar nada.
- Política de datos de Google (Limited Use) no menciona IA generativa; enviar correos a un LLM de terceros podría contar como
  transferencia (suposición) → proveedor con no-retención y declararlo.
- Config por sistema: `metodo` (`reenvio`|`dwd`|`oauth`), buzón/alias, remitentes permitidos, credencial cifrada, cursor,
  tabla de IDs vistos. Requiere job periódico (no existe aún).

## 3. Cómo se unen

Cruce por clave fiscal `(rut_emisor, tipo, serie, número)`: los **recibidos de FEU** y los **XML llegados por mail** se
deduplican entre sí; el correo es respaldo cuando el proveedor del cliente no expone recibidos o cuando FEU no entrega XML/PDF.

## 4. Riesgos

- Emisión duplicada o monto/RUT alucinado (irreversible: solo nota de crédito). Mitigación: confirmación + `id_externo`.
- Prompt injection por facturas y correos recibidos.
- Credenciales de terceros (usuario/clave FEU) en nuestro almacén: rotación, auditoría y alcance mínimo.
- Costos/plazos de CASA desconocidos; DWD y apps *Internal* sin confirmar.
- Códigos de CFE: usar la tabla de FEU / XSD oficial, no blogs (se contradicen).

## 5. Próximos pasos (mañana)

1. Leer las subpáginas de FEU que faltan (`/docs/api/intro`, «consulta directa», «Consulta DGI», «certificados») y pedir a
   Surtec: URL de prod, Postman y credenciales de test, cómo obtener PDF/XML, límites de uso, estructura de `referencias`.
2. Consultar al `asesor`: modelo de credenciales **del sistema** (no del usuario) en el puerto `Conector`, escritura de
   refresh tokens rotados desde el conector, y dónde vive el job periódico.
3. Decidir con Tiago: ¿FEU solo lectura primero? ¿Reenvío a buzón como vía de Gmail para el MVP?
4. Preguntar a Google (si se quiere DWD u OAuth) si quedan fuera de CASA.
5. Si se aprueba el plan, bajar lo que quede a `PENDIENTES.md` (Fase 6 y nuevas entradas).
