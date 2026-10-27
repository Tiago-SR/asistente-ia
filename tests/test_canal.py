# ruff: noqa: F811  (se reutilizan fixtures de test_api.py por importación)
"""Canal de mensajería (strategy): proveedor Meta, fábrica por sistema y webhook."""

import hashlib
import hmac
import json
import uuid

import httpx
import pytest

from asistente.core import canales
from asistente.core.canales.base import ErrorCanal
from asistente.core.canales.config import CanalMetaConfig, CanalOpenWAConfig
from asistente.core.canales.meta import CanalMeta
from asistente.core.canales.openwa import CanalOpenWA
from asistente.sistemas.registro import Sistema, secretos_canal
from asistente.store.canal import MensajesCanal
from conftest import entorno, entrada_sistema, escribir_registro, registro_desde_yaml
from test_api import construir_app, llm, sesiones  # noqa: F401  (fixtures por importación)

SECRETO = "app-secret-de-prueba"
NUM = "1234567890"
CFG = CanalMetaConfig(proveedor="meta", phone_number_id=NUM)


def _canal(handler=None) -> CanalMeta:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler)) if handler else None
    return CanalMeta(CFG, "tok", SECRETO, "verifica", http, espera_s=0)


def _firma(cuerpo: bytes, secreto=SECRETO) -> dict:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()}


def _payload(wamid=None, numero=NUM, **value) -> bytes:
    wamid = wamid or f"wamid.{uuid.uuid4().hex}"
    value = {"metadata": {"phone_number_id": numero},
             "messages": [{"id": wamid, "from": "59899111222", "type": "text", "text": {"body": "hola"}}], **value}
    return json.dumps({"entry": [{"changes": [{"value": value}]}]}).encode()


# --- fábrica / strategy ---

def test_fabrica_sin_canal_o_sin_secretos_es_none(tmp_path):
    ruta = escribir_registro(tmp_path / "s.yaml", [
        entrada_sistema("a"), entrada_sistema("b", canal_mensajeria={"proveedor": "meta", "phone_number_id": NUM})])
    reg = registro_desde_yaml(ruta, env=entorno("a", "b"))
    assert reg.obtener("a").canal_mensajeria is None and reg.obtener("b").canal_mensajeria == CFG
    assert canales.para(None, {}.get, None) is None
    assert canales.para(CFG, {"wa_token": "t"}.get, None) is None
    completo = {"wa_token": "t", "wa_app_secret": "a", "wa_verify_token": "v"}
    assert isinstance(canales.para(CFG, completo.get, None), CanalMeta)


def test_secretos_dependen_del_proveedor():
    assert secretos_canal({}) == ()
    assert secretos_canal({"canal_mensajeria": {"proveedor": "meta"}}) == ("wa_token", "wa_app_secret", "wa_verify_token")


def test_proveedor_desconocido_se_rechaza():
    with pytest.raises(ValueError):
        Sistema.model_validate({**entrada_sistema("a"), "canal_mensajeria": {"proveedor": "otro", "phone_number_id": NUM}})


# --- proveedor Meta ---

def test_parsear_filtra_numero_ajeno_y_mapea():
    c = _canal()
    ent, _ = c.parsear(_payload())
    assert [(e.tipo, e.texto) for e in ent] == [("texto", "hola")]
    assert c.parsear(_payload(numero="999999"))[0] == []
    _, est = c.parsear(_payload(statuses=[{"id": "w9", "status": "failed", "errors": [{"code": 131047}]}]))
    assert (est[0].estado, est[0].codigo_error) == ("fallido", 131047)
    assert c.parsear(b"no es json") == ([], [])


def test_boton_trae_respuesta_a():
    m = {"id": "w2", "from": "598", "type": "interactive", "context": {"id": "wamid.tarjeta"},
         "interactive": {"button_reply": {"id": "ok:cid:n"}}}
    cuerpo = json.dumps({"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": NUM}, "messages": [m]}}]}]}).encode()
    e = _canal().parsear(cuerpo)[0][0]
    assert (e.tipo, e.respuesta_a, e.boton_id) == ("boton", "wamid.tarjeta", "ok:cid:n")


