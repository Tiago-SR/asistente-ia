"""API /v1/* de punta a punta: mocks en memoria, LLM falso y Postgres real."""

import asyncio
import json
import os
import uuid
from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from asistente.config import Settings
from asistente.core.llm.base import LlamadaTool, Mensaje, Respuesta
from asistente.core.llm.falso import LLMFalso, pide, texto
from asistente.core.prompts import Prompts
from asistente.limits import LimitesPostgres
from asistente.main import create_app
from asistente.servicios import LLMNoConfigurado, Servicios
from asistente.sistemas.auth import Autenticador
from asistente.sistemas.conector_http import ConectorHttp
from asistente.sistemas.manifiesto import CacheManifiestos
from asistente.sistemas.registro import RegistroSistemas
from asistente.store.acciones import AccionesSql
from asistente.store.auditoria import AuditoriaSql
from asistente.store.memoria import MemoriaSql
from asistente.store.models import Base, UsoModelo, UsoVoz
from asistente.store.models import LlamadaTool as FilaLlamada
from asistente.store.recientes import RecientesSql
from asistente.store.repo import Repo, recortar
from conftest import entorno, entrada_sistema, escribir_registro, firmar

URL = os.environ.get("ASISTENTE_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sin ASISTENTE_DATABASE_URL")

ORIGEN_A, ORIGEN_B = "https://a.example", "https://b.example"
LISTAR = LlamadaTool("c1", "listar_establecimientos", {})


def sub() -> str:
    return "u" + uuid.uuid4().hex[:10]


def sse(resp: httpx.Response) -> list[tuple[str, dict]]:
    eventos = []
    for bloque in resp.text.split("\n\n"):
        lineas = [x for x in bloque.split("\n") if x and not x.startswith(":")]
        if lineas:
            eventos.append((lineas[0].removeprefix("event: "), json.loads(lineas[1].removeprefix("data: "))))
    return eventos


class LLMMutable:
    """Permite cambiar el guion del LLM falso entre peticiones de un mismo test."""

    def __init__(self):
        self.actual = LLMFalso([])
        self.capacidades = self.actual.capacidades

    def usar(self, *guion) -> LLMFalso:
        self.actual = LLMFalso(list(guion))
        return self.actual

    async def stream(self, **kw):
        return await self.actual.stream(**kw)


@pytest.fixture
async def sesiones():
    motor = create_async_engine(URL)
    async with motor.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(motor, expire_on_commit=False)
    await motor.dispose()


@pytest.fixture
def llm():
    return LLMMutable()


@pytest.fixture
def construir_app(tmp_path, cliente_mocks, sesiones, llm):
    def _construir(heartbeat_s=15.0, admin_token=None, llm_ok=True, limites=None, llm_obj=None, stt=None, tts=None,
                   acciones_habilitadas=(), max_acciones_hora=20, precios_path="/no/existe.yaml",
                   consultas_recientes=True, memoria_habilitada=False, memoria_dias=30, nombre_asistente=None, voces=None):
        (tmp_path / "base.md").write_text("Reglas base.", encoding="utf-8")
        (tmp_path / "voz.md").write_text("Resumen hablado.", encoding="utf-8")
        topes = limites or {"mensajes_por_usuario_min": 1000, "mensajes_por_usuario_dia": 1000}
        ruta = escribir_registro(tmp_path / "s.yaml", [
            entrada_sistema("mock-a", origenes_permitidos=[ORIGEN_A], limites=topes,
                            acciones_habilitadas=list(acciones_habilitadas),
                            consultas_recientes=consultas_recientes, memoria_habilitada=memoria_habilitada,
                            **({"nombre_asistente": nombre_asistente} if nombre_asistente else {})),
            entrada_sistema("mock-b", origenes_permitidos=[ORIGEN_B], limites=topes,
                            memoria_habilitada=memoria_habilitada),
        ])
        registro = RegistroSistemas(ruta, env=entorno("mock-a", "mock-b"))
        manifiestos = CacheManifiestos(registro, cliente_mocks)

        def llm_para(sistema):
            if not llm_ok:
                raise LLMNoConfigurado("sin llm")
            return (llm_obj or llm), "modelo-test"

        svc = Servicios(
            settings=Settings(database_url=URL, heartbeat_s=heartbeat_s, admin_token=admin_token,
                              precios_path=precios_path),
            registro=registro, autenticador=Autenticador(registro), manifiestos=manifiestos,
            conector=ConectorHttp(registro, manifiestos, cliente_mocks), repo=Repo(sesiones),
            limites=LimitesPostgres(sesiones), auditoria=AuditoriaSql(sesiones),
            prompts=Prompts(tmp_path), llm_para=llm_para, sesiones=sesiones, stt=stt, tts=tts,
            acciones=AccionesSql(sesiones, max_acciones_hora), recientes=RecientesSql(sesiones),
            memoria=MemoriaSql(sesiones, memoria_dias),
            **({"voces": voces} if voces else {}),
        )
        app = create_app(svc)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://asistente")

    return _construir


