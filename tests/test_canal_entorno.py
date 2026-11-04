"""Verifica la marca de entorno en los payloads enviados a WhatsApp."""

import json

import httpx
import pytest

from asistente.core.canales.config import CanalMetaConfig, CanalOpenWAConfig
from asistente.core.canales.meta import CanalMeta
from asistente.core.canales.openwa import CanalOpenWA


@pytest.mark.parametrize("entorno,prefijo", [
    (None, "[DEV] "), ("dev", "[DEV] "), ("staging", "[DEV] "),
    ("prod", ""), ("production", ""), ("produccion", ""), (" PROD ", ""),
])
async def test_marca_en_payloads(monkeypatch, entorno, prefijo):
    if entorno is None:
        monkeypatch.delenv("ASISTENTE_ENTORNO", raising=False)
    else:
        monkeypatch.setenv("ASISTENTE_ENTORNO", entorno)
    enviados = []

    def responder(request):
        enviados.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "m"}], "messageId": "m"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
        meta = CanalMeta(CanalMetaConfig(proveedor="meta", phone_number_id="12345"),
                         "token", "secret", "verify", http)
        openwa = CanalOpenWA(CanalOpenWAConfig(
            proveedor="openwa", base_url="http://openwa", session_id="test"),
            "key", "secret", http)
        await meta.enviar_texto("12345", "Hola")
        await meta.enviar_botones("12345", "Confirmar", [("id", "Sí")])
        await openwa.enviar_texto("12345", "Hola")
        await openwa.enviar_documento("12345", b"archivo", "reporte.xlsx", "application/octet-stream")
        assert enviados[0]["text"]["body"] == prefijo + "Hola"
        assert enviados[1]["interactive"]["body"]["text"] == prefijo + "Confirmar"
        assert enviados[1]["interactive"]["action"]["buttons"][0]["reply"]["id"] == "id"
        assert enviados[2]["text"] == prefijo + "Hola"
        assert enviados[3]["filename"] == prefijo + "reporte.xlsx"
        await meta.enviar_texto("12345", "x" * 5000)
        await meta.enviar_botones("12345", "x" * 2000, [])
        await openwa.enviar_texto("12345", "x" * 5000)
        assert len(enviados[4]["text"]["body"]) == 4096
        assert len(enviados[5]["interactive"]["body"]["text"]) == 1024
        assert len(enviados[6]["text"]) == 4096
