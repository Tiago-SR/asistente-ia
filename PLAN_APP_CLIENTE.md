# Plan: apps cliente de Jarvis (escritorio y móvil)

> Estado: **solo análisis, sin decisiones cerradas ni código** (2026-10-13). Origen: `PlataformaJarvisArquitectura.md`
> (app de escritorio, versionado de contratos, distribución). Se retoma al salir de la rama `feature/nuevo-admin-sistema`,
> cuando el panel de administración (`PLAN_PANEL_ADMIN.md`, Fases 1-4) esté cerrado y verificado.
>
> Reglas del proyecto: responder en español, no hacer `git commit` (sugerir el mensaje), consultar al asesor antes de
> decisiones de API pública o difíciles de revertir.

## 1. Objetivo

- App propia de **escritorio** (Windows, macOS, Linux), instalable (no PWA).
- App propia de **móvil** (Android e iOS).
- El **widget web** (`src/asistente/static/widget.js`) se mantiene tal cual para las empresas que quieran incrustarlo.

## 2. Qué cambia al salir del navegador

- **Web Speech API no funciona en las WebView** (Tauri, Electron, Android WebView; en iOS es poco fiable). La voz actual
  depende de ella, así que hay que cambiar de motor fuera del navegador:
  - **Móvil**: reconocimiento nativo (SFSpeechRecognizer en iOS, SpeechRecognizer en Android) con un plugin.
  - **Escritorio**: STT del servidor, que ya existe (`api/voz.py`, `voz-motor="servidor"`). Hoy solo admite el modo
    «tocar»; el modo «libres» necesitaría detección de voz (VAD) en el cliente.
  - **Widget**: sin cambios, sigue con Web Speech del navegador.
- **No hay sesión del sistema de la empresa**: hoy el widget pide el token con `fetch(token-url, { credentials:
  "same-origin" })` (`widget.js:1270` y `:2949`), que funciona porque vive dentro de la página del sistema. Una app propia
  no tiene esas cookies (ver §4).

## 3. Opciones evaluadas

| Opción | Cubre | Reutiliza el widget | Riesgo principal |
|---|---|---|---|
| PWA sobre el widget | escritorio (Chrome/Edge) y Android; iOS limitado | sí | no es app instalable «de verdad»; voz iOS y push limitados |
| **Capacitor (móvil) + Tauri 2 (escritorio)**, mismo bundle web | las 4 plataformas | sí, carga `<asistente-chat>` | dos shells, poco código propio |
| Tauri 2 solo (escritorio + móvil) | las 4 | sí | soporte móvil joven, menos plugins de voz/push |
| React Native/Expo + Electron | las 4 | no (reescribir ~3000 líneas) | dos UIs que mantener |
| Flutter | las 4 | no (reescribir todo) | cambia de stack |
| Electron solo | escritorio | sí | sin móvil; Web Speech no funciona (sin clave de Google); pesa más |

**Recomendación provisional** (aún no decidida): un único cliente web TS/React empaquetado con **Capacitor en móvil** y
**Tauri 2 en escritorio**. El chat es `<asistente-chat>` reutilizado; alrededor van las pantallas nuevas (login,
selector de empresa, ajustes). Capacitor es lo más maduro en iOS/Android (voz, push, Keychain/Keystore); Tauri da
instaladores ligeros. Si el soporte móvil de Tauri madura, se puede simplificar a un solo shell.

## 4. Riesgos y decisiones abiertas

1. **Login y JWT (el mayor; decisión de API pública → consultar al asesor antes de escribir código).**
   Hace falta un flujo nuevo en el contrato: login del sistema → redirect o deep link con código de un solo uso →
   canje por `{token, expira}` más forma de renovarlo. Choca con la regla «token solo en memoria»
   (`contrato/CONTRATO.md` §7). Con app nativa se puede guardar la renovación en Keychain/Keystore; alternativa: un BFF
   que la guarde en nuestro backend. Cada empresa tendría que implementar su parte. **ZetaSoftware** (auth por empresa,
   sin usuarios) no encaja en este flujo.