async def test_enviar_texto_corta_y_devuelve_id():
    vistos = []

    def h(req):
        vistos.append((req.headers["authorization"], json.loads(req.content)))
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})

    assert await _canal(h).enviar_texto("598", "x" * 5000) == "wamid.1"
    assert vistos[0][0] == "Bearer tok" and len(vistos[0][1]["text"]["body"]) == 4096


async def test_reintenta_5xx_y_tipa_el_error():
    n = []

    def h(req):
        n.append(1)
        return httpx.Response(500) if len(n) < 3 else httpx.Response(
            400, json={"error": {"code": 131047, "message": "fuera de ventana"}})

    with pytest.raises(ErrorCanal) as e:
        await _canal(h).enviar_texto("598", "hola")
    assert len(n) == 3 and e.value.codigo == 131047


async def test_medio_demasiado_grande():
    def h(req):
        if req.url.path.endswith("/m1"):
            return httpx.Response(200, json={"url": "https://m/x", "mime_type": "image/png"})
        return httpx.Response(200, content=b"x" * 10)

    assert await _canal(h).descargar_medio("m1", 10) == (b"x" * 10, "image/png")
    with pytest.raises(ErrorCanal):
        await _canal(h).descargar_medio("m1", 5)


# --- webhook ---

@pytest.fixture
async def wa(construir_app, sesiones, monkeypatch):
    async with construir_app() as c:
        svc = c._transport.app.state.servicios
        svc.canal_mensajes = MensajesCanal(sesiones)
        monkeypatch.setattr("asistente.api.canal.canal_de",
                            lambda svc, sid, habilitado=True: _canal() if sid == "mock-a" else None)
        yield c


async def test_verificacion_get(wa):
    p = {"hub.mode": "subscribe", "hub.challenge": "1234"}
    r = await wa.get("/canal/mock-a/webhook", params={**p, "hub.verify_token": "verifica"})
    assert r.status_code == 200 and r.text == "1234"
    assert (await wa.get("/canal/mock-a/webhook", params={**p, "hub.verify_token": "otro"})).status_code == 403


async def test_sistema_sin_canal_o_inexistente_da_la_misma_403(wa):
    cuerpo = _payload()
    for sid in ("mock-b", "no-existe"):
        r = await wa.post(f"/canal/{sid}/webhook", content=cuerpo, headers=_firma(cuerpo))
        assert r.status_code == 403 and r.json() == (await wa.post("/canal/x/webhook", content=cuerpo)).json()


async def test_post_firma_mala_o_ausente(wa):
    cuerpo = _payload()
    assert (await wa.post("/canal/mock-a/webhook", content=cuerpo)).status_code == 403
    assert (await wa.post("/canal/mock-a/webhook", content=cuerpo, headers=_firma(cuerpo, "x"))).status_code == 403


async def test_duplicado_se_procesa_una_vez(wa, monkeypatch):
    vistos = []

    async def falso(svc, sid, canal, m):
        vistos.append(m.id)

    monkeypatch.setattr("asistente.api.canal.procesar", falso)
    cuerpo = _payload("wamid.dup")
    for _ in range(2):
        assert (await wa.post("/canal/mock-a/webhook", content=cuerpo, headers=_firma(cuerpo))).status_code == 200
    assert vistos == ["wamid.dup"]


async def test_numero_ajeno_estado_y_basura(wa, monkeypatch):
    vistos = []

    async def falso(svc, sid, canal, m):
        vistos.append(m.id)

    monkeypatch.setattr("asistente.api.canal.procesar", falso)
    ajeno = _payload("wamid.9", numero="999999")
    assert (await wa.post("/canal/mock-a/webhook", content=ajeno, headers=_firma(ajeno))).status_code == 200
    estado = _payload(statuses=[{"id": "w9", "status": "failed", "errors": [{"code": 131047}]}])
    assert (await wa.post("/canal/mock-a/webhook", content=estado, headers=_firma(estado))).status_code == 200
    ruido = b"no es json"
    assert (await wa.post("/canal/mock-a/webhook", content=ruido, headers=_firma(ruido))).status_code == 200
    assert len(vistos) == 1 and vistos[0] != "wamid.9"  # solo el del payload de `estado`; el ajeno no entra


