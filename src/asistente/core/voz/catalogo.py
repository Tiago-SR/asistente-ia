"""Catálogo de voces del servidor (`config/voces.yaml`).

Cada voz tiene un `id` propio y estable (el que ve el widget y guarda el usuario), una etiqueta, un género y el
`voice_id` del proveedor, que nunca sale del servidor. El `voice_id` se escribe en el archivo (`voz_id`) o se
toma de una variable de entorno (`voz_id_env`). Una voz sin `voice_id` se ignora (queda como pendiente), así no
se ofrece una voz que fallaría.

Sin archivo, la voz única es `TTS_VOZ_ID` (el comportamiento de antes).
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

GENEROS = ("femenina", "masculina")
ID_DEFECTO = "defecto"


@dataclass(frozen=True)
class Voz:
    id: str
    etiqueta: str
    genero: str | None
    voz_id: str  # del proveedor: no se expone


@dataclass(frozen=True)
class CatalogoVoces:
    voces: tuple[Voz, ...] = ()
    defecto: str | None = None

    def __bool__(self) -> bool:
        return bool(self.voces)

    def resolver(self, id_: str | None) -> Voz | None:
        """La voz pedida; si falta o ya no existe, la predeterminada (nunca un error: una voz retirada no deja mudo a nadie)."""
        por_id = {v.id: v for v in self.voces}
        return por_id.get(id_ or "") or por_id.get(self.defecto or "") or (self.voces[0] if self.voces else None)

    def publico(self) -> list[dict]:
        return [{"id": v.id, "etiqueta": v.etiqueta, "genero": v.genero} for v in self.voces]


def _voz(e: object, env: dict[str, str]) -> Voz | None:
    if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not e["id"].strip():
        log.warning("voces.yaml: entrada sin id, se ignora")
        return None
    id_ = e["id"].strip()
    voz_id = str(e.get("voz_id") or "").strip() or env.get(str(e.get("voz_id_env") or ""), "").strip()
    if not voz_id:
        log.info("voz %r sin voice_id (pendiente): no se ofrece", id_)
        return None
    genero = e.get("genero")
    if genero is not None and genero not in GENEROS:
        log.warning("voz %r: género %r no válido (%s), se ofrece sin género", id_, genero, "/".join(GENEROS))
        genero = None
    return Voz(id_, str(e.get("etiqueta") or id_).strip() or id_, genero, voz_id)


def cargar(ruta: str | Path, voz_id_unica: str | None = None, env: dict[str, str] | None = None) -> CatalogoVoces:
    """Sin archivo: una sola voz, `voz_id_unica` (TTS_VOZ_ID), o ninguna. Con archivo manda el archivo."""
    env = os.environ if env is None else env
    p = Path(ruta)
    if not p.is_file():
        return CatalogoVoces((Voz(ID_DEFECTO, "Voz del servidor", None, voz_id_unica),), ID_DEFECTO) if voz_id_unica else CatalogoVoces()
    datos = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    voces: list[Voz] = []
    for e in datos.get("voces") or []:
        v = _voz(e, env)
        if v and all(v.id != o.id for o in voces):
            voces.append(v)
    defecto = datos.get("defecto")
    if voces and defecto not in {v.id for v in voces}:
        if defecto:
            log.warning("voces.yaml: la voz predeterminada %r no está disponible; se usa %r", defecto, voces[0].id)
        defecto = voces[0].id
    return CatalogoVoces(tuple(voces), defecto if voces else None)
