"""core/ solo depende de interfaces: no importa api/, sistemas/ ni store/."""

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "src" / "asistente" / "core"
PROHIBIDOS = ("api", "sistemas", "store")


def _importados(archivo: Path) -> list[str]:
    """Módulos importados, con los imports relativos resueltos contra `asistente.core`."""
    paquete = ["asistente", "core", *archivo.relative_to(CORE).parent.parts]
    nombres = []
    for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Import):
            nombres += [a.name for a in nodo.names]
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level:
                base = paquete[: len(paquete) - (nodo.level - 1)]
                nombres.append(".".join([*base, *([nodo.module] if nodo.module else [])]))
                if not nodo.module:
                    nombres += [".".join([*base, a.name]) for a in nodo.names]
            elif nodo.module:
                nombres.append(nodo.module)
                nombres += [f"{nodo.module}.{a.name}" for a in nodo.names]
    return nombres


def test_core_no_importa_api_sistemas_ni_store():
    archivos = sorted(CORE.rglob("*.py"))
    assert archivos, "no se encontró core/"
    violaciones = [
        f"{a.relative_to(CORE)} importa {m}"
        for a in archivos
        for m in _importados(a)
        if any(m == f"asistente.{p}" or m.startswith(f"asistente.{p}.") for p in PROHIBIDOS)
    ]
    assert not violaciones, "\n".join(violaciones)


def test_el_detector_ve_los_imports_relativos(tmp_path, monkeypatch):
    malo = CORE / "_prueba_tmp.py"
    malo.write_text("from ..store import repo\nfrom asistente.api.chat import router\n", encoding="utf-8")
    try:
        encontrados = _importados(malo)
    finally:
        malo.unlink()
    assert "asistente.store" in encontrados
    assert "asistente.api.chat" in encontrados
