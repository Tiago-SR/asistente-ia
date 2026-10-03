"""Verificador de conformidad con el contrato v1.

Uso:
  python herramientas/verificar_sistema.py --base-url http://localhost:8201 \
      --token-url "http://localhost:8201/asistente/token?usuario=ana" \
      --token-manifiesto manifiesto-mock-a

Solo necesita httpx, jsonschema y pyjwt. Sale con código 1 si algún chequeo falla.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import httpx
import jwt
from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).resolve().parent.parent / "contrato" / "schemas"
NOMBRE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
resultados: list[tuple[bool, str, str]] = []


def schema(nombre: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMAS / nombre).read_text()))


def chequeo(ok: bool, titulo: str, detalle: str = "") -> bool:
    resultados.append((ok, titulo, detalle))
    print(f"[{'OK' if ok else 'FALLA'}] {titulo}" + (f" — {detalle}" if detalle and not ok else ""))
    return ok


def errores(validador: Draft202012Validator, instancia) -> str:
    return "; ".join(
        f"{'/'.join(map(str, e.path)) or '<raíz>'}: {e.message}"
        for e in validador.iter_errors(instancia)
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--base-url", required=True)
    p.add_argument("--token-url", required=True, help="URL que emite un token para un usuario de prueba")
    p.add_argument("--token-manifiesto", required=True)
    p.add_argument("--ruta-manifiesto", default="/asistente/tools")
    p.add_argument("--ruta-ejecucion", default="/asistente/tools/{nombre}")
    p.add_argument("--ruta-salud", default="/asistente/salud")
    a = p.parse_args()

    base = a.base_url.rstrip("/")
    c = httpx.Client(timeout=20, follow_redirects=False)
    hdr = lambda tok: {"Authorization": f"Bearer {tok}"}
    ejec = lambda n: base + a.ruta_ejecucion.format(nombre=n)
    cab_ej = {"X-Asistente-Contrato": "1", "Content-Type": "application/json"}

    # Salud (opcional)
    r = c.get(base + a.ruta_salud)
    if r.status_code == 404:
        print("[--] salud no implementada (opcional)")
    else:
        chequeo(r.status_code == 200 and r.json().get("ok") is True, "salud devuelve {ok: true}")

    # Token de usuario
    r = c.get(a.token_url)
    if not chequeo(r.status_code == 200, "ruta de token responde 200", f"status {r.status_code}"):
        return resumen()
    cuerpo = r.json()
    chequeo(not (e := errores(schema("token-respuesta.schema.json"), cuerpo)), "respuesta de token cumple schema", e)
    token = cuerpo.get("token", "")
    try:
        cab = jwt.get_unverified_header(token)
        claims = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
    except jwt.PyJWTError as e:
        chequeo(False, "el token es un JWT legible", str(e))
        return resumen()
    chequeo(cab.get("alg", "none").lower() != "none", "alg distinto de none", str(cab))
    chequeo(not (e := errores(schema("token-claims.schema.json"), claims)), "claims cumplen schema", e)
    vida = claims.get("exp", 0) - claims.get("iat", 0)
    chequeo(0 < vida <= 15 * 60, "vida del token ≤ 15 min", f"{vida}s")

    # Manifiesto
    chequeo(c.get(base + a.ruta_manifiesto).status_code == 401, "manifiesto sin credencial → 401")
    chequeo(
        c.get(base + a.ruta_manifiesto, headers=hdr("credencial-falsa")).status_code == 401,
        "manifiesto con credencial falsa → 401",
    )
    r = c.get(base + a.ruta_manifiesto, headers=hdr(a.token_manifiesto))
    if not chequeo(r.status_code == 200, "manifiesto con credencial válida → 200", f"status {r.status_code}"):
        return resumen()
    man = r.json()
    chequeo(not (e := errores(schema("manifiesto.schema.json"), man)), "manifiesto cumple schema", e)
    tools = man.get("tools", [])
    nombres = [t.get("nombre", "") for t in tools]
    chequeo(len(nombres) == len(set(nombres)), "nombres de tools únicos")
    chequeo(all(NOMBRE_RE.match(n) for n in nombres), "nombres de tools válidos")
    chequeo(len(r.content) <= 256 * 1024, "manifiesto ≤ 256 KB")
    for t in tools:
        try:
            Draft202012Validator.check_schema(t["parametros"])
        except Exception as ex:  # noqa: BLE001
            chequeo(False, f"parametros de {t.get('nombre')} es JSON Schema válido", str(ex))

    # Ejecución: autenticación
    lecturas = [t for t in tools if t.get("efecto") == "lectura"]
    escrituras = [t for t in tools if t.get("efecto") == "escritura"]
    if not lecturas:
        chequeo(False, "hay al menos una tool de lectura")
        return resumen()
    u = lecturas[0]["nombre"]
    cuerpo_vacio = json.dumps({"parametros": {}})
    chequeo(c.post(ejec(u), headers=cab_ej, content=cuerpo_vacio).status_code == 401, "ejecución sin token → 401")
    chequeo(
        c.post(ejec(u), headers={**cab_ej, **hdr("basura")}, content=cuerpo_vacio).status_code == 401,
        "ejecución con token inválido → 401",
    )
    chequeo(
        c.post(ejec(u), headers={**cab_ej, **hdr(a.token_manifiesto)}, content=cuerpo_vacio).status_code in (401, 403),
        "ejecución con token de manifiesto → rechazada (401/403)",
    )
    chequeo(
        c.post(ejec(u), headers={**cab_ej, **hdr(_sin_firma(claims))}, content=cuerpo_vacio).status_code == 401,
        "ejecución con token alg=none → 401",
    )

    # Ejecución: tools de lectura sin parámetros obligatorios
    val_resp = schema("ejecucion-respuesta.schema.json")
    for t in lecturas:
        if t["parametros"].get("required"):
            print(f"[--] {t['nombre']}: tiene parámetros obligatorios, no se ejecuta automáticamente")
            continue
        r = c.post(ejec(t["nombre"]), headers={**cab_ej, **hdr(token)}, content=cuerpo_vacio)
        ok = r.status_code == 200 and not (e := errores(val_resp, r.json()))
        chequeo(ok, f"ejecutar {t['nombre']} cumple el contrato", f"status {r.status_code} {r.text[:200]}")

    # Ejecución: parámetros inválidos y tool desconocida
    r = c.post(ejec(u), headers={**cab_ej, **hdr(token)}, content="no es json")
    chequeo(
        r.status_code in (200, 400, 422) and (r.status_code != 200 or r.json().get("ok") is False),
        "cuerpo inválido no produce éxito",
        f"status {r.status_code}",
    )
    r = c.post(ejec("tool_que_no_existe"), headers={**cab_ej, **hdr(token)}, content=cuerpo_vacio)
    chequeo(
        r.status_code in (404, 403) or (r.status_code == 200 and r.json().get("ok") is False),
        "tool desconocida no produce éxito",
        f"status {r.status_code}",
    )

    # Solo lectura: las tools de escritura se rechazan con scope de lectura
    for t in escrituras:
        r = c.post(ejec(t["nombre"]), headers={**cab_ej, **hdr(token)}, content=cuerpo_vacio)
        chequeo(r.status_code == 403, f"escritura {t['nombre']} con scope de lectura → 403", f"status {r.status_code}")

    return resumen()


def _sin_firma(claims: dict) -> str:
    """JWT con alg=none y los mismos claims (no debe ser aceptado)."""
    import base64

    b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims)}."


def resumen() -> int:
    fallos = [r for r in resultados if not r[0]]
    print(f"\n{len(resultados) - len(fallos)}/{len(resultados)} chequeos correctos")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
