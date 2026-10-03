"""Adaptador para cualquier endpoint `/v1/chat/completions` con streaming y tools.

Probado contra llama-server (Qwen). El razonamiento del modelo (`reasoning_content`)
se ignora a propósito: no se muestra, no se guarda y no se reenvía.
"""

import json
import logging
from collections.abc import AsyncIterator

import httpx

from asistente.core.llm.base import (
    Capacidades,
    LlamadaTool,
    LLMError,
    Mensaje,
    MotivoFin,
    OnDelta,
    Respuesta,
    ToolDef,
    Uso,
)

log = logging.getLogger(__name__)

_MOTIVOS: dict[str | None, MotivoFin] = {"tool_calls": "tool", "function_call": "tool", "length": "limite"}


class OpenAICompat:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        cliente: httpx.AsyncClient | None = None,
        timeout_s: float = 120.0,
        contexto_max: int | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        # Sin timeout de lectura global: un stream largo es normal; se acota por chunk.
        self._cliente = cliente or httpx.AsyncClient(follow_redirects=False)
        self._timeout = httpx.Timeout(timeout_s, connect=10.0)
        self.capacidades = Capacidades(contexto_max=contexto_max)

    async def stream(
        self,
        *,
        modelo: str,
        system: str,
        tools: list[ToolDef],
        messages: list[Mensaje],
        max_tokens: int,
        on_delta: OnDelta | None = None,
    ) -> Respuesta:
        cuerpo: dict = {
            "model": modelo,
            "messages": [{"role": "system", "content": system}, *_traducir(messages)],
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            cuerpo["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.nombre, "description": t.descripcion, "parameters": t.parametros},
                }
                for t in tools
            ]
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        texto: list[str] = []
        parciales: dict[int, dict] = {}
        motivo: str | None = None
        uso = Uso()
        try:
            async with self._cliente.stream(
                "POST", self._url, json=cuerpo, headers=headers, timeout=self._timeout
            ) as r:
                if r.status_code != 200:
                    detalle = (await r.aread()).decode(errors="replace")[:300]
                    raise LLMError(f"el proveedor respondió HTTP {r.status_code}: {detalle}")
                async for evento in _eventos(r):
                    if evento.get("usage"):
                        u = evento["usage"]
                        uso = Uso(u.get("prompt_tokens") or 0, u.get("completion_tokens") or 0)
                    for ch in evento.get("choices") or []:
                        delta = ch.get("delta") or {}
                        if frag := delta.get("content"):
                            texto.append(frag)
                            if on_delta:
                                await on_delta(frag)
                        for tc in delta.get("tool_calls") or []:
                            _acumular(parciales, tc)
                        motivo = ch.get("finish_reason") or motivo
        except httpx.HTTPError as e:
            raise LLMError(f"fallo de red con el proveedor: {type(e).__name__}") from e

        llamadas = tuple(_cerrar(i, p) for i, p in sorted(parciales.items()))
        fin: MotivoFin = "tool" if llamadas else _MOTIVOS.get(motivo, "fin")
        return Respuesta("".join(texto), llamadas, fin, uso)


async def _eventos(r: httpx.Response) -> AsyncIterator[dict]:
    async for linea in r.aiter_lines():
        if not linea.startswith("data:"):
            continue
        dato = linea[5:].strip()
        if dato == "[DONE]":
            return
        try:
            yield json.loads(dato)
        except ValueError as e:
            raise LLMError("el proveedor envió un evento SSE que no es JSON") from e


def _acumular(parciales: dict[int, dict], tc: dict) -> None:
    p = parciales.setdefault(tc.get("index", 0), {"id": "", "nombre": "", "args": ""})
    if tc.get("id"):
        p["id"] = tc["id"]
    fn = tc.get("function") or {}
    if fn.get("name"):
        p["nombre"] += fn["name"]
    if fn.get("arguments"):
        p["args"] += fn["arguments"]


def _cerrar(indice: int, p: dict) -> LlamadaTool:
    id_ = p["id"] or f"call_{indice}"
    try:
        args = json.loads(p["args"]) if p["args"].strip() else {}
    except ValueError:
        args = None
    if not isinstance(args, dict):
        return LlamadaTool(id_, p["nombre"], {}, argumentos_invalidos=True)
    return LlamadaTool(id_, p["nombre"], args)


def _traducir(mensajes: list[Mensaje]) -> list[dict]:
    salida: list[dict] = []
    for m in mensajes:
        if m.rol == "tool":
            salida.append({"role": "tool", "tool_call_id": m.llamada_id, "content": m.texto})
        elif m.rol == "assistant" and m.llamadas:
            salida.append(
                {
                    "role": "assistant",
                    "content": m.texto or None,
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.nombre, "arguments": json.dumps(c.parametros)},
                        }
                        for c in m.llamadas
                    ],
                }
            )
        else:
            salida.append({"role": m.rol, "content": m.texto})
    return salida
