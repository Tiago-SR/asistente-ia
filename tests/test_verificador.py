"""El verificador de conformidad aprueba el mock y detecta cada variante defectuosa."""

import importlib.util
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from conftest import cargar_mock

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("verificar_sistema", RAIZ / "herramientas" / "verificar_sistema.py")
verificador = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verificador)

SECRETO = "secreto-mock-v-" + "x" * 32
MANIFIESTO = "manifiesto-mock-v"


def montar(monkeypatch, defecto: str = ""):
    monkeypatch.setenv("MOCK_DEFECTO", defecto)
    mock = cargar_mock(monkeypatch, "mock-v")
    return TestClient(mock.app, base_url="http://mock-v")


def configuracion(**cambios) -> "verificador.Config":
    base = {
        "base_url": "http://mock-v",
        "token_url": "http://mock-v/asistente/token?usuario=ana",
        "token_manifiesto": MANIFIESTO,
        "secreto_firma": f"secreto-mock-v-{'x' * 32}",
        "token_url_otro": "http://mock-v/asistente/token?usuario=beto",
        "max_ms": 150,
    }
    base.update(cambios)
    return verificador.Config(**base)


def verificar(cliente, **cambios):
    return verificador.Verificador(configuracion(**cambios), cliente).ejecutar()


def fallos(informe) -> list[str]:
    return [t for _, estado, t, _ in informe.entradas if estado == verificador.FALLA]


def test_el_mock_conforme_pasa_sin_omitir_nada(monkeypatch):
    informe = verificar(montar(monkeypatch))
    assert informe.conforme, fallos(informe)
    assert informe.cuenta(verificador.OMITIDO) == 1  # resumen_establecimiento exige id y no se ejecuta sola
    assert "CONFORME" in informe.texto()


# defecto del mock → fragmento del título del chequeo que debe fallar
DEFECTOS = {
    "token_vida_larga": "vida del token",
    "manifiesto_publico": "sin credencial → 401",
    "manifiesto_invalido": "nombres de tools válidos",
    "acepta_vencido": "token vencido",
    "firma_no_verificada": "otra clave",
    "acepta_alg_none": "alg=none",
    "acepta_token_manifiesto": "token de manifiesto usado en la ejecución",
    "ignora_scope": "scope ajeno",
    "params_sin_validar": "parametros_invalidos",
    "filtra_ids_ajenos": "id de otro usuario",
    "respuesta_enorme": "tamaño de la respuesta",
    "lento": "tiempo de respuesta",
}


def test_cada_defecto_tiene_su_comprobacion():
    mock_defectos = {"respuesta_con_geometria"}  # solo avisa (ver test siguiente)
    from conftest import MOCK
    fuente = MOCK.read_text()
    declarados = set(DEFECTOS) | mock_defectos
    assert all(f'"{d}"' in fuente for d in declarados)


@pytest.mark.parametrize("defecto,fragmento", DEFECTOS.items())
def test_detecta_el_defecto(monkeypatch, defecto, fragmento):
    informe = verificar(montar(monkeypatch, defecto))
    assert not informe.conforme
    assert any(fragmento in f for f in fallos(informe)), (defecto, fallos(informe))
    assert "NO CONFORME" in informe.texto()


def test_geometrias_en_los_datos_son_un_aviso(monkeypatch):
    informe = verificar(montar(monkeypatch, "respuesta_con_geometria"))
    assert informe.conforme
    assert any("geometrías" in t for _, e, t, _ in informe.entradas if e == verificador.AVISO)


def test_sin_datos_opcionales_omite_en_vez_de_fallar(monkeypatch):
    informe = verificar(montar(monkeypatch), secreto_firma=None, token_url_otro=None)
    assert informe.conforme
    omitidos = [t for _, e, t, _ in informe.entradas if e == verificador.OMITIDO]
    assert any("token vencido" in t for t in omitidos)
    assert any("id de otro usuario" in t for t in omitidos)


def test_id_ajeno_explicito(monkeypatch):
    cliente = montar(monkeypatch, "filtra_ids_ajenos")
    informe = verificar(cliente, token_url_otro=None, id_ajeno="3")
    assert any("id de otro usuario" in f for f in fallos(informe))


def test_sistema_caido_falla_sin_traceback():
    def caido(request):
        import httpx
        raise httpx.ConnectError("no hay nadie")

    import httpx
    cliente = httpx.Client(transport=httpx.MockTransport(caido))
    informe = verificador.Verificador(configuracion(), cliente).ejecutar()
    assert not informe.conforme


def test_cli_codigo_de_salida_y_sin_secretos(monkeypatch, capsys):
    cliente = montar(monkeypatch)
    monkeypatch.setattr(verificador.httpx, "Client", lambda **kw: cliente)
    monkeypatch.setenv("V_MANIFIESTO", MANIFIESTO)
    monkeypatch.setenv("V_SECRETO", SECRETO)
    argv = ["--base-url", "http://mock-v", "--token-url", "http://mock-v/asistente/token?usuario=ana",
            "--token-url-otro", "http://mock-v/asistente/token?usuario=beto",
            "--token-manifiesto-env", "V_MANIFIESTO", "--secreto-firma-env", "V_SECRETO",
            "--max-ms", "150"]
    assert verificador.main(argv) == 0
    salida = capsys.readouterr().out
    assert "Resumen:" in salida and "CONFORME" in salida
    assert MANIFIESTO not in salida and SECRETO not in salida

    cliente = montar(monkeypatch, "acepta_vencido")
    monkeypatch.setattr(verificador.httpx, "Client", lambda **kw: cliente)
    assert verificador.main(argv) == 1
    salida = capsys.readouterr().out
    assert "Fallos a corregir" in salida and SECRETO not in salida


def test_los_secretos_se_ocultan_aunque_el_sistema_los_devuelva():
    informe = verificador.Informe(secretos={"s3cr3t0"})
    informe.registrar(verificador.FALLA, "algo", "el servidor dijo s3cr3t0")
    assert "s3cr3t0" not in informe.texto()
