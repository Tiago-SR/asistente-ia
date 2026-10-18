# Auditoría 2026-10-18: Nice to have y notas

La numeración sigue la de los otros dos archivos (esta empieza en el 19).

## 19. Código muerto y dependencias
- **Dónde:**
  - `src/asistente/core/llm/base.py:94-98`: `soporta_cache`, `soporta_streaming_tools` y `contexto_max`, sin lectores en el árbol.
  - `src/asistente/store/metricas.py:99`: `pendientes()`, sin llamadas.
  - `src/asistente/limits.py:103`: escribe tokens diarios por usuario y nada lo lee.
  - `panel/src/components/ui/select.tsx`, `separator.tsx` y `panel/src/lib/utils.ts`: 0 importadores.
  - `panel/package.json:22`: `shadcn` va en `dependencies` y debería ir a dev.
  - `panel/package.json:17`: el paquete npm `cn`; comprobar su procedencia (lo habitual es `clsx` + `tailwind-merge` o una función de 3 líneas).
- **Fix:** borrar lo que no se usa (grep de nuevo antes de borrar).
- **Si no se arregla:** solo hay más código que leer.

## 20. Índices y detalles menores
- Faltan índices para las purgas diarias en `conversaciones(sistema_id, actualizada)` y `contadores_uso(ventana, inicio)` (`store/repo.py:176-185`, `store/resumen.py:81-84`). Va en una migración nueva.
- `store/lectura_metricas.py:98-100` agrupa toda `uso_diario` sin filtrar por sistema. Añadir `WHERE sistema_id = ANY(:ids)`.
- `sistemas/auth.py:154`: `usuario_ref` no tiene tope de longitud (columnas de 256). Rechazar `sub` de más de 240 caracteres.
- Logs de depuración en `static/widget.js` (1098, 1808, 2105, 2152, 2404).
- No existe `.github/`: ningún test ni auditoría de dependencias corre al hacer push.

## Hallazgos menores que quedaron fuera (unos 40)

Medios y bajos, por si hace falta retomarlos:
- **API:** `admin_fallos_ip` crece sin límite (`api/admin.py:226-239`); `/salud` sin auth expone número de sistemas (`main.py:114-133`); `estado.py:20-21` hace un GET al STT en cada carga del widget, sin caché; el email del login fallido se guarda sin normalizar (`admin.py:250`); la docstring de `tools()` está después de un `if` (`admin.py:534`); la caché de LLM guarda claves viejas tras rotar secretos (`servicios.py:112-115`).
- **Store:** el lote de métricas se pierde al cancelar la tarea (`store/metricas.py:102-117`); una conversación borrada durante un turno se recrea (`store/repo.py:127-135`).
- **Core:** `<voz>` de más de 600 caracteres se ve crudo en pantalla (`core/voz_resumen.py:13, 51`); acciones pendientes de un turno cortado (`agent.py:133-137, 228-230`); posible nombre de tool duplicado según el servidor (`llm/openai_compat.py:134-142`, sin verificar con llama-server).
- **Widget:** el foco salta al cargar la página (`widget.js:1332`); blobs de imágenes y caché TTS sin liberar (`:2530, 2565, 2808`); `catch {}` vacío al arrancar (`:1325`); 401 reintentado hasta 4 veces (`:1355, 2594`); el atributo `servidor` acepta `http://` (`:1094`).
- **Panel:** `.catch(() => setManifiestos({}))` esconde errores (`Sistemas.tsx:31`); "Close" sin traducir (`ui/dialog.tsx:75`).
- **Deploy y ejemplos:** `X-Forwarded-For` confiable en rangos privados amplios y whisper/searxng en la misma red que `asistente` (`docker-compose.yml:29, 49, 94, 117`); imágenes sin digest y postgres sin `cap_drop` (`Dockerfile`, `docker-compose.yml`); Caddyfile de ejemplo inconsistente (`deploy/Caddyfile.example:3, 13`); el mock compara tokens con `!=` (`ejemplos/sistema-mock/app.py:324, 331`); el ejemplo PHP ejecuta antes de consumir la propuesta (`AsistenteController.php:63, 195`) y no valida la longitud mínima de la clave (`Config.php:13, 79`).

## Verificado sin hallazgo
- SQL parametrizado en todo el store.
- Cifrado AES-256-GCM con nonce aleatorio, AAD y sin claves en `src/`.
- Sin IDOR entre usuarios ni sistemas.
- Widget sin `innerHTML`; el único `dangerouslySetInnerHTML` del panel usa colores constantes.
- Defensa SSRF sin bypass evidente (pinning por IP, revalidación en redirecciones).
- Tope de memoria con advisory lock.
- Prod con `read_only`, `cap_drop: [ALL]`, `no-new-privileges` y puerto solo en loopback.

## No revisado
- No se ejecutó nada: ni tests, ni `tsc`, ni `npm audit`, ni `docker compose config`, ni pruebas de concurrencia.
- No se leyeron las migraciones 0001-0004 y 0006 (solo grep), `sistemas/registro_bd.py`, `sistemas/cli.py`, `api/confirmaciones.py`, `config/prompts/*.md`, `tests_e2e/`, `evals/correr.py` ni el contenido de `tests/`.
- `herramientas/verificar_sistema.py` solo con grep.
- Partes de `widget.js` (130-500, 545-1000, 1550-2150) y del panel (`Metricas.tsx`, `Cuenta.tsx`, `Usuarios.tsx`).
- Las tools del ejemplo PHP y la validación de parámetros del mock.
- El README menciona un "verificador" (Fase 2) que no se encontró en el código; falta confirmar si es documentación vieja.
