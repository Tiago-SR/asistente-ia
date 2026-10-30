# ruff: noqa: F811  (se reutilizan fixtures de test_api.py por importación)
"""Canal de mensajería (strategy): proveedor Meta, fábrica por sistema y webhook."""

import hashlib
import hmac
import json
import time
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
from test_api import construir_app, llm, sesiones, sub  # noqa: F401  (fixtures por importación)

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
        if req.url.path.endswith("/111"):
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/x", "mime_type": "image/png"})
        return httpx.Response(200, content=b"x" * 10)

    assert await _canal(h).descargar_medio("111", 10) == (b"x" * 10, "image/png")
    with pytest.raises(ErrorCanal):
        await _canal(h).descargar_medio("111", 5)


async def test_medio_con_ref_o_host_ajeno_no_recibe_el_bearer():
    vistos = []

    def h(req):
        vistos.append(str(req.url))
        return httpx.Response(200, json={"url": "https://evil.example/x", "mime_type": "image/png"})

    with pytest.raises(ErrorCanal):
        await _canal(h).descargar_medio("111", 10)  # URL fuera de Meta
    with pytest.raises(ErrorCanal):
        await _canal(h).descargar_medio("../me", 10)  # ref no numérica
    assert len(vistos) == 1  # solo la consulta de info; nada llegó a evil.example


