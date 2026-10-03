"""Sistema mock que implementa el contrato v1 con datos ficticios.

Sirve para desarrollo, para el verificador y para los tests de aislamiento
(se levantan dos instancias con ids y secretos distintos).

Configuración por variables de entorno:
  MOCK_ID                 id del sistema (claim `iss`)            [mock-a]
  MOCK_NOMBRE             nombre en el manifiesto                 [Mock A]
  MOCK_SECRETO            secreto HS256 que firma/valida tokens   [secreto-mock-a]
  MOCK_AUDIENCIA          claim `aud`                             [asistente]
  MOCK_TOKEN_MANIFIESTO   credencial para leer el manifiesto      [manifiesto-mock-a]

El login es de juguete: `GET /asistente/token?usuario=ana` emite un token para
ese usuario sin pedir contraseña. Un sistema real usa su sesión normal.
"""

import os
import time
import uuid

import jwt
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

ID = os.getenv("MOCK_ID", "mock-a")
NOMBRE = os.getenv("MOCK_NOMBRE", "Mock A")
SECRETO = os.getenv("MOCK_SECRETO", "secreto-mock-a")
AUDIENCIA = os.getenv("MOCK_AUDIENCIA", "asistente")
TOKEN_MANIFIESTO = os.getenv("MOCK_TOKEN_MANIFIESTO", "manifiesto-mock-a")
VIDA_TOKEN_S = 600

# Datos ficticios: cada usuario ve solo sus establecimientos.
DATOS: dict[str, list[dict]] = {
    "ana": [
        {"id": "1", "nombre": "El Matorral", "superficie_ha": 540.5, "cultivo": "soja"},
        {"id": "2", "nombre": "La Esperanza", "superficie_ha": 210.0, "cultivo": "maíz"},
    ],
    "beto": [
        {"id": "3", "nombre": "Los Ceibos", "superficie_ha": 88.2, "cultivo": "trigo"},
    ],
}

MANIFIESTO = {
    "contrato": "1",
    "sistema": {"nombre": NOMBRE, "version": "0.1.0"},
    "tools": [
        {
            "nombre": "listar_establecimientos",
            "descripcion": (
                "Lista los establecimientos que el usuario puede ver. "
                "Usar primero para resolver nombres a ids."
            ),
            "parametros": {
                "type": "object",
                "properties": {"texto": {"type": "string", "description": "filtro por nombre"}},
                "additionalProperties": False,
            },
            "efecto": "lectura",
            "timeout_s": 15,
        },
        {
            "nombre": "resumen_establecimiento",
            "descripcion": "Devuelve superficie y cultivo de un establecimiento a partir de su id.",
            "parametros": {
                "type": "object",
                "properties": {"id": {"type": "string", "description": "id del establecimiento"}},
                "required": ["id"],
                "additionalProperties": False,
            },
            "efecto": "lectura",
            "timeout_s": 15,
        },
        {
            # Solo para probar que el asistente no la expone al modelo.
            "nombre": "eliminar_establecimiento",
            "descripcion": "Elimina un establecimiento.",
            "parametros": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
            "efecto": "escritura",
        },
    ],
}

app = FastAPI(title=f"Sistema mock {ID}")


def _ok(datos: dict, fuente: str, ui: list | None = None) -> dict:
    out = {"ok": True, "datos": datos, "fuente": fuente}
    if ui:
        out["ui"] = ui
    return out


def _error(error: str, detalle: str) -> dict:
    return {"ok": False, "error": error, "detalle": detalle}


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "falta Authorization: Bearer")
    return authorization.removeprefix("Bearer ").strip()


@app.get("/asistente/salud")
async def salud() -> dict:
    return {"ok": True}


@app.get("/asistente/token")
async def emitir_token(usuario: str) -> dict:
    if usuario not in DATOS:
        raise HTTPException(403, "usuario sin acceso al asistente")
    ahora = int(time.time())
    claims = {
        "iss": ID,
        "aud": AUDIENCIA,
        "sub": usuario,
        "iat": ahora,
        "exp": ahora + VIDA_TOKEN_S,
        "jti": uuid.uuid4().hex,
        "scope": "asistente:lectura",
        "nombre": usuario.capitalize(),
        "locale": "es-UY",
    }
    token = jwt.encode(claims, SECRETO, algorithm="HS256")
    return {
        "token": token,
        "expira": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(claims["exp"])),
    }