@pytest.fixture
async def api(construir_app):
    async with construir_app() as c:
        yield c


def auth(sistema="mock-a", usuario="ana", **kw) -> dict:
    return {"Authorization": f"Bearer {firmar(sistema, usuario, **kw)}"}


async def chatear(api, mensaje="hola", conv=None, **kw):
    cuerpo = {"mensaje": mensaje, **({"conversacion_id": str(conv)} if conv else {})}
    return await api.post("/v1/chat", json=cuerpo, headers=auth(**kw))


# --- flujo feliz -------------------------------------------------------------------------


async def test_chat_con_tool_persiste_y_expone_solo_texto_visible(api, llm):
    guion = llm.usar(pide(LISTAR), texto("Tenés El Matorral"))
    r = await chatear(api, "¿qué campos tengo?")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = sse(r)
    nombres = [e for e, _ in ev]
    assert nombres[0] == "tool" and "ui" in nombres and "delta" in nombres and nombres[-1] == "done"
    conv = ev[-1][1]["conversacion_id"]
    # el modelo recibió los datos reales del sistema y el system prompt compuesto
    assert "El Matorral" in guion.llamadas[1].messages[-1].texto
    assert "Reglas base." in guion.llamadas[0].system and "Mock A" in guion.llamadas[0].system.replace("MOCK-A", "Mock A")

    visibles = (await api.get(f"/v1/conversaciones/{conv}", headers=auth())).json()["mensajes"]
    assert [(m["rol"], m["texto"]) for m in visibles] == [
        ("user", "¿qué campos tengo?"), ("assistant", "Tenés El Matorral"),
    ]
    lista = (await api.get("/v1/conversaciones", headers=auth())).json()
    assert conv in [c["id"] for c in lista]


async def test_segundo_mensaje_recibe_historial_con_resultados_viejos_recortados(api, llm):
    llm.usar(pide(LISTAR), texto("uno"))
    conv = sse(await chatear(api, "primero"))[-1][1]["conversacion_id"]
    guion = llm.usar(texto("dos"))
    assert sse(await chatear(api, "segundo", conv))[-1][0] == "done"
    previos = guion.llamadas[0].messages
    assert [m.rol for m in previos] == ["user", "assistant", "tool", "assistant", "user"]
    assert "El Matorral" not in previos[2].texto  # dato de cliente de un turno viejo


async def test_auditoria_registra_la_tool_con_usuario_y_conversacion(api, llm, sesiones):
    u = sub()
    llm.usar(pide(LISTAR), texto("ok"))
    conv = sse(await chatear(api, usuario=u))[-1][1]["conversacion_id"]
    async with sesiones() as s:
        filas = (await s.execute(select(FilaLlamada).where(FilaLlamada.usuario_ref == u))).scalars().all()
    assert len(filas) == 1
    f = filas[0]
    assert (f.sistema_id, f.tool, f.ok, f.status_http) == ("mock-a", "listar_establecimientos", True, 200)
    assert str(f.conversacion_id) == conv and f.bytes_respuesta


async def test_delete_borra_y_luego_404(api, llm):
    llm.usar(texto("hola"))
    conv = sse(await chatear(api))[-1][1]["conversacion_id"]
    assert (await api.delete(f"/v1/conversaciones/{conv}", headers=auth())).status_code == 204
    assert (await api.delete(f"/v1/conversaciones/{conv}", headers=auth())).status_code == 404
    assert (await api.get(f"/v1/conversaciones/{conv}", headers=auth())).status_code == 404


async def test_estado(api):
    r = await api.get("/v1/estado", headers=auth())
    assert r.json() == {
        "habilitado": True,
        "nombre_sistema": "MOCK-A",
        "nombre_asistente": None,
        "memoria": False,
        "voz": {"dictado": False, "respuesta": False, "max_audio_s": 60},
    }


async def test_estado_informa_el_nombre_del_asistente_del_yaml(construir_app):
    async with construir_app(nombre_asistente="Sofía") as c:
        assert (await c.get("/v1/estado", headers=auth())).json()["nombre_asistente"] == "Sofía"


async def test_estado_informa_dictado_segun_el_stt(construir_app):
    from asistente.core.voz.falso import SttFalso

    for stt, esperado in [(SttFalso(), True), (SttFalso(disponible=False), False), (None, False)]:
        async with construir_app(stt=stt) as c:
            r = await c.get("/v1/estado", headers=auth())
            assert r.json()["voz"] == {"dictado": esperado, "respuesta": False, "max_audio_s": 60}


# --- aislamiento (el hito del punto 5 se apoya acá) -----------------------------------------