def test_firma_y_verify_token_no_ascii_no_lanzan():
    c = _canal()
    assert c.autenticar("", b"{}", {"x-hub-signature-256": "sha256=ñ"}) is False
    assert c.verificar_suscripcion({"hub.mode": "subscribe", "hub.verify_token": "ñ"}) is None


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
    d = {"id": "3EB0A1", "chatId": "59899111222@c.us", "from": "59899111222@c.us", "body": "hola", "type": "text",
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


def test_openwa_admite_acciones_y_valida_url():
    assert CanalOpenWAConfig(proveedor="openwa", base_url="http://x", session_id="s", acciones=("crear_nota",))
    with pytest.raises(ValueError):
        CanalOpenWAConfig(proveedor="openwa", base_url="ftp://x", session_id="s")
    assert secretos_canal({"canal_mensajeria": {"proveedor": "openwa"}}) == ("owa_api_key", "owa_webhook_secret")


async def test_privacidad_es_publica_y_muestra_el_contacto(wa):
    r = await wa.get("/privacidad")
    assert r.status_code == 200 and "eliminación de datos" in r.text and "operador" in r.text
    wa._transport.app.state.servicios.settings.contacto_privacidad = "a@b.c<x>"
    assert "mailto:a@b.c&lt;x&gt;" in (await wa.get("/privacidad")).text  # escapado


# --- flujo: vincular y turno ---

class _Salida:
    def __init__(self, tiene_botones=True):
        self.tiene_botones = tiene_botones
        self.enviados, self.botones = [], []

    async def enviar_texto(self, contacto, texto):
        self.enviados.append((contacto, texto))
        return "wamid.out" + uuid.uuid4().hex

    async def enviar_botones(self, contacto, cuerpo, botones):
        self.botones.append((contacto, cuerpo, {t: i for i, t in botones}))
        return "wamid.btn" + uuid.uuid4().hex


@pytest.fixture
async def flujo(wa, sesiones, monkeypatch, llm):
    from asistente.api import canal_flujo
    from asistente.store.canal import VinculosCanal
    from conftest import firmar

    svc = wa._transport.app.state.servicios
    svc.canal_vinculos = VinculosCanal(sesiones)
    llamadas, vinculados = [], {"59899111222": "ana"}

    def sistema(req):
        llamadas.append(req.url.path)
        cuerpo = json.loads(req.content)
        assert req.headers["Authorization"] == "Bearer tc"
        if req.url.path.endswith("/vincular"):
            ok = cuerpo["codigo"] == "FST-BUENO"
            if ok:
                vinculados[cuerpo["wa_id"]] = "ana"
            return httpx.Response(200, json={"ok": True, "nombre": "Ana"}) if ok else httpx.Response(404)
        sub = vinculados.get(cuerpo["wa_id"])
        if sub and "confirmacion" in cuerpo:  # token de escritura atado a esa confirmación
            return httpx.Response(200, json={"token": firmar(
                "mock-a", sub, canal="whatsapp", scope="asistente:escritura", exp=int(time.time()) + 30,
                act="agregar_nota", ph=cuerpo["huella"], cid=cuerpo["confirmacion"])})
        return httpx.Response(200, json={"token": firmar("mock-a", sub, canal="whatsapp")}) if sub else httpx.Response(404)

    svc.http = httpx.AsyncClient(transport=httpx.MockTransport(sistema))
    secreto = svc.registro.secreto
    monkeypatch.setattr(svc.registro, "secreto", lambda sid, c: {"token_canal": "tc", "wa_app_secret": SECRETO}.get(c)
                        or secreto(sid, c))
    monkeypatch.setattr(canal_flujo.random, "uniform", lambda a, b: 0)
    salida = _Salida()
    yield svc, salida, llamadas, vinculados, llm


def _msg(texto, contacto="59899111222", tipo="texto"):
    from asistente.core.canales.base import Entrante
    return Entrante(id="w" + uuid.uuid4().hex, contacto=contacto, tipo=tipo, texto=texto)


async def test_sin_vinculo_silencio_y_sin_llamar_al_sistema(flujo):
    from asistente.api.canal_flujo import procesar
    svc, salida, llamadas, _, _ = flujo
    await procesar(svc, "mock-a", salida, _msg("hola"))
    await procesar(svc, "mock-a", salida, _msg("VINCULAR MALO", "59800000000"))
    assert salida.enviados == [] and llamadas == ["/asistente/canal/vincular"]


async def test_vincular_y_preguntar(flujo):
    from asistente.api.canal_flujo import ACUSES, procesar
    from asistente.core.llm.falso import texto
    svc, salida, _, _, llm = flujo
    await procesar(svc, "mock-a", salida, _msg("vincular FST-BUENO", "59877777777"))
    assert "vinculado" in salida.enviados[-1][1] and await svc.canal_vinculos.activo("mock-a", "59877777777")
    llm.usar(texto("Tenés 3 campos"))
    salida.enviados.clear()
    await procesar(svc, "mock-a", salida, _msg("¿cuántos campos tengo?", "59877777777"))
    assert [t for _, t in salida.enviados][1:] == ["Tenés 3 campos"] and salida.enviados[0][1] in ACUSES


async def test_vinculo_revocado_en_el_sistema_se_desactiva(flujo):
    from asistente.api.canal_flujo import procesar
    svc, salida, _, _, _ = flujo
    await svc.canal_vinculos.guardar("mock-a", "59855555555")  # vínculo local sin respaldo en el sistema
    await procesar(svc, "mock-a", salida, _msg("hola", "59855555555"))
    assert salida.enviados == [] and not await svc.canal_vinculos.activo("mock-a", "59855555555")


async def test_vinculado_con_imagen_recibe_aviso(flujo):
    from asistente.api.canal_flujo import SOLO_TEXTO, procesar
    svc, salida, _, _, _ = flujo
    await svc.canal_vinculos.guardar("mock-a", "59899111222")
    await procesar(svc, "mock-a", salida, _msg(None, tipo="imagen"))
    assert salida.enviados == [("59899111222", SOLO_TEXTO)]


async def test_token_sin_claim_canal_no_sirve_en_el_canal(flujo, monkeypatch):
    from asistente.api.canal_flujo import procesar
    from conftest import firmar
    svc, salida, _, _, _ = flujo
    await svc.canal_vinculos.guardar("mock-a", "59899111222")
    web = firmar("mock-a", "ana")  # token del widget: sin claim `canal`
    svc.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"token": web})))
    await procesar(svc, "mock-a", salida, _msg("hola"))
    assert salida.enviados == []
    with pytest.raises(Exception, match="canal"):
        await svc.autenticador.validar(firmar("mock-a", "ana", canal="whatsapp"))  # y al revés


# --- confirmación con botón ---

@pytest.fixture
async def escribe(flujo, mock_a, monkeypatch):
    """El sistema `mock-a` con `agregar_nota` encendida para el canal, y un usuario vinculado con su dato."""
    svc, salida, _, vinculados, llm = flujo
    actual = svc.registro.obtener("mock-a")
    con_canal = actual.model_copy(update={
        "acciones_habilitadas": ("agregar_nota",),
        "canal_mensajeria": CanalMetaConfig(proveedor="meta", phone_number_id=NUM, acciones=("agregar_nota",))})
    monkeypatch.setattr(svc.registro, "obtener", lambda sid: con_canal if sid == "mock-a" else None)
    u = sub()
    mock_a.DATOS[u] = [{"id": "1", "nombre": "El Matorral", "superficie_ha": 10.0, "cultivo": "soja"}]
    mock_a.NOTAS[u] = []
    vinculados["59899111222"] = u
    await svc.canal_vinculos.guardar("mock-a", "59899111222")
    return svc, salida, llm, mock_a, u