@app.get("/asistente/tools")
async def manifiesto(authorization: str | None = Header(default=None)) -> dict:
    if _bearer(authorization) != TOKEN_MANIFIESTO:
        raise HTTPException(401, "credencial de manifiesto inválida")
    return MANIFIESTO


@app.post("/asistente/tools/{nombre}")
async def ejecutar(
    nombre: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _bearer(authorization)
    if token == TOKEN_MANIFIESTO:
        raise HTTPException(403, "el token de manifiesto no sirve para ejecutar")
    try:
        claims = jwt.decode(
            token, SECRETO, algorithms=["HS256"], audience=AUDIENCIA, issuer=ID,
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"token inválido: {e}") from e
    if claims.get("scope") != "asistente:lectura":
        raise HTTPException(403, "scope insuficiente")

    herramienta = next((t for t in MANIFIESTO["tools"] if t["nombre"] == nombre), None)
    if herramienta is None:
        return JSONResponse(_error("no_disponible", f"tool desconocida: {nombre}"))
    if herramienta["efecto"] != "lectura":
        raise HTTPException(403, "escritura no permitida con scope de lectura")

    try:
        parametros = (await request.json())["parametros"]
    except (ValueError, KeyError, TypeError):
        parametros = None
    if not isinstance(parametros, dict):
        return JSONResponse(_error("parametros_invalidos", "cuerpo debe ser {parametros: {...}}"))

    propios = DATOS.get(claims["sub"], [])

    if nombre == "listar_establecimientos":
        texto = str(parametros.get("texto", "")).lower()
        res = [e for e in propios if texto in e["nombre"].lower()]
        ui = [
            {"tipo": "navegar", "url": f"/establecimientos/{e['id']}", "etiqueta": e["nombre"]}
            for e in res
        ]
        return JSONResponse(_ok({"establecimientos": res}, "establecimientos", ui))

    if nombre == "resumen_establecimiento":
        est_id = parametros.get("id")
        if not isinstance(est_id, str):
            return JSONResponse(_error("parametros_invalidos", "`id` debe ser string"))
        est = next((e for e in propios if e["id"] == est_id), None)
        if est is None:
            # Igual que "no existe": no se revela si pertenece a otro usuario.
            return JSONResponse(_error("no_encontrado", "No existe o no tenés acceso"))
        return JSONResponse(_ok(est, "establecimientos"))

    return JSONResponse(_error("no_disponible", "no implementada"))


# ── Página de demostración: integra el widget como lo haría cualquier sistema ──
ASISTENTE_URL = os.getenv("MOCK_ASISTENTE_URL", "http://localhost:8100")

_PAGINA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{titulo}</title></head>
<body style="font-family:system-ui;max-width:640px;margin:2rem auto;padding:0 1rem">
<h1>{titulo}</h1>
<p>{cuerpo}</p>
<p><a href="/">Inicio</a> · usuario de prueba: <a href="/?usuario=ana">ana</a> · <a href="/?usuario=beto">beto</a></p>
<script src="{asistente}/widget.js" defer></script>
<asistente-chat servidor="{asistente}" token-url="/asistente/token?usuario={usuario}"></asistente-chat>
</body></html>"""


def _pagina(titulo: str, cuerpo: str, usuario: str) -> HTMLResponse:
    from html import escape
    return HTMLResponse(_PAGINA.format(
        titulo=escape(titulo), cuerpo=escape(cuerpo), asistente=escape(ASISTENTE_URL),
        usuario=escape(usuario),
    ))


@app.get("/", response_class=HTMLResponse)
async def inicio(usuario: str = "ana") -> HTMLResponse:
    return _pagina(NOMBRE, f"Sistema mock. Sesión simulada como «{usuario}».", usuario)


@app.get("/establecimientos/{est_id}", response_class=HTMLResponse)
async def establecimiento(est_id: str, usuario: str = "ana") -> HTMLResponse:
    est = next((e for e in DATOS.get(usuario, []) if e["id"] == est_id), None)
    if est is None:
        raise HTTPException(404, "no encontrado")
    return _pagina(est["nombre"], f"{est['superficie_ha']} ha de {est['cultivo']}.", usuario)
