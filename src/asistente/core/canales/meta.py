"""WhatsApp Cloud API (Meta) sin SDK: webhook firmado y cliente de Graph."""

import asyncio
import hashlib
import hmac
import json
from collections.abc import Callable

import httpx

from asistente.core.canales.base import Entrante, ErrorCanal, EstadoEnvio
from asistente.core.canales.config import SECRETOS_CANAL, CanalMetaConfig

GRAPH = "https://graph.facebook.com"
MAX_TEXTO = 4096
_REINTENTOS = 2  # sobre 5xx/429/red
_TIPOS = {"text": "texto", "image": "imagen", "document": "documento", "interactive": "boton", "button": "boton"}
_ESTADOS = {"sent": "enviado", "delivered": "entregado", "read": "leido", "failed": "fallido"}


class CanalMeta:
    def __init__(self, cfg: CanalMetaConfig, token: str, app_secret: str, verify_token: str,
                 http: httpx.AsyncClient | None = None, *, timeout_s: float = 20.0, espera_s: float = 1.0) -> None:
        self._cfg = cfg
        self._token, self._app_secret, self._verify = token, app_secret, verify_token
        self._base = f"{GRAPH}/{cfg.graph_version}"
        self._http = http or httpx.AsyncClient(follow_redirects=False)
        self._timeout = httpx.Timeout(timeout_s, connect=5.0)
        self._espera = espera_s

    @classmethod
    def crear(cls, cfg: CanalMetaConfig, secreto: Callable[[str], str | None],
              http: httpx.AsyncClient | None) -> "CanalMeta | None":
        """None si faltan secretos: el canal queda inactivo (el webhook responde 403), sin tumbar el sistema."""
        valores = [secreto(c) for c in SECRETOS_CANAL["meta"]]
        return cls(cfg, *valores, http) if all(valores) else None  # type: ignore[arg-type]

    # --- webhook ---
    def verificar_suscripcion(self, params: dict[str, str]) -> str | None:
        if params.get("hub.mode") == "subscribe" and hmac.compare_digest(
                params.get("hub.verify_token", ""), self._verify):
            return params.get("hub.challenge", "")
        return None

    def autenticar(self, url: str, cuerpo: bytes, headers: dict[str, str]) -> bool:
        """`X-Hub-Signature-256: sha256=<hex>` = HMAC-SHA256 del cuerpo crudo con el App Secret."""
        cab = headers.get("x-hub-signature-256", "")
        esperado = hmac.new(self._app_secret.encode(), cuerpo, hashlib.sha256).hexdigest()
        return cab.startswith("sha256=") and hmac.compare_digest(cab[7:], esperado)

    def parsear(self, cuerpo: bytes) -> tuple[list[Entrante], list[EstadoEnvio]]:
        """Tolera cualquier forma. Descarta lo que no sea de nuestro `phone_number_id`: el webhook es por App y una
        App compartida entregaría los números de otros sistemas."""
        entrantes: list[Entrante] = []
        estados: list[EstadoEnvio] = []
        try:
            payload = json.loads(cuerpo)
        except ValueError:
            return entrantes, estados
        for entry in payload.get("entry") or [] if isinstance(payload, dict) else []:
            for change in (entry.get("changes") or []) if isinstance(entry, dict) else []:
                value = change.get("value") if isinstance(change, dict) else None
                if not isinstance(value, dict):
                    continue
                meta = value.get("metadata")
                if not isinstance(meta, dict) or meta.get("phone_number_id") != self._cfg.phone_number_id:
                    continue
                entrantes += [e for m in value.get("messages") or [] if (e := _entrante(m))]
                estados += [e for s in value.get("statuses") or [] if (e := _estado(s))]
        return entrantes, estados

    # --- Graph ---
    async def _llamar(self, metodo: str, url: str, **kw) -> httpx.Response:
        for intento in range(_REINTENTOS + 1):
            try:
                r = await self._http.request(
                    metodo, url, headers={"Authorization": f"Bearer {self._token}"}, timeout=self._timeout, **kw)
            except httpx.HTTPError as e:
                if intento == _REINTENTOS:
                    raise ErrorCanal(f"Graph inaccesible: {type(e).__name__}") from e
            else:
                if (r.status_code != 429 and r.status_code < 500) or intento == _REINTENTOS:
                    break
            await asyncio.sleep(self._espera * 2**intento)
        if r.status_code >= 400:
            err = {}
            try:
                err = r.json().get("error") or {}
            except ValueError:
                pass
            # El cuerpo enviado no se reproduce nunca; el mensaje de Meta no lleva datos del usuario.
            raise ErrorCanal(f"Graph HTTP {r.status_code}: {str(err.get('message', ''))[:200]}",
                             estado=r.status_code, codigo=err.get("code"))
        return r

    async def _json(self, metodo: str, url: str, **kw) -> dict:
        r = await self._llamar(metodo, url, **kw)
        try:
            datos = r.json()
        except ValueError as e:
            raise ErrorCanal("Graph devolvió una respuesta inválida") from e
        if not isinstance(datos, dict):
            raise ErrorCanal("Graph devolvió una respuesta inválida")
        return datos

    async def enviar_texto(self, contacto: str, texto: str) -> str:
        d = await self._json("POST", f"{self._base}/{self._cfg.phone_number_id}/messages", json={
            "messaging_product": "whatsapp", "to": contacto, "type": "text",
            "text": {"body": texto[:MAX_TEXTO], "preview_url": False}})
        try:
            return d["messages"][0]["id"]
        except (KeyError, IndexError, TypeError) as e:
            raise ErrorCanal("Graph no devolvió el id del mensaje") from e

    async def descargar_medio(self, ref: str, max_bytes: int) -> tuple[bytes, str]:
        """Dos pasos: la info del medio y su URL (dura ~5 min, mismo `Authorization`).
        shortcut: valida el tamaño después de bajar, no en streaming; pasar a streaming si se admiten medios grandes."""
        info = await self._json("GET", f"{self._base}/{ref}")
        if int(info.get("file_size") or 0) > max_bytes or not info.get("url"):
            raise ErrorCanal("medio demasiado grande o sin URL")
        r = await self._llamar("GET", info["url"])
        if len(r.content) > max_bytes:
            raise ErrorCanal("medio demasiado grande")
        if info.get("sha256") and hashlib.sha256(r.content).hexdigest() != info["sha256"]:
            raise ErrorCanal("el medio no coincide con su sha256")
        return r.content, str(info.get("mime_type", ""))

    async def probar(self) -> dict:
        d = await self._json("GET", f"{self._base}/{self._cfg.phone_number_id}",
                             params={"fields": "display_phone_number,verified_name"})
        return {"numero": d.get("display_phone_number"), "nombre": d.get("verified_name")}


def _entrante(m: object) -> Entrante | None:
    if not isinstance(m, dict) or not m.get("id") or not m.get("from"):
        return None
    t = m.get("type")
    tipo = _TIPOS.get(t, "otro")
    medio = m.get(t) if isinstance(m.get(t), dict) else {}
    boton = (medio.get("button_reply") or {}) if t == "interactive" else {}
    ctx = m.get("context")
    return Entrante(
        id=str(m["id"]), contacto=str(m["from"])[:32], tipo=tipo,
        texto=(medio.get("body") or medio.get("caption")) if t in ("text", "image", "document") else None,
        medio_ref=medio.get("id") if t in ("image", "document") else None,
        mime=medio.get("mime_type") if t in ("image", "document") else None,
        respuesta_a=ctx.get("id") if isinstance(ctx, dict) else None,
        boton_id=boton.get("id"))


def _estado(s: object) -> EstadoEnvio | None:
    if not isinstance(s, dict) or not s.get("id"):
        return None
    err = (s.get("errors") or [{}])[0]
    return EstadoEnvio(id=str(s["id"]), estado=_ESTADOS.get(s.get("status"), "otro"),
                       codigo_error=err.get("code") if isinstance(err, dict) else None)
