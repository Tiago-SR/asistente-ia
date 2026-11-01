# Cómo leer el contrato (para un LLM)

Implementas el lado del **sistema anfitrión**. No implementes nada del asistente (chat, webhook, SSE, widget).
Orden de lectura según la tarea; en cada caso, `openapi.yaml` y `schemas/` son la fuente de verdad de campos y
códigos, y los `.md` explican reglas y motivos. Si un `.md` y un schema discrepan, gana el schema: avisa de la
discrepancia en lugar de elegir en silencio.

| Tarea | Lee, en este orden |
|---|---|
| Solo lectura (token, manifiesto, tools) | `IMPLEMENTAR.md` etapa 1 → `CONTRATO.md` §1–§4 → `GUIA_TOOLS.md` → `openapi.yaml` |
| Escrituras con confirmación | lo anterior + `CONTRATO.md` §8 → `IMPLEMENTAR.md` etapa 2 → `schemas/propuesta-respuesta.schema.json` |
| Canal WhatsApp (OpenWA o Meta) | lo de lectura + `CONTRATO.md` §9 → `CANAL_WHATSAPP.md` (completo) → rutas `/asistente/canal/*` de `openapi.yaml` → claim `canal` en `schemas/token-claims.schema.json` |

Cosas que suelen salir mal:

- «`canal`» significa dos cosas: el claim/campo `"whatsapp"` del canal de mensajería, y `"voz"` en `POST /v1/chat`
  (del asistente). Para ti sólo importa el primero.
- Con WhatsApp, un `404` en `/asistente/canal/token` es definitivo para el asistente: no lo uses para errores
  propios (usa `5xx`).
- Para el sistema, «destructiva» es sólo la bandera `destructiva` del manifiesto.
- El contrato es el mismo con OpenWA y con Meta; no construyas endpoints distintos por proveedor.
- Termina con `python herramientas/verificar_sistema.py` (ver `CONTRATO.md` §6.5). Esa herramienta no cubre el canal
  WhatsApp: para el canal, verifica los casos C1–C11 de `CANAL_WHATSAPP.md` §9 contra los requisitos `CAN-xx` de §1.1.