async def _proponer(escribe, texto_nota="Helada"):
    from asistente.api.canal_flujo import procesar
    from asistente.core.llm.base import LlamadaTool
    from asistente.core.llm.falso import pide, texto
    svc, salida, llm, _, _ = escribe
    llm.usar(pide(LlamadaTool("c1", "agregar_nota", {"establecimiento_id": "1", "texto": texto_nota})),
             texto("Te pedí confirmar."))
    await procesar(svc, "mock-a", salida, _msg("anotá una helada"))
    return salida.botones[-1][2]


def _boton(id_, contacto="59899111222"):
    from asistente.core.canales.base import Entrante
    return Entrante(id="w" + uuid.uuid4().hex, contacto=contacto, tipo="boton", boton_id=id_)


async def test_propuesta_sale_con_botones_y_confirmar_la_ejecuta_una_sola_vez(escribe):
    from asistente.api.canal_flujo import VENCIDA, procesar
    svc, salida, _, mock_a, u = escribe
    botones = await _proponer(escribe)
    assert set(botones) == {"Confirmar", "Cancelar"} and mock_a.NOTAS[u] == []  # proponer no escribe
    assert "El Matorral" in salida.botones[-1][1] and "Helada" in salida.botones[-1][1]  # el resumen es del sistema
    await procesar(svc, "mock-a", salida, _boton(botones["Confirmar"]))
    assert [n["texto"] for n in mock_a.NOTAS[u]] == ["Helada"]
    await procesar(svc, "mock-a", salida, _boton(botones["Confirmar"]))  # reintento de Meta o doble toque
    assert len(mock_a.NOTAS[u]) == 1 and salida.enviados[-1][1] == VENCIDA


async def test_cancelar_no_escribe(escribe):
    from asistente.api.canal_flujo import procesar
    svc, salida, _, mock_a, u = escribe
    botones = await _proponer(escribe)
    await procesar(svc, "mock-a", salida, _boton(botones["Cancelar"]))
    assert mock_a.NOTAS[u] == [] and "cancelado" in salida.enviados[-1][1]


async def test_boton_falsificado_o_de_otro_numero_se_ignora(escribe):
    from asistente.api.canal_flujo import procesar
    svc, salida, _, mock_a, u = escribe
    botones = await _proponer(escribe)
    antes = len(salida.enviados)
    id_ = botones["Confirmar"]
    await svc.canal_vinculos.guardar("mock-a", "59800000001")
    await procesar(svc, "mock-a", salida, _boton(id_[:-1] + ("0" if id_[-1] != "0" else "1")))  # firma alterada
    await procesar(svc, "mock-a", salida, _boton(id_, "59800000001"))  # firma de otro número
    await procesar(svc, "mock-a", salida, _boton("ok:basura"))
    assert mock_a.NOTAS[u] == [] and len(salida.enviados) == antes


async def test_sin_acciones_para_el_canal_no_hay_botones(flujo, mock_a):
    from asistente.api.canal_flujo import procesar
    from asistente.core.llm.base import LlamadaTool
    from asistente.core.llm.falso import pide, texto
    svc, salida, _, _, llm = flujo
    await svc.canal_vinculos.guardar("mock-a", "59899111222")
    llm.usar(pide(LlamadaTool("c1", "agregar_nota", {"establecimiento_id": "1", "texto": "x"})), texto("No puedo."))
    await procesar(svc, "mock-a", salida, _msg("anotá algo"))
    assert salida.botones == []


# --- registro de salidas y estados ---

async def test_salidas_fallidas_se_guardan_con_su_codigo(sesiones):
    from datetime import UTC, datetime, timedelta
    m = MensajesCanal(sesiones)
    await m.registrar_salida("mock-a", "w.out1", "59899111222", "texto")
    await m.actualizar_estado("mock-a", "w.out1", "fallido", "131047")
    await m.registrar_salida("mock-a", "w.out2", "59899111222", "texto")
    await m.actualizar_estado("mock-a", "w.out2", "entregado")
    f = await m.fallidos("mock-a", datetime.now(UTC) - timedelta(hours=1))
    assert [(x.id, x.error) for x in f] == [("w.out1", "131047")]


def test_a_whatsapp_tabla_encabezados_y_negrita():
    from asistente.core.formato_whatsapp import a_whatsapp
    md = ("## Resumen\n**Total:** 660 ha\n\n| Campo | Ha | Cultivo |\n|---|---|---|\n| El Matorral | 540 | Soja |\n"
          "| San Pedro | 120 | Maíz |\n\n* ver [mapa](https://x.uy/m)\n```\n| a | b |\n```")
    assert a_whatsapp(md) == ("*Resumen*\n*Total:* 660 ha\n\n- El Matorral: Ha 540, Cultivo Soja\n- San Pedro: Ha 120, Cultivo Maíz\n\n"
                              "- ver mapa (https://x.uy/m)\n```\n| a | b |\n```")
    assert a_whatsapp("| Campo | Ha |\n|---|---|\n| El Matorral | 540 |") == "- El Matorral: 540"


