"""Entrega de documentos: persistencia previa, identidad y ausencia de reintentos."""
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from asistente.api import canal_flujo as flujo
from asistente.core import events
from asistente.core.canales.base import ErrorCanal
from asistente.core.llm.base import Uso


@pytest.mark.parametrize("completo,guarda", [(True, True), (False, True), (True, False)])
async def test_turno_persiste_antes_de_enviar_y_deduplica(monkeypatch, completo, guarda):
    id_ = str(uuid.uuid4())
    archivo = NS(datos=b"xlsx", nombre="real.xlsx", tipo_mime="mime")
    sistema = NS(leer_imagenes=False, consultas_recientes=False, canal_mensajeria=None)
    usuario = NS(usuario_ref="ana")
    repo = NS(historial=AsyncMock(return_value=[]), guardar_turno=AsyncMock())
    if not guarda:
        repo.guardar_turno.side_effect = RuntimeError("persistencia")
    svc = NS(registro=NS(obtener=lambda _: sistema, secreto=lambda *a: None),
             settings=NS(max_mensaje_chars=1000, max_turnos_historial=10),
             canal_vinculos=NS(tocar=AsyncMock(return_value=datetime.now(UTC))),
             llm_para=lambda _: (None, "modelo"),
             limites=None, metricas=None, repo=repo, conector=NS(para=lambda *a: None),
             acciones=None, auditoria=None, adjuntos=None,
             archivos=NS(obtener=AsyncMock(return_value=archivo)))
    canal = NS(tiene_documentos=True, enviar_texto=AsyncMock(), enviar_documento=AsyncMock())

    async def enviar(*args):
        repo.guardar_turno.assert_awaited_once()
        assert repo.guardar_turno.call_args.args[-1] == [{"id": id_, "nombre": "evento.xlsx"}]
    canal.enviar_documento.side_effect = enviar
    armar = AsyncMock(return_value=(None, None, None, None, True, "v"))
    monkeypatch.setattr(flujo, "armar_turno", armar)
    monkeypatch.setattr(flujo, "_identificar", AsyncMock(return_value=usuario))
    monkeypatch.setattr(flujo, "reservar_cuota", AsyncMock(return_value=None))
    monkeypatch.setattr(flujo.random, "uniform", lambda *a: 0)

    async def run(*args, **kwargs):
        await args[7](events.UI, [{"tipo": "descarga", "id": id_, "nombre": "evento.xlsx"}] * 2)
        return NS(completo=completo, motivo="prueba", nuevos=[], uso=Uso(), texto="Contenido")
    monkeypatch.setattr(flujo, "run_turn", run)
    mensaje = NS(tipo="texto", texto="Excel", contacto="598", medio_ref=None)
    if completo and not guarda:
        with pytest.raises(RuntimeError):
            await flujo._turno(svc, "sistema", canal, mensaje)
    else:
        await flujo._turno(svc, "sistema", canal, mensaje)
    if completo and guarda:
        svc.archivos.obtener.assert_awaited_once_with("sistema", "ana", uuid.UUID(id_))
        canal.enviar_documento.assert_awaited_once_with("598", b"xlsx", "real.xlsx", "mime")
    else:
        canal.enviar_documento.assert_not_awaited()
    assert armar.call_args.kwargs["entrega_excel"] is True


async def test_entrega_parcial_no_reintenta_y_usa_filtro_de_identidad():
    ids = [str(uuid.uuid4()) for _ in range(3)]
    archivo = NS(datos=b"xlsx", nombre="reporte.xlsx", tipo_mime="mime")
    svc = NS(archivos=NS(obtener=AsyncMock(side_effect=[None, archivo, archivo])))
    canal = NS(enviar_texto=AsyncMock(),
               enviar_documento=AsyncMock(side_effect=[ErrorCanal("timeout"), "aceptado"]))
    await flujo._entregar_archivos(svc, "sistema", NS(usuario_ref="ana"), canal, "598", ids + ids)
    assert canal.enviar_documento.await_count == 2
    assert canal.enviar_texto.await_count == 2
    assert "No pude confirmar" in canal.enviar_texto.call_args_list[-1].args[1]
    assert [c.args for c in svc.archivos.obtener.call_args_list] == [
        ("sistema", "ana", uuid.UUID(i)) for i in ids]


async def test_registra_documento_sin_contenido():
    svc = NS(canal_mensajes=NS(registrar_salida=AsyncMock()))
    canal = NS(enviar_documento=AsyncMock(return_value="mid"))
    assert await flujo._Registrando(canal, svc, "s").enviar_documento("598", b"privado", "a.xlsx", "mime") == "mid"
    svc.canal_mensajes.registrar_salida.assert_awaited_once_with("s", "mid", "598", "documento")


def test_prompt_sin_entrega_solo_si_el_sistema_tiene_excel(tmp_path):
    from asistente.core.prompts import Prompts
    (tmp_path / "base.md").write_text("base", encoding="utf-8")
    p = Prompts(tmp_path)
    comun = {"sistema_nombre": "S", "prompt_dominio": None, "usuario_nombre": None, "locale": None,
              "hoy": datetime.now(UTC).date(), "canal": "whatsapp"}
    base, v_base = p.componer(**comun)
    con, v_con = p.componer(**comun, excel_sin_entrega=True)
    assert "No ofrezcas generar ni adjuntar planillas" in con
    assert "No ofrezcas generar ni adjuntar planillas" not in base
    assert v_base != v_con