async def test_otro_usuario_y_otro_sistema_no_ven_ni_tocan_la_conversacion(api, llm):
    llm.usar(texto("secreto de ana"))
    ana = sub()
    conv = sse(await chatear(api, usuario=ana))[-1][1]["conversacion_id"]
    intrusos = [{"sistema": "mock-a", "usuario": sub()}, {"sistema": "mock-b", "usuario": ana}]
    for i in intrusos:
        h = auth(i["sistema"], i["usuario"])
        assert (await api.get(f"/v1/conversaciones/{conv}", headers=h)).status_code == 404
        assert (await api.delete(f"/v1/conversaciones/{conv}", headers=h)).status_code == 404
        r = await chatear(api, conv=conv, sistema=i["sistema"], usuario=i["usuario"])
        assert r.status_code == 404 and "secreto" not in r.text
        assert conv not in [c["id"] for c in (await api.get("/v1/conversaciones", headers=h)).json()]
    # y a ana no le pasó nada
    assert (await api.get(f"/v1/conversaciones/{conv}", headers=auth(usuario=ana))).status_code == 200


async def test_id_de_conversacion_inexistente_responde_igual_que_uno_ajeno(api):
    r = await chatear(api, conv=uuid.uuid4())
    assert (r.status_code, r.json()) == (404, {"error": "conversacion_no_encontrada"})


# --- autenticación, origen y CORS ------------------------------------------------------------


@pytest.mark.parametrize("ruta", ["/v1/estado", "/v1/conversaciones"])
async def test_sin_token_401(api, ruta):
    r = await api.get(ruta)
    assert r.status_code == 401 and r.json() == {"error": "token_invalido"}


async def test_token_vencido_se_distingue(api):
    r = await api.get("/v1/estado", headers=auth(iat=1, exp=2))
    assert r.status_code == 401 and r.json() == {"error": "token_expirado"}


async def test_origen_debe_pertenecer_al_sistema_del_token(api):
    ok = await api.get("/v1/estado", headers={**auth(), "Origin": ORIGEN_A})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == ORIGEN_A
    cruzado = await api.get("/v1/estado", headers={**auth("mock-a"), "Origin": ORIGEN_B})
    assert cruzado.status_code == 403 and cruzado.json() == {"error": "origen_no_permitido"}
    ajeno = await api.get("/v1/estado", headers={**auth(), "Origin": "https://evil.example"})
    assert ajeno.status_code == 403 and "access-control-allow-origin" not in ajeno.headers


async def test_preflight_solo_para_origenes_registrados(api):
    pre = {"Access-Control-Request-Method": "POST"}
    r = await api.options("/v1/chat", headers={"Origin": ORIGEN_B, **pre})
    assert r.status_code == 204 and r.headers["access-control-allow-origin"] == ORIGEN_B
    r = await api.options("/v1/chat", headers={"Origin": "https://evil.example", **pre})
    assert "access-control-allow-origin" not in r.headers


async def test_preflight_permite_la_cabecera_de_duracion_del_dictado(api):
    """El widget manda X-Audio-Duracion-S desde otro origen: sin esto el navegador bloquea el dictado."""
    r = await api.options("/v1/voz/transcribir", headers={
        "Origin": ORIGEN_B, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type,x-audio-duracion-s",
    })
    permitidas = r.headers["access-control-allow-headers"].lower()
    assert r.status_code == 204 and "x-audio-duracion-s" in permitidas


# --- validaciones y errores ----------------------------------------------------------------------


@pytest.mark.parametrize("mensaje", ["", "   ", "x" * 5000])
async def test_mensaje_invalido_422(api, mensaje):
    r = await chatear(api, mensaje)
    assert (r.status_code, r.json()) == (422, {"error": "mensaje_invalido"})


async def test_llm_sin_configurar_503(construir_app):
    async with construir_app(llm_ok=False) as c:
        r = await chatear(c)
    assert (r.status_code, r.json()) == (503, {"error": "llm_no_configurado"})


async def test_limite_por_minuto_llega_como_evento_de_error(construir_app, llm):
    async with construir_app(limites={"mensajes_por_usuario_min": 1}) as c:
        u = sub()
        llm.usar(texto("a"))
        assert sse(await chatear(c, usuario=u))[-1][0] == "done"
        r = await chatear(c, usuario=u)
    assert sse(r) == [("error", {"codigo": "mensajes_min"})]


async def test_turno_fallido_no_guarda_nada(api, llm):
    def falla(_):
        raise __import__("asistente.core.llm.base", fromlist=["LLMError"]).LLMError("x")

    llm.usar(falla)
    u = sub()
    assert sse(await chatear(api, usuario=u)) == [("error", {"codigo": "llm_no_disponible"})]
    assert (await api.get("/v1/conversaciones", headers=auth(usuario=u))).json() == []