2. **CORS y orígenes**: `origenes_permitidos` va por sistema (`api/deps.py:52`, `api/cors.py:27`). Las apps usan
   orígenes compartidos (`capacitor://localhost`, `https://localhost`, `tauri://localhost`): hace falta una lista global
   de «orígenes de plataforma». El `Origin` deja de separar empresas; lo que separa es `iss`/`aud` del JWT.
3. **Voz en iOS**: si el reconocimiento nativo falla, queda el STT del servidor (solo «tocar»).
4. **Push**: hoy no hay nada en el backend. Añadir un emisor APNs/FCM; confirmar antes si de verdad hace falta.
5. **Distribución y firma**: cuentas de Apple Developer y Google Play, firma de código en Windows (SmartScreen) y macOS
   (Developer ID + notarización), CI con matriz Windows/macOS/Linux. Apple (guía 4.2) rechaza webs envueltas sin
   funciones nativas: la voz nativa y el push ayudan a justificarla.
6. **Actualizaciones**: escritorio con el plugin *updater* de Tauri (endpoint propio, firmado); móvil por tiendas.
7. **Versionado de contratos** (solo v1 hoy, `manifiesto.py:20`): definir política antes de abrir más clientes.
8. **Roles configurables** del panel, y **baja** de empresas (no hay `DELETE`, solo `habilitado=false`).

## 5. Referencia: Tauri

**Qué es**: framework para empaquetar una UI web como app nativa. Usa la WebView del sistema (WebView2 en Windows,
WKWebView en macOS/iOS, WebKitGTK en Linux, Android WebView) y un núcleo en Rust. Desde la v2 también móvil.

| | Tauri | Electron |
|---|---|---|
| Motor web | WebView del sistema | Chromium incluido |
| Núcleo | Rust | Node.js |
| Instalador | ~3-10 MB | ~80-150 MB |
| Consistencia entre sistemas | varía con la WebView | idéntica |

**Desarrollo**: `npm create tauri-app` (frontend en `src/`, nativo en `src-tauri/`); `npm run tauri dev` levanta Vite con
HMR y abre la ventana nativa; funciones nativas con `#[tauri::command]` invocadas desde TS con `invoke(...)` (para un
chat que habla con el backend por HTTP muchas veces no hace falta Rust); permisos declarados en `tauri.conf.json`
(capabilities); móvil con `tauri android init|dev` y `tauri ios init|dev`. Requiere Rust y las dependencias de cada
sistema (Build Tools en Windows, Xcode en macOS, `webkit2gtk` en Linux, Android Studio/Xcode para móvil).

**Despliegue**: `npm run tauri build` genera el instalador **del sistema en el que se compila** (`.msi`/`.exe`,
`.dmg`/`.app`, `.deb`/`.rpm`/`.AppImage`, `.apk`/`.aab`, `.ipa`); sin compilación cruzada cómoda, así que se usa CI
(hay acción oficial de GitHub). Firma y notarización como en §4.5. Actualizaciones con el plugin *updater* (JSON con
versión y URL, verificado con clave de firma propia).

## 6. Orden propuesto para validar barato

1. Diseñar el flujo de login/token con el asesor (en papel) y prototiparlo contra el sistema demo STMGIS
   (`localhost:8201`).
2. Prototipo de escritorio: Tauri cargando `<asistente-chat>` con voz del servidor; probar en los tres sistemas.
3. Prototipo de móvil: Capacitor con voz nativa; probar en un iPhone y un Android reales (`Origin` enviado, CORS, voz).
4. Orígenes de plataforma en el registro y `cors.py`; decidir push; preparar distribución y firma.
5. Preguntar a uno o dos clientes si les sirve instalar desde el navegador o exigen instalador, y si necesitan push.

## 7. Pendiente de decidir

- Shell definitivo (Capacitor + Tauri vs. solo Tauri) tras los prototipos.
- Flujo de login y renovación (código + deep link, BFF o Keychain/Keystore).
- Si el modo de voz «libres» es obligatorio en escritorio (VAD en cliente).
- Si hace falta push y en qué plataformas.
