from asistente.sistemas.registro import RegistroSistemas
from conftest import entorno, entrada_sistema, escribir_registro


def test_carga_sistema_valido(tmp_path):
    r = RegistroSistemas(
        escribir_registro(tmp_path / "s.yaml", [entrada_sistema("a")]), env=entorno("a")
    )
    assert r.obtener("a").auth.audiencia == "asistente"
    assert r.errores == {}


def test_locale_defecto_valido_o_el_sistema_se_descarta(tmp_path):
    r = RegistroSistemas(escribir_registro(tmp_path / "s.yaml", [
        entrada_sistema("a", locale_defecto="es-UY"), entrada_sistema("b", locale_defecto="español"),
        entrada_sistema("c")]), env=entorno("a", "b", "c"))
    assert r.obtener("a").locale_defecto == "es-UY" and r.obtener("c").locale_defecto is None
    assert r.obtener("b") is None and "b" in r.errores


def test_sistema_invalido_no_afecta_a_los_demas(tmp_path):
    malo = entrada_sistema("malo", auth={"algoritmo": "none", "secreto_env": "X"})
    r = RegistroSistemas(
        escribir_registro(tmp_path / "s.yaml", [malo, entrada_sistema("a")]),
        env=entorno("a", "malo"),
    )
    assert r.obtener("malo") is None
    assert r.obtener("a") is not None
    assert "malo" in r.errores


def test_faltan_variables_de_entorno(tmp_path):
    r = RegistroSistemas(escribir_registro(tmp_path / "s.yaml", [entrada_sistema("a")]), env={})
    assert r.obtener("a") is None
    assert "a_SECRETO" in r.errores["a"]


def test_exactamente_una_fuente_de_clave(tmp_path):
    e = entrada_sistema(
        "a", auth={"algoritmo": "HS256", "secreto_env": "A", "jwks_url": "https://x/jwks"}
    )
    r = RegistroSistemas(escribir_registro(tmp_path / "s.yaml", [e]), env=entorno("a"))
    assert "a" in r.errores


def test_hs256_requiere_secreto_y_rs256_no_lo_admite(tmp_path):
    hs = entrada_sistema("h", auth={"algoritmo": "HS256", "jwks_url": "https://x/jwks"})
    rs = entrada_sistema("r", auth={"algoritmo": "RS256", "secreto_env": "S"})
    r = RegistroSistemas(escribir_registro(tmp_path / "s.yaml", [hs, rs]), env=entorno("h", "r"))
    assert set(r.errores) == {"h", "r"}


def test_id_duplicado_deshabilita_ambos(tmp_path):
    r = RegistroSistemas(
        escribir_registro(tmp_path / "s.yaml", [entrada_sistema("a"), entrada_sistema("a")]),
        env=entorno("a"),
    )
    assert r.obtener("a") is None
    assert r.errores["a"] == "id duplicado"


def test_deshabilitado_no_se_sirve(tmp_path):
    r = RegistroSistemas(
        escribir_registro(tmp_path / "s.yaml", [entrada_sistema("a", habilitado=False)]), env={}
    )
    assert r.obtener("a") is None
    assert r.errores == {}


def test_ruta_ejecucion_sin_placeholder(tmp_path):
    e = entrada_sistema(
        "a", conector={"token_manifiesto_env": "a_MANIFEST", "ruta_ejecucion": "/tools"}
    )
    r = RegistroSistemas(escribir_registro(tmp_path / "s.yaml", [e]), env=entorno("a"))
    assert "a" in r.errores


def test_archivo_inexistente_o_vacio(tmp_path):
    assert RegistroSistemas(tmp_path / "no-existe.yaml").todos() == []
    vacio = tmp_path / "v.yaml"
    vacio.write_text("")
    assert RegistroSistemas(vacio).todos() == []


def test_recargar_toma_cambios(tmp_path):
    ruta = escribir_registro(tmp_path / "s.yaml", [entrada_sistema("a")])
    r = RegistroSistemas(ruta, env=entorno("a", "b"))
    escribir_registro(ruta, [entrada_sistema("a"), entrada_sistema("b")])
    r.recargar()
    assert r.obtener("b") is not None


def test_ejemplo_del_repo_carga():
    from conftest import RAIZ

    assert RegistroSistemas(RAIZ / "config" / "sistemas.example.yaml").todos() == []
