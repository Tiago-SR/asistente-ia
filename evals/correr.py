"""Corre el set de preguntas contra un asistente en marcha y guarda resultados por modelo.

Mide por pregunta: aciertos, tools llamadas, iteraciones (llamadas al LLM), latencia, tokens y costo.
Usa el asistente real por HTTP, así que prueba todo el camino (token, tools, prompt, modelo).

Dentro del contenedor dev (el modelo y el LLM salen del .env del servicio asistente):
  docker compose -f docker-compose.dev.yml run --rm -v ./evals:/app/evals asistente python evals/correr.py

Variables / opciones: ver --help. Los resultados quedan en evals/resultados/<modelo>_<fecha>.{json,md}.
"""

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from puntuar import puntuar

AQUI = Path(__file__).parent


def leer_sse(r: httpx.Response):
    evento = None
    for linea in r.iter_lines():
        if linea.startswith("event:"):
            evento = linea[6:].strip()
        elif linea.startswith("data:") and evento:
            yield evento, json.loads(linea[5:])
            evento = None


class Cliente:
    def __init__(self, asistente: str, token_url: str, origen: str, timeout: float) -> None:
        self.http = httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0))
        self.asistente, self.token_url, self.origen = asistente.rstrip("/"), token_url, origen

    def token(self, usuario: str) -> str:
        r = self.http.get(self.token_url, params={"usuario": usuario})
        r.raise_for_status()
        return r.json()["token"]

    def turno(self, token: str, mensaje: str, conversacion: str | None) -> dict:
        """Un mensaje. Reintenta (sin contarlo) si se topa con el tope por minuto del usuario."""
        for _ in range(6):
            res = self._turno(token, mensaje, conversacion)
            if res["error"] == "mensajes_min":
                time.sleep(15)
                continue
            return res
        return res

    def _turno(self, token: str, mensaje: str, conversacion: str | None) -> dict:
        cuerpo = {"mensaje": mensaje, **({"conversacion_id": conversacion} if conversacion else {})}
        cabeceras = {"Authorization": f"Bearer {token}", "Origin": self.origen}
        res = {"texto": "", "tools": [], "propuestas": [], "iteraciones": 1, "error": None, "uso": {}, "conversacion": conversacion,
               "latencia_s": 0.0, "primer_token_s": None}
        inicio = time.monotonic()
        with self.http.stream("POST", f"{self.asistente}/v1/chat", json=cuerpo, headers=cabeceras) as r:
            if r.status_code != 200:
                res["error"] = f"http_{r.status_code}"
                return res
            for evento, datos in leer_sse(r):
                if evento == "delta":
                    if res["primer_token_s"] is None:
                        res["primer_token_s"] = round(time.monotonic() - inicio, 2)
                    res["texto"] += datos["texto"]
                elif evento == "tool":
                    res["iteraciones"] += 1
                    res["tools"] += [h.removeprefix("Consultando ") for h in datos["herramientas"]]
                elif evento == "confirmacion":
                    res["propuestas"].append({k: datos.get(k) for k in ("tool", "resumen", "lineas")})
                elif evento == "error":
                    res["error"] = datos["codigo"]
                elif evento == "token_expirado":
                    res["error"] = "token_expirado"
                elif evento == "done":
                    res["conversacion"], res["uso"] = datos["conversacion_id"], datos.get("uso", {})
        res["latencia_s"] = round(time.monotonic() - inicio, 2)
        return res


def costo(uso: dict, tarifa: dict | None, horario: str) -> float | None:
    if not tarifa:
        return None
    entrada, hit, salida = uso.get("tokens_in", 0), uso.get("tokens_in_cache", 0), uso.get("tokens_out", 0)
    return (
        (entrada - hit) * tarifa["entrada_cache_miss"][horario]
        + hit * tarifa["entrada_cache_hit"][horario]
        + salida * tarifa["salida"][horario]
    ) / 1e6