async def test_heartbeat_en_turnos_lentos(construir_app):
    class Lento:
        capacidades = LLMFalso([]).capacidades

        async def stream(self, **kw):
            await asyncio.sleep(0.3)
            return Respuesta("tarde", motivo_fin="fin")

    async with construir_app(heartbeat_s=0.05, llm_obj=Lento()) as c:
        r = await chatear(c)
    assert ": ping" in r.text and sse(r)[-1][0] == "done"


# --- admin ------------------------------------------------------------------------------------


async def test_admin_deshabilitado_sin_token_configurado(api):
    assert (await api.post("/admin/recargar")).status_code == 503


async def test_admin_exige_token_y_reporta_sistemas(construir_app):
    async with construir_app(admin_token="adm1n") as c:
        assert (await c.get("/admin/sistemas", headers={"Authorization": "Bearer mal"})).status_code == 401
        assert (await c.get("/admin/sistemas")).status_code == 401
        h = {"Authorization": "Bearer adm1n"}
        r = (await c.get("/admin/sistemas", headers=h)).json()
        assert {s["id"]: s["manifiesto_ok"] for s in r["sistemas"]} == {"mock-a": True, "mock-b": True}
        assert (await c.post("/admin/recargar", headers=h)).json() == {"sistemas": 2, "errores": {}}


async def test_admin_uso_calcula_el_costo_por_sistema_y_modelo(construir_app, sesiones, tmp_path):
    precios = tmp_path / "precios.yaml"
    precios.write_text("""
m-caro:
  entrada_cache_hit: {valle: 1, pico: 2}
  entrada_cache_miss: {valle: 10, pico: 20}
  salida: {valle: 100, pico: 200}
""", encoding="utf-8")
    mes = datetime(2019, 3, 1, tzinfo=UTC)  # la BD de desarrollo se comparte: un mes que nadie usa
    async with sesiones.begin() as s:
        await s.execute(delete(UsoModelo).where(UsoModelo.mes == mes))
        s.add_all([
            UsoModelo(sistema_id="mock-a", mes=mes, modelo="m-caro", llamadas=3, tokens_in=1_000_000,
                      tokens_in_cache=400_000, tokens_out=10_000),
            UsoModelo(sistema_id="mock-a", mes=mes, modelo="m-local", llamadas=1, tokens_in=5, tokens_out=5,
                      tokens_in_cache=0),
        ])
    async with construir_app(admin_token="adm1n", precios_path=str(precios)) as c:
        h = {"Authorization": "Bearer adm1n"}
        assert (await c.get("/admin/uso")).status_code == 401
        assert (await c.get("/admin/uso?mes=2026-13", headers=h)).status_code == 422
        r = (await c.get("/admin/uso?mes=2019-03", headers=h)).json()
        assert r["mes"] == "2019-03"
        a = next(s for s in r["sistemas"] if s["id"] == "mock-a")
        assert a["nombre"] == "MOCK-A"
        caro = next(m for m in a["modelos"] if m["modelo"] == "m-caro")
        # 600 000 sin caché x 10 + 400 000 con caché x 1 + 10 000 de salida x 100 = 7,4 USD (valle)
        assert caro["costo_usd"]["valle"] == pytest.approx(7.4)
        assert caro["costo_usd"]["pico"] == pytest.approx(14.8)
        assert next(m for m in a["modelos"] if m["modelo"] == "m-local")["costo_usd"] is None
        assert a["sin_tarifa"] == ["m-local"] and a["costo_usd"]["valle"] == pytest.approx(7.4)
        assert (await c.get("/admin/uso?mes=2019-04", headers=h)).json()["sistemas"] == []
        assert (await c.get("/admin/uso", headers=h)).status_code == 200  # mes en curso


