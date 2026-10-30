"""OpenWA (WhatsApp Web autoalojado): webhook firmado con HMAC y REST con `X-API-Key`. Solo texto e imágenes entrantes.

Los formatos salen del código de OpenWA v0.26.0 (IncomingMessage, `type` = text|image|document...), no de capturas reales: verificar con un webhook real."""

import hashlib
import hmac
import json
import re
from collections.abc import Callable
from urllib.parse import quote

import httpx

from asistente.core.canales.base import Entrante, ErrorCanal, EstadoEnvio
from asistente.core.canales.config import SECRETOS_CANAL, CanalOpenWAConfig

MAX_TEXTO = 4096
_TIPOS = {"text": "texto", "image": "imagen", "document": "documento"}
_SUFIJO = re.compile(r"@(c\.us|lid)$")


class CanalOpenWA:
    def __init__(self, cfg: CanalOpenWAConfig, api_key: str, webhook_secret: str,
                 http: httpx.AsyncClient | None = None, *, timeout_s: float = 20.0) -> None:
        self._cfg = cfg
        self._api_key, self._secret = api_key, webhook_secret
        self._base = f"{cfg.base_url.rstrip('/')}/api/sessions/{cfg.session_id}"
        self._http = http or httpx.AsyncClient(follow_redirects=False)
        self._timeout = httpx.Timeout(timeout_s, connect=5.0)

    @classmethod
    def crear(cls, cfg: CanalOpenWAConfig, secreto: Callable[[str], str | None],
              http: httpx.AsyncClient | None) -> "CanalOpenWA | None":
        """None si falta algún secreto. Sin `webhook_secret` OpenWA no firma: ese canal no se activa."""
        valores = [secreto(c) for c in SECRETOS_CANAL["openwa"]]
        return cls(cfg, *valores, http) if all(valores) else None  # type: ignore[arg-type]

    # --- webhook ---
    def verificar_suscripcion(self, params: dict[str, str]) -> str | None:
        return None  # OpenWA no hace handshake GET

    def autenticar(self, url: str, cuerpo: bytes, headers: dict[str, str]) -> bool:
        """`X-OpenWA-Signature: sha256=<hex>` = HMAC-SHA256 del cuerpo crudo con el secret del webhook."""
        cab = headers.get("x-openwa-signature", "")
        esperado = hmac.new(self._secret.encode(), cuerpo, hashlib.sha256).hexdigest()
        return cab.startswith("sha256=") and hmac.compare_digest(cab[7:].encode(), esperado.encode())

    def parsear(self, cuerpo: bytes) -> tuple[list[Entrante], list[EstadoEnvio]]:
        """Solo `message.received` de nuestra sesión, de un chat individual, no propio y con teléfono resoluble.
        Grupos, estados, canales y `@lid` sin `senderPhone` se ignoran (para el vínculo hace falta el teléfono)."""
        try:
            p = json.loads(cuerpo)
        except ValueError:
            return [], []
        d = p.get("data") if isinstance(p, dict) else None
        if (not isinstance(d, dict) or p.get("event") != "message.received"
                or p.get("sessionId") != self._cfg.session_id or d.get("fromMe") or d.get("isGroup")
                or not d.get("id")):
            return [], []
        chat = str(d.get("chatId") or d.get("from") or "")
        if chat.endswith("@c.us"):
            contacto = chat[:-5]
        elif chat.endswith("@lid"):
            contacto = str(d.get("senderPhone") or "")
        else:
            return [], []
        contacto = _SUFIJO.sub("", contacto).lstrip("+")
        if not contacto.isdigit():
            return [], []
        media = d.get("media") if isinstance(d.get("media"), dict) else {}
        return [Entrante(
            id=str(d["id"]), contacto=contacto[:32], tipo=_TIPOS.get(d.get("type"), "otro"),
            texto=d.get("body") or None, medio_ref=f"{chat}/{d['id']}" if media else None,
            mime=media.get("mimetype"))], []

    # --- REST ---
    async def _llamar(self, metodo: str, url: str, **kw) -> httpx.Response:
        # shortcut: sin reintentos (uso de pruebas y cobertura básica); copiar los de CanalMeta si se usa en serio.
        try:
            r = await self._http.request(metodo, url, headers={"X-API-Key": self._api_key},
                                         timeout=self._timeout, **kw)
        except httpx.HTTPError as e:
            raise ErrorCanal(f"OpenWA inaccesible: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise ErrorCanal(f"OpenWA HTTP {r.status_code}", estado=r.status_code)
        return r

    async def _json(self, metodo: str, url: str, **kw) -> dict:
        r = await self._llamar(metodo, url, **kw)
        try:
            datos = r.json()
        except ValueError as e:
            raise ErrorCanal("OpenWA devolvió una respuesta inválida") from e
        if not isinstance(datos, dict):
            raise ErrorCanal("OpenWA devolvió una respuesta inválida")
        return datos

    async def enviar_texto(self, contacto: str, texto: str) -> str:
        d = await self._json("POST", f"{self._base}/messages/send-text",
                             json={"chatId": f"{contacto}@c.us", "text": texto[:MAX_TEXTO]})
        if not d.get("messageId"):
            raise ErrorCanal("OpenWA no devolvió el id del mensaje")
        return str(d["messageId"])

    async def enviar_botones(self, contacto: str, cuerpo: str, botones: list[tuple[str, str]]) -> str:
        raise ErrorCanal("OpenWA no admite botones")

    async def descargar_medio(self, ref: str, max_bytes: int) -> tuple[bytes, str]:
        chat, _, mid = ref.partition("/")
        r = await self._llamar("GET", f"{self._base}/messages/{quote(chat, safe='')}/{quote(mid, safe='')}/media")
        if len(r.content) > max_bytes:
            raise ErrorCanal("medio demasiado grande")
        return r.content, r.headers.get("content-type", "").split(";")[0]

    async def probar(self) -> dict:
        d = await self._json("GET", self._base)
        if d.get("status") != "ready":
            raise ErrorCanal(f"sesión {d.get('status')}")
        return {"numero": None, "nombre": f"sesión {self._cfg.session_id} lista"}