def correr_pregunta(cli: Cliente, p: dict, base: list[float], tarifa: dict | None) -> dict:
    token = cli.token(p["usuario"])
    conv, total, herramientas, propuestas, ultimo = None, {"tokens_in": 0, "tokens_out": 0, "tokens_in_cache": 0}, [], [], None
    latencia = iteraciones = 0
    for mensaje in p["turnos"]:
        ultimo = cli.turno(token, mensaje, conv)
        conv = ultimo["conversacion"]
        herramientas += ultimo["tools"]
        propuestas += ultimo["propuestas"]
        latencia += ultimo["latencia_s"]
        iteraciones += ultimo["iteraciones"]
        for k in total:
            total[k] += ultimo["uso"].get(k, 0)
        if ultimo["error"]:
            break
    puntaje = puntuar(p, ultimo["texto"], herramientas, base, ultimo["error"], propuestas)
    return {
        "id": p["id"], "categoria": p["categoria"], "usuario": p["usuario"], "turnos": p["turnos"],
        "ok": puntaje["ok"], "fallos": puntaje["fallos"], "respuesta": ultimo["texto"], "tools": herramientas, "propuestas": propuestas,
        "iteraciones": iteraciones, "latencia_s": round(latencia, 2), "primer_token_s": ultimo["primer_token_s"],
        "uso": total,
        "costo_usd": {h: costo(total, tarifa, h) for h in ("valle", "pico")} if tarifa else None,
    }