async def test_admin_uso_suma_el_costo_de_la_voz_del_servidor(construir_app, sesiones, tmp_path):
    precios = tmp_path / "precios.yaml"
    precios.write_text("""
m-caro:
  entrada_cache_hit: {valle: 1, pico: 2}
  entrada_cache_miss: {valle: 10, pico: 20}
  salida: {valle: 100, pico: 200}
"elevenlabs:con-tarifa": {usd_por_1k_caracteres: 0.04}
""", encoding="utf-8")
    mes = datetime(2019, 5, 1, tzinfo=UTC)  # un mes que nadie usa (la BD de desarrollo se comparte)
    async with sesiones.begin() as s:
        await s.execute(delete(UsoModelo).where(UsoModelo.mes == mes))
        await s.execute(delete(UsoVoz).where(UsoVoz.mes == mes))
        s.add_all([
            UsoModelo(sistema_id="mock-a", mes=mes, modelo="m-caro", llamadas=1, tokens_in=1_000_000,
                      tokens_in_cache=0, tokens_out=0),
            UsoVoz(sistema_id="mock-a", mes=mes, proveedor="elevenlabs", modelo="con-tarifa", llamadas=40,
                   caracteres=50_000),
            UsoVoz(sistema_id="mock-a", mes=mes, proveedor="elevenlabs", modelo="sin-tarifa", llamadas=1,
                   caracteres=10),
            UsoVoz(sistema_id="mock-b", mes=mes, proveedor="elevenlabs", modelo="con-tarifa", llamadas=1,
                   caracteres=1_000),   # un sistema que solo usó voz también aparece
        ])
    async with construir_app(admin_token="adm1n", precios_path=str(precios)) as c:
        r = (await c.get("/admin/uso?mes=2019-05", headers={"Authorization": "Bearer adm1n"})).json()
    a = next(s for s in r["sistemas"] if s["id"] == "mock-a")
    voz = {v["modelo"]: v for v in a["voz"]}
    assert voz["con-tarifa"]["caracteres"] == 50_000 and voz["con-tarifa"]["llamadas"] == 40
    assert voz["con-tarifa"]["costo_usd"] == pytest.approx(2.0)   # 50 x 0,04
    assert voz["sin-tarifa"]["costo_usd"] is None
    assert a["sin_tarifa"] == ["elevenlabs:sin-tarifa"]
    # LLM (10 USD valle / 20 pico) + voz (2 USD en las dos cotas)
    assert a["costo_usd"]["valle"] == pytest.approx(12.0) and a["costo_usd"]["pico"] == pytest.approx(22.0)
    b = next(s for s in r["sistemas"] if s["id"] == "mock-b")
    assert b["modelos"] == [] and b["costo_usd"]["valle"] == pytest.approx(0.04)


async def test_salud_verifica_la_bd(api):
    r = await api.get("/salud")
    assert r.status_code == 200 and r.json() == {"ok": True, "bd": True, "sistemas": 2}


# --- unidades sin red ----------------------------------------------------------------------------


def test_recorte_de_historial_por_turnos():
    def turno(i):
        return [Mensaje("user", f"q{i}"), Mensaje("assistant", "", (LlamadaTool(f"c{i}", "t", {}),)),
                Mensaje("tool", '{"ok": true, "datos": "PRIVADO"}', llamada_id=f"c{i}"),
                Mensaje("assistant", f"a{i}")]

    historial = [m for i in range(4) for m in turno(i)]
    r = recortar(historial, max_turnos=2)
    assert [m.texto for m in r if m.rol == "user"] == ["q2", "q3"]
    assert r[0].rol == "user"  # nunca empieza con una tool huérfana
    assert all("PRIVADO" not in m.texto for m in r)  # ningún resultado viejo sobrevive
    assert [m.llamada_id for m in r if m.rol == "tool"] == ["c2", "c3"]  # pero el emparejamiento sí


def test_prompts_compone_capas_y_versiona(tmp_path):
    (tmp_path / "base.md").write_text("BASE", encoding="utf-8")
    (tmp_path / "dominio").mkdir()
    (tmp_path / "dominio" / "agro.md").write_text("AGRO", encoding="utf-8")
    p = Prompts(tmp_path)
    t, v = p.componer(sistema_nombre="SGA", prompt_dominio=f"{tmp_path.name}/dominio/agro.md",
                      usuario_nombre="Ana", locale="es-AR", hoy=date(2026, 3, 1))
    assert t.index("BASE") < t.index("AGRO") < t.index("2026-03-01") and "Ana" in t
    _, v2 = p.componer(sistema_nombre="SGA", prompt_dominio=None, usuario_nombre=None, locale=None,
                       hoy=date(2026, 3, 1))
    assert v != v2


def test_prompt_dominio_fuera_de_prompts_se_ignora(tmp_path):
    (tmp_path / "base.md").write_text("BASE", encoding="utf-8")
    (tmp_path.parent / "fuera.md").write_text("SECRETO", encoding="utf-8")
    t, _ = Prompts(tmp_path).componer(sistema_nombre="S", prompt_dominio="../fuera.md",
                                      usuario_nombre=None, locale=None, hoy=date(2026, 1, 1))
    assert "SECRETO" not in t


# --- dictado: POST /v1/voz/transcribir --------------------------------------------------------


def voz(stt=None, **kw):
    from asistente.core.voz.falso import SttFalso

    return stt or SttFalso("¿cuántas hectáreas tengo?"), kw


async def dictar(c, audio=b"AUDIO", tipo="audio/webm;codecs=opus", params="", headers=None, **kw):
    h = {**auth(**kw), "Content-Type": tipo, **(headers or {})}
    return await c.post(f"/v1/voz/transcribir{params}", content=audio, headers=h)