# --- proveedor OpenWA ---

OWA = CanalOpenWAConfig(proveedor="openwa", base_url="http://openwa:2785", session_id="s1")


def _owa(handler=None) -> CanalOpenWA:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler)) if handler else None
    return CanalOpenWA(OWA, "key", "secreto", http)


def _owa_payload(**data) -> bytes:
    d = {"id": "3EB0A1", "chatId": "59899111222@c.us", "from": "59899111222@c.us", "body": "hola", "type": "chat",
         "fromMe": False, "isGroup": False, **data}
    return json.dumps({"event": "message.received", "sessionId": "s1", "data": d}).encode()


def test_openwa_firma_y_sin_secret_no_se_activa():
    c = _owa()
    cuerpo = b"{}"
    ok = {"x-openwa-signature": "sha256=" + hmac.new(b"secreto", cuerpo, hashlib.sha256).hexdigest()}
    assert c.autenticar("", cuerpo, ok) and not c.autenticar("", cuerpo, {}) and c.verificar_suscripcion({}) is None
    assert CanalOpenWA.crear(OWA, {"owa_api_key": "k"}.get, None) is None
    assert CanalOpenWA.crear(OWA, {"owa_api_key": "k", "owa_webhook_secret": "s"}.get, None) is not None


def test_openwa_parsear_filtros():
    c = _owa()
    e = c.parsear(_owa_payload())[0]
    assert [(x.id, x.contacto, x.tipo, x.texto) for x in e] == [("3EB0A1", "59899111222", "texto", "hola")]
    for malo in (_owa_payload(fromMe=True), _owa_payload(isGroup=True), _owa_payload(chatId="1-2@g.us"),
                 _owa_payload(chatId="status@broadcast"), _owa_payload(chatId="123@lid"), b"x", b"[]",
                 _owa_payload().replace(b'"s1"', b'"otra"')):
        assert c.parsear(malo) == ([], [])
    lid = c.parsear(_owa_payload(chatId="123@lid", senderPhone="+59899111222"))[0]
    assert lid[0].contacto == "59899111222"
    img = c.parsear(_owa_payload(type="image", media={"mimetype": "image/jpeg"}))[0][0]
    assert (img.tipo, img.mime, img.medio_ref) == ("imagen", "image/jpeg", "59899111222@c.us/3EB0A1")


async def test_openwa_enviar_probar_y_medio():
    vistos = []

    def h(req):
        vistos.append((req.method, req.url.path, req.headers["x-api-key"]))
        if req.url.path.endswith("/send-text"):
            assert json.loads(req.content) == {"chatId": "598@c.us", "text": "hola"}
            return httpx.Response(201, json={"messageId": "m1", "timestamp": 1})
        if req.url.path.endswith("/media"):
            return httpx.Response(200, content=b"img", headers={"content-type": "image/png; x=1"})
        return httpx.Response(200, json={"status": "qr_ready"})

    c = _owa(h)
    assert await c.enviar_texto("598", "hola") == "m1"
    assert await c.descargar_medio("598@c.us/m1", 10) == (b"img", "image/png")
    assert vistos[1][1] == "/api/sessions/s1/messages/598@c.us/m1/media"  # httpx devuelve el path decodificado
    with pytest.raises(ErrorCanal, match="qr_ready"):
        await c.probar()


def test_openwa_es_solo_lectura_y_url_valida():
    with pytest.raises(ValueError):
        CanalOpenWAConfig(proveedor="openwa", base_url="http://x", session_id="s", acciones=("crear_nota",))
    with pytest.raises(ValueError):
        CanalOpenWAConfig(proveedor="openwa", base_url="ftp://x", session_id="s")
    assert secretos_canal({"canal_mensajeria": {"proveedor": "openwa"}}) == ("owa_api_key", "owa_webhook_secret")