def resumir(resultados: list[dict]) -> dict:
    n = len(resultados)
    lat = sorted(r["latencia_s"] for r in resultados)
    por_cat: dict[str, list[bool]] = {}
    for r in resultados:
        por_cat.setdefault(r["categoria"], []).append(r["ok"])
    suma = {k: sum(r["uso"][k] for r in resultados) for k in ("tokens_in", "tokens_out", "tokens_in_cache")}
    resumen = {
        "preguntas": n,
        "aciertos": sum(r["ok"] for r in resultados),
        "tasa_acierto": round(sum(r["ok"] for r in resultados) / n, 3) if n else 0,
        "por_categoria": {c: f"{sum(v)}/{len(v)}" for c, v in sorted(por_cat.items())},
        "cifras_no_respaldadas": sum(any("no respaldada" in f for f in r["fallos"]) for r in resultados),
        "errores_servicio": sum(any(f.startswith("error del servicio") for f in r["fallos"]) for r in resultados),
        "iteraciones_media": round(statistics.mean(r["iteraciones"] for r in resultados), 2) if n else 0,
        "latencia_s": {"mediana": lat[n // 2] if n else 0, "p95": lat[min(n - 1, int(n * 0.95))] if n else 0},
        "tokens_por_pregunta": {k: round(v / n) for k, v in suma.items()} if n else {},
        "cache_hit_pct": round(100 * suma["tokens_in_cache"] / suma["tokens_in"], 1) if suma["tokens_in"] else 0,
    }
    if all(r["costo_usd"] for r in resultados) and n:
        resumen["costo_usd_por_pregunta"] = {
            h: round(statistics.mean(r["costo_usd"][h] for r in resultados), 6) for h in ("valle", "pico")
        }
    return resumen


def informe_md(modelo: str, fecha: str, resumen: dict, resultados: list[dict], nota: str | None) -> str:
    c = resumen.get("costo_usd_por_pregunta")
    lineas = [
        f"# Evals — {modelo} ({fecha})", "",
        *([f"> {nota}", ""] if nota else []),
        f"- **Aciertos:** {resumen['aciertos']}/{resumen['preguntas']} ({resumen['tasa_acierto']:.0%})",
        "- **Por categoría:** " + ", ".join(f"{k} {v}" for k, v in resumen["por_categoria"].items()),
        f"- **Con cifras no respaldadas:** {resumen['cifras_no_respaldadas']} · **errores del servicio:** {resumen['errores_servicio']}",
        f"- **Iteraciones por pregunta (llamadas al LLM):** {resumen['iteraciones_media']}",
        f"- **Latencia:** mediana {resumen['latencia_s']['mediana']} s, p95 {resumen['latencia_s']['p95']} s",
        f"- **Tokens por pregunta:** {resumen['tokens_por_pregunta']} · caché de entrada {resumen['cache_hit_pct']} %",
        *([f"- **Costo por pregunta (USD):** valle {c['valle']:.6f} · pico {c['pico']:.6f}"] if c else []),
        "", "## Fallos", "",
    ]
    fallidas = [r for r in resultados if not r["ok"]]
    if not fallidas:
        lineas.append("Ninguno.")
    for r in fallidas:
        lineas += [f"### {r['id']} ({r['categoria']}, {r['usuario']}): {r['turnos'][-1]}",
                   *[f"- {f}" for f in r["fallos"]], f"- Tools: {r['tools'] or 'ninguna'}",
                   *([f"- Propuestas: {r['propuestas']}"] if r.get("propuestas") else []),
                   f"- Respuesta: {r['respuesta'][:400]!r}", ""]
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asistente", default=os.environ.get("EVAL_ASISTENTE", "http://asistente:8000"))
    ap.add_argument("--preguntas", default=str(AQUI / "preguntas.yaml"),
                    help="archivo de preguntas (p. ej. evals/preguntas_acciones.yaml, contra mock-a)")
    ap.add_argument("--token-url", default=os.environ.get("EVAL_TOKEN_URL"),
                    help="por defecto, el `token_url` del archivo de preguntas")
    ap.add_argument("--origen", default=os.environ.get("EVAL_ORIGEN"),
                    help="Origin que se envía; debe estar en origenes_permitidos del sistema (por defecto, el del archivo)")
    ap.add_argument("--modelo", default=os.environ.get("ASISTENTE_MODELO_DEFAULT"),
                    help="nombre del modelo del asistente (solo etiqueta y tarifa; por defecto ASISTENTE_MODELO_DEFAULT)")
    ap.add_argument("--solo", help="ids separados por coma (p. ej. q02,q09)")
    ap.add_argument("--nota", help="texto libre para el informe (p. ej. 'thinking desactivado')")
    ap.add_argument("--salida", default=str(AQUI / "resultados"))
    ap.add_argument("--timeout", type=float, default=150.0)
    args = ap.parse_args()
    if not args.modelo:
        ap.error("falta --modelo (o ASISTENTE_MODELO_DEFAULT)")

    ruta = Path(args.preguntas)
    conjunto = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    token_url = args.token_url or conjunto.get("token_url", "http://sistema-php:8000/asistente/token")
    origen = args.origen or conjunto.get("origen", "http://localhost:8203")
    preguntas = conjunto["preguntas"]
    if args.solo:
        ids = set(args.solo.split(","))
        preguntas = [p for p in preguntas if p["id"] in ids]
    tarifa = (yaml.safe_load((AQUI / "precios.yaml").read_text(encoding="utf-8")) or {}).get(args.modelo)

    cli = Cliente(args.asistente, token_url, origen, args.timeout)
    resultados = []
    for p in preguntas:
        try:
            r = correr_pregunta(cli, p, conjunto["base_numeros"], tarifa)
        except httpx.HTTPError as e:
            print(f"{p['id']}: no se pudo consultar el asistente ({type(e).__name__}: {e})", file=sys.stderr)
            return 2
        resultados.append(r)
        print(f"{'OK  ' if r['ok'] else 'FALLO'} {r['id']} {r['latencia_s']:>6}s it={r['iteraciones']} "
              f"tok={r['uso']['tokens_in']}/{r['uso']['tokens_out']}  {'; '.join(r['fallos'])}", flush=True)
        if r["fallos"] and any(f == "error del servicio: mensajes_dia" for f in r["fallos"]):
            print("tope diario de mensajes alcanzado: abortando", file=sys.stderr)
            return 2

    resumen = resumir(resultados)
    ahora = datetime.now().astimezone()
    fecha = ahora.strftime("%Y-%m-%d_%H%M")
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    sufijo = "" if ruta.name == "preguntas.yaml" else "_" + ruta.stem.removeprefix("preguntas_")
    base = salida / f"{args.modelo}{sufijo}_{fecha}"
    base.with_suffix(".json").write_text(
        json.dumps({"modelo": args.modelo, "fecha": ahora.isoformat(timespec="seconds"), "nota": args.nota,
                    "resumen": resumen, "resultados": resultados}, ensure_ascii=False, indent=1), encoding="utf-8")
    base.with_suffix(".md").write_text(informe_md(args.modelo, fecha, resumen, resultados, args.nota), encoding="utf-8")
    print("\n" + json.dumps(resumen, ensure_ascii=False, indent=1))
    print(f"\nGuardado en {base}.json y .md")
    return 0 if resumen["aciertos"] == resumen["preguntas"] else 1


if __name__ == "__main__":
    sys.exit(main())