async def test_dictado_ok_pasa_tipo_e_idioma(construir_app):
    from asistente.core.voz.falso import SttFalso

    stt = SttFalso("hola mundo")
    async with construir_app(stt=stt) as c:
        r = await dictar(c, params="?idioma=pt", headers={"X-Audio-Duracion-S": "3.5"})
    assert r.status_code == 200 and r.json() == {"texto": "hola mundo"}
    (ll,) = stt.llamadas
    assert (ll.audio, ll.tipo_mime, ll.idioma) == (b"AUDIO", "audio/webm", "pt")


async def test_dictado_exige_token_y_origen(construir_app):
    from asistente.core.voz.falso import SttFalso

    stt = SttFalso()
    async with construir_app(stt=stt) as c:
        r = await c.post("/v1/voz/transcribir", content=b"x", headers={"Content-Type": "audio/webm"})
        assert r.status_code == 401
        r = await dictar(c, headers={"Origin": "https://malo.example"})
        assert r.status_code == 403 and r.json() == {"error": "origen_no_permitido"}
        r = await dictar(c, headers={"Origin": ORIGEN_A})
        assert r.status_code == 200
    assert len(stt.llamadas) == 1


async def test_dictado_sin_stt_es_503(api):
    r = await dictar(api)
    assert r.status_code == 503 and r.json() == {"error": "voz_no_disponible"}


@pytest.mark.parametrize("tipo", ["text/plain", "application/json", "video/mp4"])
async def test_dictado_tipo_no_permitido(construir_app, tipo):
    from asistente.core.voz.falso import SttFalso

    stt = SttFalso()
    async with construir_app(stt=stt) as c:
        r = await dictar(c, tipo=tipo)
    assert r.status_code == 415 and r.json() == {"error": "audio_tipo_no_permitido"} and not stt.llamadas


async def test_dictado_topes_de_tamano_y_duracion(construir_app, monkeypatch):
    from asistente.core.voz.falso import SttFalso

    stt = SttFalso()
    async with construir_app(stt=stt) as c:
        kb = 2048  # valor por defecto
        r = await dictar(c, audio=b"x" * (kb * 1024 + 1))
        assert r.status_code == 413 and r.json() == {"error": "audio_demasiado_grande"}
        r = await dictar(c, audio=b"x" * (kb * 1024))
        assert r.status_code == 200
        r = await dictar(c, headers={"X-Audio-Duracion-S": "61"})
        assert r.status_code == 413 and r.json() == {"error": "audio_demasiado_largo"}
        for malo in ("abc", "nan", "-1"):
            r = await dictar(c, headers={"X-Audio-Duracion-S": malo})
            assert r.status_code == 422, malo
    assert len(stt.llamadas) == 1


async def test_dictado_tamano_sin_content_length_se_corta_leyendo(construir_app):
    from asistente.core.voz.falso import SttFalso

    async def trozos():
        for _ in range(3):
            yield b"x" * (1024 * 1024)

    stt = SttFalso()
    async with construir_app(stt=stt) as c:
        r = await c.post("/v1/voz/transcribir", content=trozos(),
                         headers={**auth(), "Content-Type": "audio/webm"})
    assert r.status_code == 413 and not stt.llamadas


async def test_dictado_cuerpo_vacio_es_422(construir_app):
    from asistente.core.voz.falso import SttFalso

    async with construir_app(stt=SttFalso()) as c:
        r = await dictar(c, audio=b"")
    assert r.status_code == 422 and r.json() == {"error": "audio_invalido"}


async def test_dictado_errores_del_stt(construir_app):
    from asistente.core.voz.base import AudioInvalido
    from asistente.core.voz.falso import SttFalso

    async with construir_app(stt=SttFalso(falla=True)) as c:
        r = await dictar(c)
    assert r.status_code == 502 and r.json() == {"error": "voz_error"}

    class Rechaza(SttFalso):
        async def transcribir(self, *a, **k):
            raise AudioInvalido("no")

    async with construir_app(stt=Rechaza()) as c:
        r = await dictar(c)
    assert r.status_code == 422 and r.json() == {"error": "audio_invalido"}


async def test_dictado_rate_limit_por_usuario_y_aparte_del_chat(construir_app, llm):
    from asistente.core.voz.falso import SttFalso

    u1, u2 = sub(), sub()
    llm.usar(texto("ok"))
    async with construir_app(stt=SttFalso()) as c:
        for _ in range(10):
            assert (await dictar(c, usuario=u1)).status_code == 200
        r = await dictar(c, usuario=u1)
        assert r.status_code == 429 and r.json() == {"error": "limite_excedido"}
        assert (await dictar(c, usuario=u2)).status_code == 200  # otro usuario, otro contador
        # dictar no consume la cuota de mensajes del chat
        assert sse(await chatear(c, usuario=u1))[-1][0] == "done"


# --- canal de voz (resumen hablado; ver tests/test_voz.py) -------------------------------------