# --- confirmación por código (canales sin botones, p. ej. OpenWA) ---

async def _proponer_codigo(escribe):
    import re
    salida = escribe[1]
    salida.tiene_botones = False
    await _proponer_texto(escribe)
    return re.search(r"CONFIRMAR (\w{5}) o CANCELAR", salida.enviados[-1][1])[1]


async def _proponer_texto(escribe):
    from asistente.api.canal_flujo import procesar
    from asistente.core.llm.base import LlamadaTool
    from asistente.core.llm.falso import pide, texto
    svc, salida, llm, _, _ = escribe
    llm.usar(pide(LlamadaTool("c1", "agregar_nota", {"establecimiento_id": "1", "texto": "Helada"})),
             texto("Te pedí confirmar."))
    await procesar(svc, "mock-a", salida, _msg("anotá una helada"))


async def test_codigo_confirma_una_sola_vez_y_no_llega_al_modelo(escribe):
    from asistente.api.canal_flujo import VENCIDA, procesar
    svc, salida, llm, mock_a, u = escribe
    cod = await _proponer_codigo(escribe)
    assert salida.botones == [] and mock_a.NOTAS[u] == []
    antes = len(llm.actual.llamadas)
    await procesar(svc, "mock-a", salida, _msg(f"confirmar {cod.lower()}"))
    assert [n["texto"] for n in mock_a.NOTAS[u]] == ["Helada"]
    await procesar(svc, "mock-a", salida, _msg(f"CONFIRMAR {cod}"))
    assert len(mock_a.NOTAS[u]) == 1 and salida.enviados[-1][1] == VENCIDA
    assert len(llm.actual.llamadas) == antes  # ni la confirmación ni el reintento llamaron al modelo


async def test_codigo_cancelar_incorrecto_o_ajeno_no_escribe(escribe):
    from asistente.api.canal_flujo import VENCIDA, procesar
    svc, salida, _, mock_a, u = escribe
    cod = await _proponer_codigo(escribe)
    await svc.canal_vinculos.guardar("mock-a", "59800000001")
    await procesar(svc, "mock-a", salida, _msg("CONFIRMAR AAAAA"))
    assert salida.enviados[-1][1] == VENCIDA and mock_a.NOTAS[u] == []
    await procesar(svc, "mock-a", salida, _msg(f"CONFIRMAR {cod}", "59800000001"))  # código de otro número
    assert mock_a.NOTAS[u] == []
    await procesar(svc, "mock-a", salida, _msg(f"cancelar {cod}"))
    assert mock_a.NOTAS[u] == [] and "cancelado" in salida.enviados[-1][1]
    await procesar(svc, "mock-a", salida, _msg(f"CONFIRMAR {cod}"))  # ya cancelada
    assert mock_a.NOTAS[u] == []


async def test_confirmar_sin_codigo_va_al_modelo_y_no_ejecuta(escribe):
    from asistente.api.canal_flujo import procesar
    svc, salida, llm, mock_a, u = escribe
    await _proponer_codigo(escribe)
    from asistente.core.llm.falso import texto
    llm.usar(texto("Necesito el código."))
    await procesar(svc, "mock-a", salida, _msg("sí, confirmar"))
    assert mock_a.NOTAS[u] == []


def test_acuse_varia_y_saluda_solo_tras_una_pausa():
    from asistente.api.canal_flujo import ACUSES, _acuse
    assert {_acuse("Ana", None, False) for _ in range(100)} == set(ACUSES)
    con = _acuse("Ana María", "UTC", True)
    assert con.startswith(("Buen día, Ana.", "Buenas tardes, Ana.", "Buenas noches, Ana.")) and con.split(". ", 1)[1] in ACUSES
    assert _acuse(None, None, True).split(". ", 1)[0] in ("Buen día", "Buenas tardes", "Buenas noches")


async def test_lecturas_bloqueadas_no_se_ofrecen_por_el_canal():
    from asistente.api.canal_flujo import _ConectorCanal
    from asistente.core.llm.base import ToolDef

    class Base:
        async def tools(self):
            return [ToolDef(nombre=n, descripcion="", parametros={}, escritura=e) for n, e in
                    (("ver_a", False), ("ver_b", False), ("anotar", True))]

    c = _ConectorCanal(Base(), frozenset({"anotar"}), frozenset({"ver_b"}))
    assert [t.nombre for t in await c.tools()] == ["ver_a", "anotar"]
