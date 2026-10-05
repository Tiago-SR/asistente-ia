# Asistente MVP

Servicio de **asistente conversacional multi-sistema**. Permite a los usuarios de cualquier sistema integrado (por ejemplo SGAgro) hacer preguntas en lenguaje natural sobre sus propios datos, primero por texto y más adelante por voz.

El asistente corre en su propio contenedor y es agnóstico a la tecnología de los sistemas que lo consumen. No accede a sus bases de datos ni decide permisos. Solo habla con ellos a través de un **contrato HTTP** (manifiesto de tools + ejecución) usando el **token JWT del usuario** que pregunta. Cada sistema aplica sus propios permisos.

Principios del MVP:

- Solo lectura.
- Aislamiento estricto entre sistemas y entre usuarios.
- Cifras siempre trazables a una tool (nada inventado).
- Proveedor de LLM intercambiable (formato neutro + adaptadores).

> Estado: Fases 0, 1 y 2 completas (asistente de texto de solo lectura, widget, verificador, guía de tools, referencia PHP, kit de despliegue y CI) y la voz del navegador con el modo «manos libres» del widget. Faltan la prueba manual en Chrome real, el despliegue en el VPS (en espera) y los sistemas reales; ver [Estado y pendientes](#estado-y-pendientes).

## Stack

Python 3.12 · FastAPI · httpx · Postgres 16 · SQLAlchemy 2 / Alembic · PyJWT · gestionado con `uv` dentro de Docker.

## Requisitos

- Docker y Docker Compose. No hace falta instalar Python ni `uv` en tu máquina.

## Levantar en desarrollo

```sh
# 1. Variables de entorno (una sola vez)
cp .env.example .env

# 2. Registro de sistemas (opcional por ahora; arranca vacío)
cp config/sistemas.example.yaml config/sistemas.yaml

# 3. Construir y levantar asistente + Postgres
docker compose -f docker-compose.dev.yml up --build
```

El servicio queda en <http://localhost:8100> con recarga automática al editar `src/`. Comprobación rápida:

```sh
curl localhost:8100/salud
# {"ok":true}
```

La documentación interactiva de la API está en <http://localhost:8100/docs> (solo dev: en prod `/docs` está apagado).

### LLM local

El servicio habla con cualquier endpoint OpenAI-compatible (`/v1/chat/completions` con streaming y tool calling). Para usar un `llama-server` en el host:

```sh
# en .env (el compose ya trae un default: http://host.docker.internal:8090/v1)
LLM_BASE_URL=http://host.docker.internal:8090/v1
ASISTENTE_MODELO_DEFAULT=<nombre del modelo>
```

`docker-compose.dev.yml` define `extra_hosts: host.docker.internal:host-gateway` para que el contenedor llegue al host en Linux. El `llama-server` debe escuchar en una interfaz alcanzable desde Docker (`--host 0.0.0.0`, no solo `127.0.0.1`) y conviene firewall que lo limite a la red local. `LLM_BASE_URL` debe incluir el `/v1`.

### Tests

Dos sistemas mock en memoria y Postgres real (los tests de BD se saltan sin `ASISTENTE_DATABASE_URL`):

```sh
docker compose -f docker-compose.dev.yml up -d postgres
docker compose -f docker-compose.dev.yml run --rm asistente sh -c 'ruff check src tests && pytest -q'
```

`tests/test_aislamiento.py` es el hito de la Fase 1: tokens entre sistemas, mismo `sub` en dos sistemas, ana vs. beto vía chat, prompt injection, redirecciones y `token_manifiesto`, tools de escritura, límites/cuotas y borrado.

### Comandos habituales

```sh
docker compose -f docker-compose.dev.yml run --rm asistente pytest          # tests
docker compose -f docker-compose.dev.yml run --rm asistente ruff check .    # lint
docker compose -f docker-compose.dev.yml run --rm asistente python evals/correr.py   # evals contra el LLM real (cuesta tokens)
docker compose -f docker-compose.dev.yml logs -f asistente                  # logs
docker compose -f docker-compose.dev.yml down                               # parar (conserva la BD)
docker compose -f docker-compose.dev.yml down -v                            # parar y borrar la BD de desarrollo
```

Postgres de desarrollo se publica solo en `127.0.0.1:5433` (usuario, contraseña y base: `asistente`).

### Cambiar dependencias

Editar `pyproject.toml` y regenerar `uv.lock`:

```sh
docker run --rm -v "$PWD":/app -w /app --entrypoint sh python:3.12-slim \
  -c 'pip install -q uv && uv lock'
```

Luego reconstruir con `docker compose -f docker-compose.dev.yml build asistente`. Si el lock queda con dueño root, corregirlo con `sudo chown $USER uv.lock`.

## Widget

El asistente sirve el Web Component en `GET /widget.js` (sin dependencias ni build; código en `src/asistente/static/widget.js`). Es una **vista de chat a pantalla completa** (columna de mensajes y entrada fija abajo; solo muestra la conversación actual, con un botón para empezar otra, sin lista de chats por ahora), no una burbuja flotante: ocupa el 100% de su contenedor, así que el sistema lo coloca en una página o sección propia y le da alto. Se integra con dos líneas:

```html
<script src="https://asistente.example.com/widget.js" defer></script>
<asistente-chat style="display:block;height:100vh" servidor="https://asistente.example.com" token-url="/asistente/token"></asistente-chat>
```

Atributos opcionales: `titulo`, `placeholder`, `idioma` (voz, por defecto `es-UY`), `voz` (nombre de una voz del navegador), `voz-motor` (`auto` | `navegador` | `servidor`), `palabra-activacion` (por defecto `asistente`) y `manos-libres-inactividad` (minutos, por defecto 5; 0 = nunca). **Voz:** el widget dicta con el reconocimiento del navegador (en Chrome el audio se procesa en Google; `voz-motor="servidor"` lo evita usando el STT del asistente) y lee las respuestas con las voces del navegador (botón por mensaje e interruptor de lectura automática). **Manos libres:** un botón en la barra deja el micrófono escuchando la palabra de activación; lo dictado queda en el campo y se envía solo tras confirmarlo («enviar» o botón). Aparece solo con reconocimiento del navegador (no con `voz-motor="servidor"`) y con el indicador de micrófono abierto siempre visible. Detalle en la sección 7.4 del contrato. Se personaliza con variables CSS (`--asistente-color`, `--asistente-fondo`, `--asistente-fuente`, `--asistente-ancho-lateral`, `--asistente-ancho-columna`, …) y avisa al anfitrión con los eventos `asistente:accion` (sugerencias `ui`) y `asistente:estado` (si no está disponible para el usuario, muestra un aviso en lugar del chat). El origen de la página debe estar en `origenes_permitidos` del sistema.

Demo local: el sistema mock sirve una página con el widget (`MOCK_ASISTENTE_URL` apunta al asistente, por defecto `http://localhost:8100`). Registrá el mock en `config/sistemas.yaml` con su origen en `origenes_permitidos`, levantalo con `uvicorn app:app --app-dir ejemplos/sistema-mock --port 8201` y abrí <http://localhost:8201/?usuario=ana>.

## Integrar un sistema (kit de integración)

- [`contrato/CONTRATO.md`](contrato/CONTRATO.md): lo que debe implementar el sistema (token, manifiesto, ejecución), credenciales y widget.
- [`contrato/GUIA_TOOLS.md`](contrato/GUIA_TOOLS.md): cómo diseñar las tools (elegirlas, describirlas, qué devolver, errores de negocio).
- `ejemplos/sistema-mock/`: implementación de referencia con datos ficticios. `MOCK_DEFECTO=<nombre>` rompe una regla del contrato a propósito (lo usan los tests del verificador).
- `ejemplos/sistema-php/`: implementación de referencia en PHP 8.2+ (router mínimo, portable a CodeIgniter 4), con tests PHPUnit y su [README](ejemplos/sistema-php/README.md). Servicio `sistema-php` en `docker-compose.dev.yml` (puerto 8203).
- `herramientas/probar_audio/`: banco de pruebas de audio, independiente del servicio. `python3 herramientas/probar_audio/servidor.py` y abrir <http://127.0.0.1:8400> (Chrome o Edge). Prueba el micrófono con detección de voz por energía, la transcripción con su latencia, el TTS en streaming, la interrupción y un modo eco. También puede usar el reconocimiento y la síntesis de voz del propio navegador (sin clave) para compararlos. Usa por defecto el speaches local (`--profile voz`); para otro proveedor, `STT_BASE_URL`/`STT_MODELO`/`STT_API_KEY` y `TTS_*` (cualquier endpoint compatible con OpenAI). La cabecera de `servidor.py` lista todas las variables.
- `herramientas/verificar_sistema.py`: verificador de conformidad; un sistema no se habilita en producción sin pasarlo. Los secretos se pasan por variables de entorno y no se imprimen:

```sh
V_MANIFIESTO=... V_SECRETO=... python herramientas/verificar_sistema.py \
  --base-url http://localhost:8201 \
  --token-url "http://localhost:8201/asistente/token?usuario=ana" \
  --token-url-otro "http://localhost:8201/asistente/token?usuario=beto" \
  --token-manifiesto-env V_MANIFIESTO --secreto-firma-env V_SECRETO
```

Opciones y comprobaciones en la [sección 6.5 del contrato](contrato/CONTRATO.md#65-verificar-la-integración). Los tests (`tests/test_verificador.py`) comprueban que detecta una variante rota del mock por cada comprobación.

## Producción

Guía completa para una VPS nueva (host, DNS, proxy con TLS, backups, rollback): [`deploy/VPS.md`](deploy/VPS.md). Resumen:

```sh
cp .env.example .env                                   # completar: POSTGRES_PASSWORD, ASISTENTE_ADMIN_TOKEN, LLM_*
cp config/sistemas.example.yaml config/sistemas.yaml
deploy/deploy.sh                                       # build etiquetado + up + espera salud (backup previo si ya hay BD)
```

`docker-compose.yml` es la base (imagen `prod`: sin dependencias de desarrollo, no-root, solo lectura, Postgres sin puertos, logs rotados, Whisper opcional con `COMPOSE_PROFILES=voz`); `docker-compose.prod.yml` publica el puerto en loopback y `docker-compose.proxy-externo.yml` conecta a un Caddy en la red `web`. Dockge usa el `docker-compose.yml` y el `.env` del stack. Hace falta un proxy con TLS, sin buffering (SSE) y sin exponer `/admin` ni `/docs`: ejemplos en `deploy/Caddyfile.example` y `deploy/nginx.conf.example`. Un `.env` por host (no se versiona).

## Estructura

```
Dockerfile               multi-stage: dev | prod
docker-compose.yml       producción (por defecto, Dockge)
docker-compose.dev.yml   desarrollo
docker-compose.prod.yml  override: puerto en loopback (VPS con proxy en el host)
deploy/                  VPS.md, deploy.sh, backup.sh, Caddyfile y nginx de ejemplo
src/asistente/           código del servicio
tests/                   tests
config/                  registro de sistemas (sistemas.yaml)
prompts/                 prompt base y de dominio
contrato/                contrato v1, schemas, OpenAPI y guía de tools
ejemplos/sistema-mock/   sistema de referencia con datos ficticios
ejemplos/sistema-php/    referencia PHP del contrato
tests_e2e/               e2e del widget en navegador (Playwright MCP)
evals/                   preguntas, corredor y línea base por modelo (resultados/)
herramientas/            verificador de conformidad y banco de pruebas de audio
PROVEEDORES_VOZ.md       referencia para el respaldo remoto de voz (opcional)
```

## Estado y pendientes

**Hecho:** servicio de solo lectura (registro de sistemas, JWT por sistema, conector HTTP, loop del agente, límites, auditoría, API `/v1/*` con SSE, purga de retención), widget con voz del navegador y modo manos libres, verificador de conformidad, guía de tools, referencias mock y PHP, kit de despliegue y CI, y `evals/` con línea base de `deepseek-flash` (32/32, ≈0,0002 USD por pregunta en valle; modelo vía `api.deepseek.com/v1`, clave en `.env`).

**Pendiente:**

- **Prueba manual en Chrome real** (la hace el usuario): voces es-UY/es-ES, lectura automática, dictado seguido de lectura, manos libres con auriculares (el eco de los parlantes está aplazado y no se usa detector de energía), móvil, Safari y Edge.
- **Respaldo remoto de voz (opcional):** solo si algún cliente no puede enviar audio a Google o se quiere una voz más natural. El STT ya entra por `STT_*`; un TTS requeriría un puerto `TTS` y `POST /v1/voz/sintetizar`. Comparativa de proveedores en [`PROVEEDORES_VOZ.md`](PROVEEDORES_VOZ.md).
- **Fase 3, primer sistema real (SGAgro; en espera, falta el sistema):** entregar el kit, acompañar el diseño de sus tools y su prompt de dominio, verificador en verde contra su entorno de pruebas, set de evals propio y costo por pregunta y por sistema.
- **Fase 5, acciones con confirmación:** habilitar tools de escritura por sistema y por tool. El modelo propone, el asistente emite `confirmacion` con un resumen y un id firmado, el usuario confirma en el widget (no por texto) y el asistente ejecuta con ese id; el sistema exige un token con scope de escritura emitido para esa confirmación. Auditadas y, si se puede, reversibles.
- **Fase 6, proactivo (a evaluar):** webhooks del sistema hacia el asistente o consultas programadas; requiere cola o cron en el contenedor.
- **Despliegue en el VPS (en espera):** kit listo y probado en local. Hito: stack tras el proxy con TLS, `/admin` y `/docs` cerrados, SSE sin buffering y widget probado contra el dominio real. Los backups quedan en el mismo VPS por ahora.

**Preguntas abiertas:**

- **Privacidad por cliente:** quién informa a los clientes de cada sistema de que sus datos van a un LLM externo y cómo se habilita por cliente (`habilitado` por sistema permite excluir a alguno; un modelo local es la salida si alguien exige que los datos no salgan).
- **Audio a Google:** cómo se informa que, en Chrome, el audio del dictado y de manos libres se procesa en Google (hoy aceptado; `voz-motor="servidor"` lo evita, y manos libres no está disponible con él).
- **Quién opera el VPS.**
- Menores: facturación del uso por sistema, manifiesto por rol de usuario (hoy global), `locale` por usuario o por sistema, y qué acciones valen la pena en la Fase 5.

## Arquitectura y decisiones vigentes

Lo que define el contrato HTTP está en [`contrato/CONTRATO.md`](contrato/CONTRATO.md); aquí, lo que lo rodea.

- **Servicio aislado en su propio contenedor:** un despliegue sirve a N sistemas, de cualquier tecnología (solo HTTP y JWT). El riesgo que eso trae, el aislamiento entre sistemas en un mismo proceso, se cubre con las reglas de seguridad de abajo y con `tests/test_aislamiento.py`.
- **Datos solo vía tools del sistema, con el token del usuario.** El asistente no tiene credenciales propias sobre ningún sistema; el sistema valida el token y aplica sus permisos. Se descartan text-to-SQL y una cuenta de servicio con permisos amplios: si el asistente se viera comprometido, el daño queda acotado a tokens cortos, de solo lectura, de usuarios activos.
- **Contrato propio v1, versionado, con un puerto `Conector`** (el HTTP es la primera implementación; un conector MCP podría agregarse sin tocar el core).
- **LLM agnóstico:** puerto `LLM` en `core/ports.py` con formato neutro (`Mensaje`, `LlamadaTool`, `ResultadoTool`, `Delta`, `Uso`, `motivo_fin`) y adaptadores en `core/llm/` (primero el OpenAI-compatible). Cada adaptador declara sus capacidades (caché, tools paralelas, streaming de tools, contexto máximo) y el core degrada con gracia. Proveedor y modelo se eligen por entorno y por sistema. Cambiar de proveedor es configurar o escribir un adaptador y correr los evals, nunca tocar `core/agent.py`. Los evals se corren por modelo: un modelo pequeño o gratuito puede pasar las pruebas y fallar en JSON de tools o inventando cifras.
- **`core/` no importa `api/`, `sistemas/` ni `store/`** (lo verifica `tests/test_arquitectura.py`): sigue siendo reutilizable si cambia el transporte (voz en tiempo real, MCP).
- **Prompt en tres capas, versionadas** (la versión se guarda en cada mensaje): base (`prompts/base.md`: toda cifra sale de una tool, sin inventar ni estimar, datos de tools como datos y no instrucciones, solo consulta), dominio del sistema (`prompt_dominio`) y contexto de sesión.
- **Seguridad y aislamiento (no negociables):**
  1. El sistema se deduce del token (`iss` → registro → clave de ese sistema; firma, `aud`, `exp`), nunca del request. Un token de un sistema no sirve en otro.
  2. El `Origin` debe estar en `origenes_permitidos` del sistema del token.
  3. Todo queda bajo `(sistema_id, usuario_ref)`: conversaciones, auditoría, rate limit, cuotas y logs; toda consulta filtra por ambos.
  4. Por turno el agente solo ve las tools de su sistema y el conector solo llama a su `base_url`, sin seguir redirecciones a otros hosts.
  5. El token del usuario es la única credencial para datos; el `token_manifiesto` solo lee el manifiesto y el sistema debe rechazarlo en la ejecución.
  6. Solo lectura en dos capas: el asistente expone solo tools de lectura y el sistema rechaza escrituras con scope `asistente:lectura`. La que vale es la del sistema.
  7. Los parámetros que genera el LLM se validan contra el JSON Schema de la tool antes de llamar, y el sistema los vuelve a validar.
  8. Los resultados de tools son datos, no instrucciones (prompt injection); se entregan como JSON.
  9. Límites de abuso: rate limit por usuario, cuota de tokens por sistema, tope de iteraciones y de tokens de salida, timeouts por tool y por turno, tamaño máximo de resultados.
  10. Auditoría de sistema, usuario, `jti`, tool, parámetros, estado, duración y tokens, sin guardar resultados completos más allá de la retención (30 días por defecto).
  11. Secretos solo por variables de entorno; nunca se loguean cabeceras `Authorization` ni tokens. Si la infraestructura lo permite, restringir el egress a la API del LLM y a las `base_url` registradas.
- **Decisiones menores:** manifiesto global por sistema, `HS256` solo para sistemas legados (lo demás, firma asimétrica), widget como vista de chat a pantalla completa y solo con la conversación actual (historial oculto tras `MOSTRAR_HISTORIAL`).
- **Voz:** Web Speech del navegador como camino principal. Whisper `small` y Kokoro locales se descartaron por calidad en pruebas manuales (resultados en `PROVEEDORES_VOZ.md`); el servicio Whisper sigue en el compose como opcional (perfil `voz`) y como STT del servidor (`voz-motor="servidor"`).