async def test_api_canal_voz_manda_evento_voz_guarda_solo_el_texto_completo_y_pide_el_resumen(api, llm):
    guion = llm.usar(pide(LISTAR), texto("<voz>Tenés un establecimiento.</voz>\n\nTenés El Matorral"))
    r = await api.post("/v1/chat", json={"mensaje": "¿qué campos tengo?", "canal": "voz"}, headers=auth())
    assert r.status_code == 200
    ev = sse(r)
    assert ("voz", {"texto": "Tenés un establecimiento."}) in ev
    assert "<voz>" not in "".join(d["texto"] for e, d in ev if e == "delta")
    assert "## Canal de voz" in guion.llamadas[0].system
    conv = ev[-1][1]["conversacion_id"]
    visibles = (await api.get(f"/v1/conversaciones/{conv}", headers=auth())).json()["mensajes"]
    assert visibles[-1]["texto"].strip() == "Tenés El Matorral"


async def test_api_canal_texto_por_defecto_sin_capa_de_voz(api, llm):
    guion = llm.usar(texto("Hola"))
    ev = sse(await api.post("/v1/chat", json={"mensaje": "hola"}, headers=auth()))
    assert not [e for e, _ in ev if e == "voz"]
    assert "Canal de voz" not in guion.llamadas[0].system


@pytest.mark.parametrize("canal", ["radio", 3, None])
async def test_api_canal_desconocido_422(api, canal):
    r = await api.post("/v1/chat", json={"mensaje": "hola", "canal": canal}, headers=auth())
    assert r.status_code == 422


async def test_done_informa_tiempos_en_ms_sin_exponer_datos_internos(api, llm):
    llm.usar(texto("<voz>Hola.</voz>\n\nHola Ana"))
    ev = sse(await api.post("/v1/chat", json={"mensaje": "hola", "canal": "voz"}, headers=auth()))
    tiempos = ev[-1][1]["tiempos_ms"]
    assert {"voz", "primer_delta", "total"} <= tiempos.keys() and all(isinstance(v, int) and v >= 0 for v in tiempos.values())
    assert not [k for k in tiempos if k.startswith("_")]


# --- respuesta hablada: POST /v1/voz/sintetizar ------------------------------------------------


async def sintetizar(c, texto="Hola, tenés 660 hectáreas.", headers=None, usuario=None, **kw):
    h = auth(usuario=usuario) if usuario else auth()
    return await c.post("/v1/voz/sintetizar", json={"texto": texto, **kw}, headers={**h, **(headers or {})})


async def test_sintetizar_ok_devuelve_audio_sin_cache(construir_app):
    from asistente.core.voz.falso import TtsFalso

    tts = TtsFalso(b"MP3")
    async with construir_app(tts=tts) as c:
        r = await sintetizar(c, idioma="es-UY")
    assert r.status_code == 200 and r.content == b"MP3"
    assert r.headers["content-type"] == "audio/mpeg" and r.headers["cache-control"] == "no-store"
    assert tts.llamadas == [("Hola, tenés 660 hectáreas.", "es-UY")]


async def test_sintetizar_suma_los_caracteres_al_uso_del_mes(construir_app, sesiones):
    from asistente.core.voz.falso import TtsFalso

    mes = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with sesiones.begin() as s:
        await s.execute(delete(UsoVoz).where(UsoVoz.mes == mes, UsoVoz.sistema_id == "mock-a"))
    async with construir_app(tts=TtsFalso(b"MP3")) as c:
        assert (await sintetizar(c, texto="Hola")).status_code == 200
        assert (await sintetizar(c, texto="Tenés 660 hectáreas.")).status_code == 200
        assert (await sintetizar(c, texto="")).status_code == 422   # lo rechazado no cuenta
    async with sesiones() as s:
        fila = (await s.execute(select(UsoVoz).where(UsoVoz.mes == mes, UsoVoz.sistema_id == "mock-a"))).scalar_one()
    assert (fila.proveedor, fila.modelo, fila.llamadas, fila.caracteres) == ("falso", "falso", 2, 4 + 20)


async def test_sintetizar_que_falla_no_cuenta(construir_app, sesiones):
    from asistente.core.voz.falso import TtsFalso

    mes = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with sesiones.begin() as s:
        await s.execute(delete(UsoVoz).where(UsoVoz.mes == mes, UsoVoz.sistema_id == "mock-a"))
    async with construir_app(tts=TtsFalso(falla=True)) as c:
        assert (await sintetizar(c)).status_code == 502
    async with sesiones() as s:
        assert (await s.execute(select(UsoVoz).where(UsoVoz.mes == mes, UsoVoz.sistema_id == "mock-a"))).first() is None


