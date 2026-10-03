import json

import httpx
import pytest

from asistente.core.llm.base import LlamadaTool, LLMError, Mensaje, ToolDef
from asistente.core.llm.openai_compat import OpenAICompat, _traducir


def sse(*eventos: dict | str) -> bytes:
    return "".join(
        f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n" for e in eventos
    ).encode()


def adaptador(cuerpo: bytes, status: int = 200, capturar: list | None = None) -> OpenAICompat:
    def handler(request: httpx.Request) -> httpx.Response:
        if capturar is not None:
            capturar.append(json.loads(request.content))
        return httpx.Response(status, content=cuerpo)

    return OpenAICompat("http://llm/v1", cliente=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def chunk(delta: dict, fin: str | None = None) -> dict:
    return {"choices": [{"delta": delta, "finish_reason": fin}]}


async def llamar(llm, **kw):
    deltas: list[str] = []

    async def on_delta(t):
        deltas.append(t)

    r = await llm.stream(
        modelo="m", system="s", tools=kw.get("tools", []), messages=[Mensaje("user", "hola")],
        max_tokens=50, on_delta=on_delta,
    )
    return r, deltas


async def test_texto_en_streaming_e_ignora_razonamiento():
    llm = adaptador(sse(
        chunk({"reasoning_content": "pienso..."}),
        chunk({"content": "Ho"}),
        chunk({"content": "la"}, "stop"),
        {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}},
        "[DONE]",
    ))
    r, deltas = await llamar(llm)
    assert deltas == ["Ho", "la"]
    assert r.texto == "Hola" and r.motivo_fin == "fin"
    assert (r.uso.tokens_in, r.uso.tokens_out) == (7, 3)
    assert "pienso" not in r.texto


async def test_tool_calls_fragmentadas_y_en_paralelo():
    llm = adaptador(sse(
        chunk({"tool_calls": [{"index": 0, "id": "c0", "function": {"name": "lista", "arguments": ""}}]}),
        chunk({"tool_calls": [{"index": 1, "id": "c1", "function": {"name": "resumen", "arguments": '{"id"'}}]}),
        chunk({"tool_calls": [{"index": 1, "function": {"arguments": ': "1"}'}}]}),
        chunk({}, "tool_calls"),
        "[DONE]",
    ))
    r, _ = await llamar(llm)
    assert r.motivo_fin == "tool"
    assert r.llamadas == (LlamadaTool("c0", "lista", {}), LlamadaTool("c1", "resumen", {"id": "1"}))


async def test_argumentos_que_no_son_objeto_se_marcan():
    llm = adaptador(sse(
        chunk({"tool_calls": [{"index": 0, "id": "c", "function": {"name": "t", "arguments": "[1]"}}]}, "tool_calls"),
        "[DONE]",
    ))
    r, _ = await llamar(llm)
    assert r.llamadas[0].argumentos_invalidos


async def test_limite_de_longitud():
    r, _ = await llamar(adaptador(sse(chunk({"content": "x"}, "length"), "[DONE]")))
    assert r.motivo_fin == "limite"


async def test_peticion_incluye_tools_y_system():
    capt: list = []
    tools = [ToolDef("lista", "d", {"type": "object", "properties": {}})]
    await llamar(adaptador(sse(chunk({"content": "ok"}, "stop"), "[DONE]"), capturar=capt), tools=tools)
    cuerpo = capt[0]
    assert cuerpo["stream"] is True and cuerpo["messages"][0] == {"role": "system", "content": "s"}
    assert cuerpo["tools"][0]["function"]["name"] == "lista"


async def test_http_error_no_filtra_secretos():
    with pytest.raises(LLMError, match="HTTP 500"):
        await llamar(adaptador(b"boom", status=500))


async def test_error_de_red():
    def handler(request):
        raise httpx.ConnectError("x")

    llm = OpenAICompat("http://llm/v1", cliente=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(LLMError, match="red"):
        await llamar(llm)


def test_traduccion_de_historial_con_tools():
    msgs = [
        Mensaje("user", "q"),
        Mensaje("assistant", "", (LlamadaTool("c", "t", {"a": 1}),)),
        Mensaje("tool", '{"ok": true}', llamada_id="c"),
        Mensaje("assistant", "listo"),
    ]
    t = _traducir(msgs)
    assert t[1]["tool_calls"][0]["function"]["arguments"] == '{"a": 1}' and t[1]["content"] is None
    assert t[2] == {"role": "tool", "tool_call_id": "c", "content": '{"ok": true}'}
    assert t[3] == {"role": "assistant", "content": "listo"}
