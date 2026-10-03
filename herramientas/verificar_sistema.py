"""Verificador de conformidad con el contrato v1 (sección 10.5 del plan).

Uso mínimo:
  python herramientas/verificar_sistema.py --base-url http://localhost:8201 \
      --token-url "http://localhost:8201/asistente/token?usuario=ana" \
      --token-manifiesto-env MI_TOKEN_MANIFIESTO

Comprobaciones opcionales (sin los datos necesarios se informan como OMITIDO):
  --secreto-firma-env VAR       forja tokens vencidos / de otra audiencia / de otro scope
                                (HS256 con el secreto de esa variable, o clave privada PEM)
  --token-url-otro URL          token de OTRO usuario: permite descubrir ids ajenos solo
  --id-ajeno ID                 id de otro usuario (alternativa a --token-url-otro)
  --cabecera-token-env VAR      cabecera "Nombre: valor" (cookie, API key…) que exige la ruta
                                de token; el valor se lee del entorno y nunca se imprime

Los secretos se leen de variables de entorno y se ocultan en todo el reporte. Solo necesita
httpx, jsonschema y pyjwt. Sale con código 1 si algún chequeo falla (2 si los argumentos
son inválidos).
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import jwt
from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).resolve().parent.parent / "contrato" / "schemas"
NOMBRE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ERRORES_AJENO = ("no_encontrado", "sin_acceso")
CLAVES_GEOMETRIA = {"geometry", "geom", "coordinates", "wkt", "geojson"}
AVISO_MS = 3000  # por encima, la respuesta se siente lenta en un chat
MAX_TOOLS_PARAMETROS = 5

OK, FALLA, AVISO, OMITIDO = "OK", "FALLA", "AVISO", "OMITIDO"


def _schema(nombre: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMAS / nombre).read_text()))


def _errores(validador: Draft202012Validator, instancia) -> str:
    return "; ".join(
        f"{'/'.join(map(str, e.path)) or '<raíz>'}: {e.message}"
        for e in validador.iter_errors(instancia)
    )


def _b64(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def _sin_firma(claims: dict) -> str:
    """JWT con alg=none y los mismos claims (no debe ser aceptado)."""
    return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}."


def _ids(datos, acumulado: set | None = None) -> set:
    """Valores de todas las claves `id` (string o entero) de una estructura anidada."""
    acumulado = set() if acumulado is None else acumulado
    if isinstance(datos, dict):
        for k, v in datos.items():
            if k == "id" and isinstance(v, str | int) and not isinstance(v, bool):
                acumulado.add(str(v))
            else:
                _ids(v, acumulado)
    elif isinstance(datos, list):
        for v in datos:
            _ids(v, acumulado)
    return acumulado


def _tiene_geometria(datos) -> bool:
    if isinstance(datos, dict):
        return any(k.lower() in CLAVES_GEOMETRIA or _tiene_geometria(v) for k, v in datos.items())
    if isinstance(datos, list):
        return any(_tiene_geometria(v) for v in datos)
    return False


def parametros_invalidos_para(schema: dict) -> list[tuple[str, dict]]:
    """Cuerpos de `parametros` que el schema de una tool debería rechazar."""
    casos: list[tuple[str, dict]] = []
    if schema.get("required"):
        casos.append(("falta un parámetro obligatorio", {}))
    malos = {"string": 12345, "integer": "abc", "number": "abc", "boolean": "abc",
             "array": "abc", "object": "abc"}
    for nombre, prop in schema.get("properties", {}).items():
        tipo = prop.get("type")
        if isinstance(tipo, str) and tipo in malos:
            casos.append((f"`{nombre}` con tipo incorrecto", {nombre: malos[tipo]}))
            break
    if schema.get("additionalProperties") is False:
        casos.append(("propiedad desconocida", {"__no_existe__": 1}))
    return casos


@dataclass
class Config:
    base_url: str
    token_url: str
    token_manifiesto: str
    ruta_manifiesto: str = "/asistente/tools"
    ruta_ejecucion: str = "/asistente/tools/{nombre}"
    ruta_salud: str = "/asistente/salud"
    cabecera_token: str | None = None          # "Nombre: valor"
    token_url_otro: str | None = None
    cabecera_token_otro: str | None = None
    secreto_firma: str | None = None
    algoritmo_firma: str = "HS256"
    id_ajeno: str | None = None
    tool_id: str | None = None
    max_kb: int = 50
    max_ms: int | None = None                  # por defecto, el `timeout_s` de cada tool
    timeout: float = 20


@dataclass
class Resp:
    status: int = 0
    cuerpo: object = None   # JSON decodificado, o None si no lo es
    texto: str = ""
    bytes: int = 0
    ms: float = 0
    error: str = ""         # fallo de red/timeout


@dataclass
class Informe:
    entradas: list[tuple[str, str, str, str]] = field(default_factory=list)  # sección, estado…
    secretos: set[str] = field(default_factory=set)
    seccion: str = ""

    def ocultar(self, texto: str) -> str:
        for s in sorted(self.secretos, key=len, reverse=True):
            texto = texto.replace(s, "***")
        return texto

    def registrar(self, estado: str, titulo: str, detalle: str = "") -> bool:
        self.entradas.append((self.seccion, estado, titulo, self.ocultar(detalle)))
        return estado != FALLA

    def cuenta(self, estado: str) -> int:
        return sum(1 for e in self.entradas if e[1] == estado)

    @property
    def conforme(self) -> bool:
        return self.cuenta(FALLA) == 0

    def texto(self) -> str:
        lineas, actual = [], None
        for seccion, estado, titulo, detalle in self.entradas:
            if seccion != actual:
                lineas += ["", f"== {seccion} =="]
                actual = seccion
            marca = {OK: "[OK]    ", FALLA: "[FALLA] ", AVISO: "[AVISO] ", OMITIDO: "[--]    "}[estado]
            lineas.append(f"{marca}{titulo}" + (f" — {detalle}" if detalle and estado != OK else ""))
        fallos = [e for e in self.entradas if e[1] == FALLA]
        lineas += ["", "-" * 60]
        if fallos:
            lineas.append("Fallos a corregir:")
            lineas += [f"  • {s}: {t}" + (f" — {d}" if d else "") for s, _, t, d in fallos]
        lineas.append(
            f"Resumen: {self.cuenta(OK)} correctos, {self.cuenta(FALLA)} fallos, "
            f"{self.cuenta(AVISO)} avisos, {self.cuenta(OMITIDO)} omitidos → "
            + ("CONFORME" if self.conforme else "NO CONFORME")
        )
        return "\n".join(lineas)


class _Corte(Exception):
    """Un prerrequisito falló y el resto de las comprobaciones no tiene sentido."""


class Verificador:
    def __init__(self, cfg: Config, cliente: httpx.Client | None = None):
        self.cfg = cfg
        self.c = cliente or httpx.Client(follow_redirects=False, timeout=cfg.timeout)
        self.inf = Informe()
        self.inf.secretos |= {s for s in (cfg.token_manifiesto, cfg.secreto_firma) if s}
        for cab in (cfg.cabecera_token, cfg.cabecera_token_otro):
            if cab:
                self.inf.secretos.add(cab.split(":", 1)[-1].strip())
        self.base = cfg.base_url.rstrip("/")

    # ── utilidades ──────────────────────────────────────────────────────────
    def _http(self, metodo: str, url: str, **kw) -> Resp:
        t0 = time.perf_counter()
        try:
            r = self.c.request(metodo, url, **kw)
        except httpx.HTTPError as e:
            return Resp(ms=(time.perf_counter() - t0) * 1000, error=type(e).__name__)
        ms = (time.perf_counter() - t0) * 1000
        try:
            cuerpo = r.json()
        except ValueError:
            cuerpo = None
        return Resp(r.status_code, cuerpo, r.text[:200], len(r.content), ms)

    def _chk(self, ok: bool, titulo: str, detalle: str = "") -> bool:
        return self.inf.registrar(OK if ok else FALLA, titulo, detalle)

    def _nota(self, estado: str, titulo: str, detalle: str = "") -> None:
        self.inf.registrar(estado, titulo, detalle)

    def _estado(self, r: Resp) -> str:
        return f"error de red: {r.error}" if r.error else f"status {r.status} {r.texto[:100]}"

    def _ejecutar(self, nombre: str, token: str | None, parametros=None, crudo: str | None = None,
                  ) -> Resp:
        cab = {"X-Asistente-Contrato": "1", "Content-Type": "application/json",
               "X-Asistente-Request-Id": uuid.uuid4().hex}
        if token is not None:
            cab["Authorization"] = f"Bearer {token}"
        cuerpo = crudo if crudo is not None else json.dumps({"parametros": parametros or {}})
        url = self.base + self.cfg.ruta_ejecucion.format(nombre=nombre)
        return self._http("POST", url, headers=cab, content=cuerpo)

    @staticmethod
    def _cabecera(valor: str | None) -> dict:
        if valor and ":" in valor:
            n, v = valor.split(":", 1)
            return {n.strip(): v.strip()}
        return {}

    def _pedir_token(self, url: str, cabecera: str | None) -> tuple[Resp, str]:
        r = self._http("GET", url, headers=self._cabecera(cabecera))
        token = r.cuerpo.get("token", "") if isinstance(r.cuerpo, dict) else ""
        if token:
            self.inf.secretos.add(token)
        return r, token

    def _forjar(self, claims: dict, **cambios) -> str:
        nuevos = {**claims, **cambios}
        return jwt.encode(
            {k: v for k, v in nuevos.items() if v is not None},
            self.cfg.secreto_firma, algorithm=self.cfg.algoritmo_firma,
        )

    # ── ejecución ───────────────────────────────────────────────────────────
    def ejecutar(self) -> Informe:
        try:
            self._salud()
            token, claims = self._token()
            tools = self._manifiesto()
            self._autenticacion(tools, token, claims)
            self._lecturas(tools, token)
            self._parametros(tools, token)
            self._ids_ajenos(tools, token)
            self._escrituras(tools, token)
        except _Corte:
            pass
        return self.inf

    def _salud(self) -> None:
        self.inf.seccion = "Salud"
        r = self._http("GET", self.base + self.cfg.ruta_salud)
        if r.status == 404:
            self._nota(OMITIDO, "salud no implementada (opcional)")
        else:
            self._chk(r.status == 200 and isinstance(r.cuerpo, dict) and r.cuerpo.get("ok") is True,
                      "salud devuelve {ok: true}", self._estado(r))

    def _token(self) -> tuple[str, dict]:
        self.inf.seccion = "Token de usuario"
        r, token = self._pedir_token(self.cfg.token_url, self.cfg.cabecera_token)
        if not self._chk(r.status == 200, "la ruta de token responde 200", self._estado(r)):
            raise _Corte
        self._chk(not (e := _errores(_schema("token-respuesta.schema.json"), r.cuerpo)),
                  "la respuesta de token cumple el schema", e)
        try:
            cab = jwt.get_unverified_header(token)
            claims = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
        except jwt.PyJWTError as e:
            self._chk(False, "el token es un JWT legible", str(e))
            raise _Corte from e
        self._chk(str(cab.get("alg", "none")).lower() != "none", "alg distinto de none", f"alg={cab.get('alg')}")
        self._chk(not (e := _errores(_schema("token-claims.schema.json"), claims)),
                  "los claims cumplen el schema (iss, aud, sub, iat, exp, jti, scope)", e)
        vida = claims.get("exp", 0) - claims.get("iat", 0)
        self._chk(0 < vida <= 15 * 60, "vida del token ≤ 15 min", f"{vida}s")
        self._chk(claims.get("scope") == "asistente:lectura", "scope = asistente:lectura",
                  f"scope={claims.get('scope')}")
        return token, claims

    def _manifiesto(self) -> list[dict]:
        self.inf.seccion = "Manifiesto"
        url = self.base + self.cfg.ruta_manifiesto
        self._chk(self._http("GET", url).status == 401, "sin credencial → 401")
        r = self._http("GET", url, headers={"Authorization": "Bearer credencial-falsa"})
        self._chk(r.status == 401, "con credencial falsa → 401", self._estado(r))
        r = self._http("GET", url, headers={"Authorization": f"Bearer {self.cfg.token_manifiesto}"})
        if not self._chk(r.status == 200 and isinstance(r.cuerpo, dict),
                         "con credencial válida → 200 y JSON", self._estado(r)):
            raise _Corte
        man = r.cuerpo
        self._chk(not (e := _errores(_schema("manifiesto.schema.json"), man)),
                  "el manifiesto cumple el schema", e)
        self._chk(man.get("contrato") == "1", "versión de contrato soportada (1)",
                  f"contrato={man.get('contrato')!r}")
        tools = [t for t in man.get("tools", []) if isinstance(t, dict)]
        nombres = [str(t.get("nombre", "")) for t in tools]
        self._chk(len(nombres) == len(set(nombres)), "nombres de tools únicos")
        self._chk(all(NOMBRE_RE.match(n) for n in nombres), "nombres de tools válidos",
                  ", ".join(n for n in nombres if not NOMBRE_RE.match(n)))
        self._chk(len(tools) <= 40, "≤ 40 tools", f"{len(tools)}")
        self._chk(r.bytes <= 256 * 1024, "manifiesto ≤ 256 KB", f"{r.bytes} bytes")
        for t in tools:
            try:
                Draft202012Validator.check_schema(t["parametros"])
            except Exception as ex:  # noqa: BLE001
                self._chk(False, f"`parametros` de {t.get('nombre')} es JSON Schema válido", str(ex)[:150])
        cortas = [t["nombre"] for t in tools if len(str(t.get("descripcion", ""))) < 30]
        if cortas:
            self._nota(AVISO, "descripciones muy cortas (el modelo no sabrá cuándo usarlas)", ", ".join(cortas))
        sin_desc = [t["nombre"] for t in tools
                    if any(not p.get("description") for p in t.get("parametros", {}).get("properties", {}).values())]
        if sin_desc:
            self._nota(AVISO, "parámetros sin `description`", ", ".join(sin_desc))
        if not [t for t in tools if t.get("efecto") == "lectura"]:
            self._chk(False, "hay al menos una tool de lectura")
            raise _Corte
        return tools

    def _autenticacion(self, tools: list[dict], token: str, claims: dict) -> None:
        self.inf.seccion = "Ejecución: autenticación"
        u = next(t["nombre"] for t in tools if t.get("efecto") == "lectura")
        self._chk(self._ejecutar(u, None).status == 401, "sin token → 401")
        self._chk(self._ejecutar(u, "basura").status == 401, "token ilegible → 401")
        firmado_ajeno = jwt.encode({**claims, "exp": int(time.time()) + 300}, uuid.uuid4().hex * 2,
                                   algorithm="HS256")
        r = self._ejecutar(u, firmado_ajeno)
        self._chk(r.status == 401, "token firmado con otra clave → 401", self._estado(r))
        r = self._ejecutar(u, _sin_firma(claims))
        self._chk(r.status == 401, "token alg=none → 401", self._estado(r))
        r = self._ejecutar(u, self.cfg.token_manifiesto)
        self._chk(r.status in (401, 403), "token de manifiesto usado en la ejecución → rechazado (401/403)",
                  self._estado(r))
        if not self.cfg.secreto_firma:
            for titulo in ("token vencido → 401", "token de otra audiencia → 401",
                           "token con scope ajeno → 403"):
                self._nota(OMITIDO, titulo, "requiere --secreto-firma-env")
            return
        ahora = int(time.time())
        r = self._ejecutar(u, self._forjar(claims, iat=ahora - 1200, exp=ahora - 600))
        self._chk(r.status == 401, "token vencido → 401", self._estado(r))
        r = self._ejecutar(u, self._forjar(claims, aud="otra-audiencia", iat=ahora, exp=ahora + 300))
        self._chk(r.status == 401, "token de otra audiencia → 401", self._estado(r))
        r = self._ejecutar(u, self._forjar(claims, scope="asistente:otro", iat=ahora, exp=ahora + 300))
        self._chk(r.status == 403, "token con scope ajeno → 403", self._estado(r))

    def _lecturas(self, tools: list[dict], token: str) -> None:
        self.inf.seccion = "Ejecución: tools de lectura"
        val = _schema("ejecucion-respuesta.schema.json")
        for t in (t for t in tools if t.get("efecto") == "lectura"):
            nombre = t["nombre"]
            if t.get("parametros", {}).get("required"):
                self._nota(OMITIDO, f"{nombre}: tiene parámetros obligatorios, no se ejecuta sola")
                continue
            r = self._ejecutar(nombre, token)
            cuerpo_ok = r.status == 200 and isinstance(r.cuerpo, dict)
            if not self._chk(cuerpo_ok and not (e := _errores(val, r.cuerpo)) and r.cuerpo.get("ok") is True,
                             f"{nombre}: responde ok y cumple el contrato",
                             (e if cuerpo_ok else self._estado(r))):
                continue
            limite_ms = self.cfg.max_ms or t.get("timeout_s", 15) * 1000
            self._chk(r.ms <= limite_ms, f"{nombre}: tiempo de respuesta", f"{r.ms:.0f} ms > {limite_ms:.0f} ms")
            if r.ms > min(limite_ms / 2, AVISO_MS) and r.ms <= limite_ms:
                self._nota(AVISO, f"{nombre}: respuesta lenta", f"{r.ms:.0f} ms")
            tope = self.cfg.max_kb * 1024
            self._chk(r.bytes <= tope, f"{nombre}: tamaño de la respuesta",
                      f"{r.bytes / 1024:.0f} KB > {self.cfg.max_kb} KB (el asistente la trunca)")
            if tope / 2 < r.bytes <= tope:
                self._nota(AVISO, f"{nombre}: respuesta grande", f"{r.bytes / 1024:.0f} KB")
            if _tiene_geometria(r.cuerpo.get("datos")):
                self._nota(AVISO, f"{nombre}: parece devolver geometrías", "resumir del lado del sistema")

    def _parametros(self, tools: list[dict], token: str) -> None:
        self.inf.seccion = "Ejecución: parámetros inválidos"
        lecturas = [t for t in tools if t.get("efecto") == "lectura"]

        def es_invalido(r: Resp) -> bool:
            return (r.status == 200 and isinstance(r.cuerpo, dict) and r.cuerpo.get("ok") is False
                    and r.cuerpo.get("error") == "parametros_invalidos")

        u = lecturas[0]["nombre"]
        r = self._ejecutar(u, token, crudo="no es json")
        self._chk(es_invalido(r), "cuerpo que no es JSON → parametros_invalidos", self._estado(r))
        r = self._ejecutar(u, token, crudo=json.dumps({"otra_cosa": {}}))
        self._chk(es_invalido(r), "cuerpo sin `parametros` → parametros_invalidos", self._estado(r))
        r = self._ejecutar("tool_que_no_existe", token)
        self._chk(r.status in (403, 404) or (r.status == 200 and isinstance(r.cuerpo, dict)
                                              and r.cuerpo.get("ok") is False),
                  "tool desconocida no produce éxito", self._estado(r))
        for t in lecturas[:MAX_TOOLS_PARAMETROS]:
            for descripcion, params in parametros_invalidos_para(t.get("parametros", {})):
                r = self._ejecutar(t["nombre"], token, params)
                self._chk(es_invalido(r), f"{t['nombre']}: {descripcion} → parametros_invalidos",
                          self._estado(r))

    def _ids_ajenos(self, tools: list[dict], token: str) -> None:
        self.inf.seccion = "Ejecución: ids ajenos"
        tool, param, tipo = self._tool_con_id(tools)
        if not tool:
            self._nota(OMITIDO, "ninguna tool de lectura recibe un id obligatorio",
                       "indicar una con --tool-id si existe")
            return
        propios = self._ids_visibles(tools, token)
        ajenos = {self.cfg.id_ajeno} if self.cfg.id_ajeno else set()
        if self.cfg.token_url_otro:
            r, otro = self._pedir_token(self.cfg.token_url_otro, self.cfg.cabecera_token_otro)
            if otro:
                ajenos |= self._ids_visibles(tools, otro) - propios
            else:
                self._nota(AVISO, "no se pudo obtener el token del otro usuario", self._estado(r))

        def valor(i: str):
            return int(i) if tipo == "integer" and i.isdigit() else i

        def ejecutar(i: str) -> Resp:
            return self._ejecutar(tool, token, {param: valor(i)})

        def no_visible(r: Resp) -> bool:
            return (r.status in (403, 404)) or (
                r.status == 200 and isinstance(r.cuerpo, dict) and r.cuerpo.get("ok") is False
                and r.cuerpo.get("error") in ERRORES_AJENO)

        if propios:
            r = ejecutar(min(propios))
            self._chk(r.status == 200 and isinstance(r.cuerpo, dict) and r.cuerpo.get("ok") is True,
                      f"{tool}: con un id propio responde ok", self._estado(r))
        inexistente = str(uuid.uuid4()) if tipo == "string" else "999999999"
        r = ejecutar(inexistente)
        self._chk(no_visible(r), f"{tool}: id inexistente → no_encontrado/sin_acceso", self._estado(r))
        if ajenos:
            r = ejecutar(min(ajenos))
            self._chk(no_visible(r), f"{tool}: id de otro usuario → no_encontrado/sin_acceso",
                      "devolvió datos de otro usuario" if r.status == 200 else self._estado(r))
        else:
            self._nota(OMITIDO, f"{tool}: id de otro usuario → no_encontrado/sin_acceso",
                       "requiere --token-url-otro o --id-ajeno")

    def _tool_con_id(self, tools: list[dict]) -> tuple[str | None, str, str]:
        for t in tools:
            if t.get("efecto") != "lectura":
                continue
            if self.cfg.tool_id and t["nombre"] != self.cfg.tool_id:
                continue
            schema = t.get("parametros", {})
            req = schema.get("required", [])
            tipos = {n: schema.get("properties", {}).get(n, {}).get("type") for n in req}
            if len(req) == 1 and tipos[req[0]] in ("string", "integer"):
                return t["nombre"], req[0], tipos[req[0]]
        return None, "", ""

    def _ids_visibles(self, tools: list[dict], token: str) -> set[str]:
        """Ids que un usuario ve en los listados que no piden parámetros."""
        ids: set[str] = set()
        for t in tools:
            if t.get("efecto") == "lectura" and not t.get("parametros", {}).get("required"):
                r = self._ejecutar(t["nombre"], token)
                if r.status == 200 and isinstance(r.cuerpo, dict) and r.cuerpo.get("ok") is True:
                    _ids(r.cuerpo.get("datos"), ids)
        return ids

    def _escrituras(self, tools: list[dict], token: str) -> None:
        self.inf.seccion = "Solo lectura"
        escrituras = [t for t in tools if t.get("efecto") == "escritura"]
        if not escrituras:
            self._nota(OMITIDO, "el sistema no declara tools de escritura")
        for t in escrituras:
            r = self._ejecutar(t["nombre"], token)
            self._chk(r.status == 403, f"escritura {t['nombre']} con scope de lectura → 403", self._estado(r))


def _desde_entorno(nombre: str | None, parser: argparse.ArgumentParser) -> str | None:
    if not nombre:
        return None
    valor = os.environ.get(nombre)
    if not valor:
        parser.error(f"la variable de entorno {nombre} no está definida")
    return valor


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--base-url", required=True)
    p.add_argument("--token-url", required=True, help="URL que emite un token para un usuario de prueba")
    p.add_argument("--cabecera-token-env", metavar="VAR")
    p.add_argument("--token-url-otro", metavar="URL")
    p.add_argument("--cabecera-token-otro-env", metavar="VAR")
    p.add_argument("--token-manifiesto", help="visible en la lista de procesos: preferir --token-manifiesto-env")
    p.add_argument("--token-manifiesto-env", metavar="VAR")
    p.add_argument("--secreto-firma-env", metavar="VAR")
    p.add_argument("--algoritmo-firma", default="HS256")
    p.add_argument("--id-ajeno")
    p.add_argument("--tool-id")
    p.add_argument("--max-kb", type=int, default=50)
    p.add_argument("--max-ms", type=int, help="tope de tiempo por ejecución (por defecto, timeout_s de la tool)")
    p.add_argument("--timeout", type=float, default=20)
    p.add_argument("--ruta-manifiesto", default="/asistente/tools")
    p.add_argument("--ruta-ejecucion", default="/asistente/tools/{nombre}")
    p.add_argument("--ruta-salud", default="/asistente/salud")
    a = p.parse_args(argv)

    manifiesto = a.token_manifiesto or _desde_entorno(a.token_manifiesto_env, p)
    if not manifiesto:
        p.error("falta --token-manifiesto-env (o --token-manifiesto)")
    cfg = Config(
        base_url=a.base_url, token_url=a.token_url, token_manifiesto=manifiesto,
        ruta_manifiesto=a.ruta_manifiesto, ruta_ejecucion=a.ruta_ejecucion, ruta_salud=a.ruta_salud,
        cabecera_token=_desde_entorno(a.cabecera_token_env, p),
        token_url_otro=a.token_url_otro,
        cabecera_token_otro=_desde_entorno(a.cabecera_token_otro_env, p),
        secreto_firma=_desde_entorno(a.secreto_firma_env, p), algoritmo_firma=a.algoritmo_firma,
        id_ajeno=a.id_ajeno, tool_id=a.tool_id, max_kb=a.max_kb,
        max_ms=a.max_ms, timeout=a.timeout,
    )
    destino = httpx.URL(a.base_url)
    print(f"Verificando {destino.scheme}://{destino.host}{f':{destino.port}' if destino.port else ''}"
          " contra el contrato v1")
    informe = Verificador(cfg).ejecutar()
    print(informe.texto())
    return 0 if informe.conforme else 1


if __name__ == "__main__":
    sys.exit(main())