async def test_sintetizar_devuelve_el_audio_aunque_falle_la_contabilidad(construir_app, monkeypatch):
    from asistente.api import voz
    from asistente.core.voz.falso import TtsFalso

    async def roto(*a, **kw):
        raise RuntimeError("bd caída")

    monkeypatch.setattr(voz, "sumar_uso_voz", roto)
    async with construir_app(tts=TtsFalso(b"MP3")) as c:
        r = await sintetizar(c)
    assert r.status_code == 200 and r.content == b"MP3"


async def test_sintetizar_exige_token_y_origen(construir_app):
    from asistente.core.voz.falso import TtsFalso

    tts = TtsFalso()
    async with construir_app(tts=tts) as c:
        assert (await c.post("/v1/voz/sintetizar", json={"texto": "x"})).status_code == 401
        r = await sintetizar(c, headers={"Origin": "https://malo.example"})
        assert r.status_code == 403
    assert not tts.llamadas


async def test_sintetizar_sin_tts_es_503(api):
    r = await sintetizar(api)
    assert r.status_code == 503 and r.json() == {"error": "voz_no_disponible"}


async def test_sintetizar_valida_el_texto(construir_app):
    from asistente.core.voz.falso import TtsFalso

    tts = TtsFalso()
    async with construir_app(tts=tts) as c:
        for malo in ("", "   "):
            assert (await sintetizar(c, malo)).status_code == 422
        r = await c.post("/v1/voz/sintetizar", content=b"no es json", headers=auth())
        assert r.status_code == 422 and r.json() == {"error": "texto_invalido"}
        r = await c.post("/v1/voz/sintetizar", json={"otro": 1}, headers=auth())
        assert r.status_code == 422
        r = await sintetizar(c, "x" * 1001)
        assert r.status_code == 413 and r.json() == {"error": "texto_demasiado_largo"}
        assert (await sintetizar(c, "x" * 1000)).status_code == 200
    assert len(tts.llamadas) == 1


async def test_sintetizar_error_del_proveedor_es_502(construir_app):
    from asistente.core.voz.falso import TtsFalso

    async with construir_app(tts=TtsFalso(falla=True)) as c:
        r = await sintetizar(c)
    assert r.status_code == 502 and r.json() == {"error": "voz_error"}


async def test_sintetizar_tiene_limite_propio_y_no_toca_el_del_dictado(construir_app, monkeypatch):
    from asistente.core.voz.falso import SttFalso, TtsFalso

    monkeypatch.setenv("ASISTENTE_VOZ_TTS_MAX_POR_MIN", "2")
    u1, u2 = sub(), sub()
    async with construir_app(tts=TtsFalso(), stt=SttFalso()) as c:
        assert (await sintetizar(c, usuario=u1)).status_code == 200
        assert (await sintetizar(c, usuario=u1)).status_code == 200
        r = await sintetizar(c, usuario=u1)
        assert r.status_code == 429 and r.json() == {"error": "limite_excedido"}
        assert (await sintetizar(c, usuario=u2)).status_code == 200  # otro usuario, otro contador
        assert (await dictar(c, usuario=u1)).status_code == 200


async def test_estado_informa_respuesta_segun_el_tts(construir_app):
    from asistente.core.voz.falso import TtsFalso

    for tts, esperado in [(TtsFalso(), True), (TtsFalso(disponible=False), False), (None, False)]:
        async with construir_app(tts=tts) as c:
            r = await c.get("/v1/estado", headers=auth())
            assert r.json()["voz"]["respuesta"] is esperado


# --- catálogo de voces del servidor --------------------------------------------------------------


def _catalogo():
    from asistente.core.voz.catalogo import CatalogoVoces, Voz

    return CatalogoVoces((Voz("m1", "Mateo", "masculina", "EL_M1"), Voz("f1", "Lucía", "femenina", "EL_F1")), "m1")


async def test_sintetizar_usa_la_voz_pedida_y_cae_a_la_predeterminada(construir_app):
    from asistente.core.voz.falso import TtsFalso

    tts = TtsFalso()
    async with construir_app(tts=tts, voces=_catalogo()) as c:
        assert (await sintetizar(c, voz="f1")).status_code == 200
        assert (await sintetizar(c)).status_code == 200
        assert (await sintetizar(c, voz="retirada")).status_code == 200   # una voz que ya no existe no deja mudo
    assert tts.voces == ["EL_F1", "EL_M1", "EL_M1"]


async def test_estado_ofrece_las_voces_sin_el_voice_id(construir_app):
    from asistente.core.voz.falso import TtsFalso

    async with construir_app(tts=TtsFalso(), voces=_catalogo()) as c:
        voz = (await c.get("/v1/estado", headers=auth())).json()["voz"]
    assert voz["voz_defecto"] == "m1"
    assert voz["voces"] == [{"id": "m1", "etiqueta": "Mateo", "genero": "masculina"},
                            {"id": "f1", "etiqueta": "Lucía", "genero": "femenina"}]
    assert "EL_M1" not in str(voz)
