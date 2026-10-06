import asyncio

from asistente.retencion import bucle_purga, purgar_todos
from asistente.sistemas.registro import RegistroSistemas
from conftest import entorno, entrada_sistema, escribir_registro


class RepoFalso:
    def __init__(self, falla: str | None = None) -> None:
        self.llamadas: list[tuple[str, int]] = []
        self.falla = falla

    async def purgar(self, sistema_id: str, retencion_dias: int) -> int:
        if sistema_id == self.falla:
            raise RuntimeError("BD caída")
        self.llamadas.append((sistema_id, retencion_dias))
        return 2


class AuditoriaFalsa:
    def __init__(self, falla: str | None = None) -> None:
        self.llamadas: list[tuple[str, int]] = []
        self.falla = falla

    async def purgar(self, sistema_id: str, retencion_dias: int) -> int:
        if sistema_id == self.falla:
            raise RuntimeError("BD caída")
        self.llamadas.append((sistema_id, retencion_dias))
        return 5


def registro(tmp_path) -> RegistroSistemas:
    ruta = escribir_registro(
        tmp_path / "s.yaml",
        [entrada_sistema("ret-a", retencion_dias=7), entrada_sistema("ret-b"), entrada_sistema("ret-c", retencion_dias=90)],
    )
    return RegistroSistemas(ruta, env=entorno("ret-a", "ret-b", "ret-c"))


async def test_cada_sistema_se_purga_con_su_retencion(tmp_path):
    repo = RepoFalso()
    borradas = await purgar_todos(registro(tmp_path), repo)
    assert repo.llamadas == [("ret-a", 7), ("ret-b", 30), ("ret-c", 90)]
    assert borradas == {"ret-a": 2, "ret-b": 2, "ret-c": 2}


async def test_un_sistema_que_falla_no_impide_purgar_a_los_demas(tmp_path):
    repo = RepoFalso(falla="ret-b")
    borradas = await purgar_todos(registro(tmp_path), repo)
    assert set(borradas) == {"ret-a", "ret-c"}


async def test_el_bucle_purga_al_arrancar_y_se_repite_hasta_cancelarse(tmp_path):
    repo = RepoFalso()
    tarea = asyncio.create_task(bucle_purga(registro(tmp_path), repo, 0.01))
    await asyncio.sleep(0.1)
    tarea.cancel()
    try:
        await tarea
    except asyncio.CancelledError:
        pass
    assert len(repo.llamadas) > 3  # más de una pasada (3 sistemas por pasada)


async def test_la_auditoria_de_tools_se_purga_con_la_retencion_de_cada_sistema(tmp_path):
    repo, auditoria = RepoFalso(), AuditoriaFalsa()
    await purgar_todos(registro(tmp_path), repo, auditoria=auditoria)
    assert auditoria.llamadas == [("ret-a", 7), ("ret-b", 30), ("ret-c", 90)]


async def test_sin_auditoria_no_se_purga_y_el_bucle_la_recibe(tmp_path):
    repo = RepoFalso()
    await purgar_todos(registro(tmp_path), repo)  # compatible con quien no la pasa
    auditoria = AuditoriaFalsa()
    tarea = asyncio.create_task(bucle_purga(registro(tmp_path), repo, 0.01, auditoria=auditoria))
    await asyncio.sleep(0.05)
    tarea.cancel()
    assert auditoria.llamadas
