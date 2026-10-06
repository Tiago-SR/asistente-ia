# ruff: noqa: F811  (se reutilizan fixtures de test_api.py por importación)
"""Memoria por usuario sobre Postgres: tope, reemplazo, vencimiento, renovación una vez al día, purga y
aislamiento por `(sistema_id, usuario_ref)`."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from asistente.core.memoria import MAX_RECUERDOS
from asistente.core.ports import TopeMemoria
from asistente.retencion import purgar_todos
from asistente.sistemas.registro import RegistroSistemas
from asistente.store.memoria import MemoriaSql
from asistente.store.models import MemoriaUsuario
from conftest import entorno, entrada_sistema, escribir_registro
from test_api import sesiones, sub  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.environ.get("ASISTENTE_DATABASE_URL"), reason="sin ASISTENTE_DATABASE_URL"
)

ENTIDAD = {"entidad": "establecimiento", "id": "4", "nombre": "San Pedro"}


class Reloj:
    def __init__(self):
        self.ahora = datetime.now(UTC)

    def __call__(self):
        return self.ahora

    def avanzar(self, **kw):
        self.ahora += timedelta(**kw)


@pytest.fixture
def reloj():
    return Reloj()


@pytest.fixture
def mem(sesiones, reloj):
    return MemoriaSql(sesiones, 30, reloj)


@pytest.fixture
def ids():
    """Sistema y usuario únicos por prueba: la base de dev se comparte entre corridas."""
    return f"s-{sub()}", sub()


async def fila(sesiones, sistema, usuario, tipo, clave):
    async with sesiones() as s:
        return (await s.execute(select(MemoriaUsuario).where(
            MemoriaUsuario.sistema_id == sistema, MemoriaUsuario.usuario_ref == usuario,
            MemoriaUsuario.tipo == tipo, MemoriaUsuario.clave == clave))).scalar_one_or_none()


async def antiguedad(sesiones, sistema, usuario, tipo, clave, dias, *, creada_tambien=False):
    """Envejece `ultimo_uso` de un recuerdo (simula que pasaron `dias` sin usarse)."""
    async with sesiones.begin() as s:
        await s.execute(update(MemoriaUsuario).where(
            MemoriaUsuario.sistema_id == sistema, MemoriaUsuario.usuario_ref == usuario,
            MemoriaUsuario.tipo == tipo, MemoriaUsuario.clave == clave,
        ).values(ultimo_uso=datetime.now(UTC) - timedelta(days=dias)))


# ───────────── guardar, reemplazar, tope ─────────────


async def test_guardar_y_leer_conserva_el_valor_json(mem, ids):
    s, u = ids
    await mem.guardar(s, u, "preferencia", "decimales", 0)
    await mem.guardar(s, u, "alias", "la sojera", ENTIDAD)
    await mem.guardar(s, u, "consulta_guardada", "la de siempre", {"tool": "t", "parametros": {"a": [1, "dos"]}})
    por_clave = {r.clave: r for r in await mem.listar(s, u)}
    assert por_clave["decimales"].valor == 0 and por_clave["decimales"].tipo == "preferencia"
    assert por_clave["la sojera"].valor == ENTIDAD
    assert por_clave["la de siempre"].valor["parametros"] == {"a": [1, "dos"]}
    assert await mem.contar(s, u) == 3


async def test_guardar_de_nuevo_la_misma_clave_reemplaza_el_valor(mem, sesiones, ids):
    s, u = ids
    primero = await mem.guardar(s, u, "preferencia", "decimales", 2)
    segundo = await mem.guardar(s, u, "preferencia", "decimales", 0)
    assert segundo.id == primero.id and segundo.valor == 0
    assert await mem.contar(s, u) == 1
    assert (await mem.obtener(s, u, "preferencia", "decimales")).valor == 0


async def test_la_misma_clave_en_otro_tipo_es_otro_recuerdo(mem, ids):
    s, u = ids
    await mem.guardar(s, u, "alias", "x", ENTIDAD)
    await mem.guardar(s, u, "consulta_guardada", "x", {"tool": "t", "parametros": {}})
    assert await mem.contar(s, u) == 2


async def test_tope_de_veinte_por_usuario_y_sistema(mem, ids):
    s, u = ids
    for i in range(MAX_RECUERDOS):
        await mem.guardar(s, u, "alias", f"alias {i}", ENTIDAD)
    with pytest.raises(TopeMemoria):
        await mem.guardar(s, u, "alias", "uno más", ENTIDAD)
    await mem.guardar(s, u, "alias", "alias 0", {**ENTIDAD, "id": "9"})  # reemplazar sí se puede
    assert await mem.contar(s, u) == MAX_RECUERDOS
    # el tope es por usuario Y por sistema: otro usuario y otro sistema tienen su propio cupo
    await mem.guardar(s, sub(), "alias", "uno más", ENTIDAD)
    await mem.guardar(f"{s}-otro", u, "alias", "uno más", ENTIDAD)


async def test_el_tope_aguanta_confirmaciones_simultaneas(mem, ids):
    s, u = ids
    for i in range(MAX_RECUERDOS - 1):
        await mem.guardar(s, u, "alias", f"alias {i}", ENTIDAD)
    resultados = await asyncio.gather(
        *(mem.guardar(s, u, "alias", f"nuevo {i}", ENTIDAD) for i in range(5)), return_exceptions=True)
    assert sum(isinstance(r, TopeMemoria) for r in resultados) == 4
    assert await mem.contar(s, u) == MAX_RECUERDOS


async def test_los_vencidos_no_cuentan_para_el_tope(mem, sesiones, ids, reloj):
    s, u = ids
    for i in range(MAX_RECUERDOS):
        await mem.guardar(s, u, "alias", f"alias {i}", ENTIDAD)
    reloj.avanzar(days=31)
    assert await mem.contar(s, u) == 0
    await mem.guardar(s, u, "alias", "nuevo", ENTIDAD)


async def test_reguardar_una_clave_vencida_reutiliza_la_fila(mem, sesiones, ids, reloj):
    s, u = ids
    vieja = await mem.guardar(s, u, "preferencia", "decimales", 2)
    reloj.avanzar(days=40)
    assert await mem.obtener(s, u, "preferencia", "decimales") is None
    nueva = await mem.guardar(s, u, "preferencia", "decimales", 0)
    assert nueva.id == vieja.id and (await mem.listar(s, u))[0].valor == 0


# ───────────── vencimiento y renovación ─────────────


async def test_lo_vencido_no_se_ve_aunque_la_purga_no_haya_corrido(mem, ids, reloj):
    s, u = ids
    await mem.guardar(s, u, "preferencia", "decimales", 0)
    reloj.avanzar(days=29)
    assert len(await mem.listar(s, u)) == 1
    reloj.avanzar(days=2)  # 31 días sin usarse
    assert await mem.listar(s, u) == []
    assert await mem.obtener(s, u, "preferencia", "decimales") is None


async def test_leerlo_para_el_prompt_renueva_la_antiguedad_y_no_vence(mem, ids, reloj):
    s, u = ids
    await mem.guardar(s, u, "preferencia", "decimales", 0)
    for _ in range(4):  # cuatro lecturas separadas 20 días: 80 días en total, nunca 30 sin uso
        reloj.avanzar(days=20)
        assert len(await mem.listar(s, u, renovar=True)) == 1


async def test_renueva_como_maximo_una_vez_al_dia(mem, sesiones, ids, reloj):
    s, u = ids
    await mem.guardar(s, u, "preferencia", "decimales", 0)
    inicial = (await fila(sesiones, s, u, "preferencia", "decimales")).ultimo_uso
    reloj.avanzar(hours=5)
    await mem.listar(s, u, renovar=True)
    assert (await fila(sesiones, s, u, "preferencia", "decimales")).ultimo_uso == inicial  # menos de un día: no escribe
    reloj.avanzar(hours=20)  # ya pasó más de un día desde el último uso
    await mem.listar(s, u, renovar=True)
    renovado = (await fila(sesiones, s, u, "preferencia", "decimales")).ultimo_uso
    assert renovado == reloj.ahora and renovado > inicial
    reloj.avanzar(hours=3)
    await mem.listar(s, u, renovar=True)
    assert (await fila(sesiones, s, u, "preferencia", "decimales")).ultimo_uso == renovado  # otra vez: nada


async def test_listar_sin_renovar_no_toca_nada(mem, sesiones, ids, reloj):
    s, u = ids
    await mem.guardar(s, u, "preferencia", "decimales", 0)
    inicial = (await fila(sesiones, s, u, "preferencia", "decimales")).ultimo_uso
    reloj.avanzar(days=10)
    await mem.listar(s, u)
    assert (await fila(sesiones, s, u, "preferencia", "decimales")).ultimo_uso == inicial


async def test_renovar_solo_toca_los_recuerdos_del_usuario_que_lee(mem, sesiones, ids, reloj):
    s, u = ids
    otro = sub()
    await mem.guardar(s, u, "preferencia", "decimales", 0)
    await mem.guardar(s, otro, "preferencia", "decimales", 0)
    antes = (await fila(sesiones, s, otro, "preferencia", "decimales")).ultimo_uso
    reloj.avanzar(days=3)
    await mem.listar(s, u, renovar=True)
    assert (await fila(sesiones, s, otro, "preferencia", "decimales")).ultimo_uso == antes


async def test_dias_sin_uso_es_configurable(sesiones, ids, reloj):
    s, u = ids
    corta = MemoriaSql(sesiones, 7, reloj)
    await corta.guardar(s, u, "preferencia", "decimales", 0)
    reloj.avanzar(days=8)
    assert await corta.listar(s, u) == []
    assert len(await MemoriaSql(sesiones, 30, reloj).listar(s, u)) == 1


# ───────────── purga ─────────────


async def test_purgar_borra_lo_vencido_de_ese_sistema_y_nada_mas(mem, sesiones, ids):
    s, u = ids
    otro_sistema = f"{s}-otro"
    for sistema in (s, otro_sistema):
        await mem.guardar(sistema, u, "preferencia", "decimales", 0)
        await mem.guardar(sistema, u, "preferencia", "brevedad", "corta")
        await antiguedad(sesiones, sistema, u, "preferencia", "decimales", 40)
    assert await mem.purgar(s) == 1
    assert await fila(sesiones, s, u, "preferencia", "decimales") is None
    assert await fila(sesiones, s, u, "preferencia", "brevedad") is not None  # vigente
    assert await fila(sesiones, otro_sistema, u, "preferencia", "decimales") is not None  # otro sistema


class RepoFalso:
    async def purgar(self, sistema_id, retencion_dias):
        return 0


async def test_el_barrido_de_retencion_purga_la_memoria_de_un_sistema_con_la_memoria_apagada(
        mem, sesiones, tmp_path, ids):
    """Si un sistema deshabilita la memoria, sus filas se van al vencer (sin usarse no se renuevan)."""
    sistema, u = ids
    registro = RegistroSistemas(escribir_registro(tmp_path / "s.yaml", [entrada_sistema(sistema)]),
                                env=entorno(sistema))
    assert registro.obtener(sistema).memoria_habilitada is False
    await mem.guardar(sistema, u, "preferencia", "decimales", 0)
    await mem.guardar(sistema, u, "preferencia", "brevedad", "corta")
    await antiguedad(sesiones, sistema, u, "preferencia", "decimales", 40)
    await purgar_todos(registro, RepoFalso(), memoria=mem)
    assert await fila(sesiones, sistema, u, "preferencia", "decimales") is None
    assert await fila(sesiones, sistema, u, "preferencia", "brevedad") is not None


# ───────────── aislamiento ─────────────


async def test_otro_usuario_y_otro_sistema_no_ven_ni_borran_nada(mem, ids):
    s, ana = ids
    beto = sub()
    guardado = await mem.guardar(s, ana, "alias", "la sojera", ENTIDAD)

    assert await mem.listar(s, beto) == [] and await mem.listar(f"{s}-otro", ana) == []
    assert await mem.obtener(s, beto, "alias", "la sojera") is None
    assert await mem.obtener(f"{s}-otro", ana, "alias", "la sojera") is None
    assert await mem.contar(s, beto) == 0
    # ni borrar por id, por clave, ni «olvidar todo»
    assert not await mem.borrar(s, beto, uuid.UUID(guardado.id))
    assert not await mem.borrar(f"{s}-otro", ana, uuid.UUID(guardado.id))
    assert not await mem.borrar_clave(s, beto, "alias", "la sojera")
    assert not await mem.borrar_clave(f"{s}-otro", ana, "alias", "la sojera")
    assert await mem.borrar_todo(s, beto) == 0 and await mem.borrar_todo(f"{s}-otro", ana) == 0
    assert (await mem.obtener(s, ana, "alias", "la sojera")).id == guardado.id

    # la misma clave en otro usuario es un recuerdo distinto
    otro = await mem.guardar(s, beto, "alias", "la sojera", {**ENTIDAD, "id": "9"})
    assert otro.id != guardado.id and (await mem.obtener(s, ana, "alias", "la sojera")).valor["id"] == "4"


async def test_borrar_por_id_y_todo(mem, ids):
    s, u = ids
    a = await mem.guardar(s, u, "preferencia", "decimales", 0)
    await mem.guardar(s, u, "preferencia", "brevedad", "corta")
    assert await mem.borrar(s, u, uuid.UUID(a.id)) and not await mem.borrar(s, u, uuid.UUID(a.id))
    assert await mem.borrar_todo(s, u) == 1 and await mem.listar(s, u) == []


async def test_la_base_rechaza_un_tipo_fuera_del_conjunto(mem, ids):
    s, u = ids
    with pytest.raises(Exception, match="ck_memoria_tipo"):
        await mem.guardar(s, u, "hecho_de_negocio", "ventas", 1000)
