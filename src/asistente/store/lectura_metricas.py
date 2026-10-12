"""Lectura de métricas para el panel: series diarias, top de usuarios y tools.

Las series salen de `uso_diario` más, al vuelo, los días posteriores al último resumido de cada sistema (el resumen
corre en la purga: ayer puede faltar). Se calculan con los mismos SELECT que el resumen. Los percentiles no se
promedian ni se suman: o vienen de un grupo único (guardado) o se calculan exactos sobre los crudos.
Fechas UTC; `hasta` inclusivo.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.store.resumen import SELECT_EVENTOS, SELECT_TOOLS

RANGO_CRUDOS_MAX_DIAS = 90
STATEMENT_TIMEOUT_MS = 5000
ORDENES = {"turnos": "turnos", "tokens": "tokens", "rechazos": "rechazos"}

_SUMABLES = ("n", "tokens_in", "tokens_in_cache", "tokens_out", "unidades", "n_sin_tarifa", "latencia_sum_ms")


def _ts(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=UTC)


def _fila(r: dict[str, Any], fuente: str) -> dict[str, Any]:
    return {**r, "dia": r["dia"].isoformat(), "fuente": fuente}


def _agrupar_por_tipo(filas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """(dia, sistema, tipo, resultado). `usuarios` y los percentiles solo se conservan si el grupo tiene una
    única fila de detalle: sumarlos o promediarlos daría un número falso."""
    grupos: dict[tuple, list[dict[str, Any]]] = {}
    for f in filas:
        grupos.setdefault((f["dia"], f["sistema_id"], f["tipo"], f["resultado"]), []).append(f)
    salida = []
    for (dia, sistema, tipo, resultado), fs in sorted(grupos.items()):
        unica = len(fs) == 1
        fila = {"dia": dia, "sistema_id": sistema, "tipo": tipo, "resultado": resultado,
                "fuente": "crudos" if any(f["fuente"] == "crudos" for f in fs) else "resumen",
                "usuarios": fs[0]["usuarios"] if unica else None,
                "p50_ms": fs[0]["p50_ms"] if unica else None,
                "p95_ms": fs[0]["p95_ms"] if unica else None,
                "latencia_max_ms": max((f["latencia_max_ms"] for f in fs if f["latencia_max_ms"] is not None),
                                       default=None)}
        for c in _SUMABLES:
            fila[c] = sum(f[c] or 0 for f in fs)
        for c in ("costo_valle_usd", "costo_pico_usd"):
            valores = [f[c] for f in fs if f[c] is not None]
            fila[c] = sum(valores) if valores else None  # NULL = sin tarifa, nunca 0
        salida.append(fila)
    return salida


class MetricasLectura:
    def __init__(self, sesiones: async_sessionmaker[AsyncSession], reloj=lambda: datetime.now(UTC)) -> None:
        self._sesiones = sesiones
        self._reloj = reloj

    async def _ejecutar(self, s: AsyncSession, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        r = await s.execute(text(sql), params)
        return [dict(m) for m in r.mappings()]

    async def cobertura(self, s: AsyncSession, sistemas: list[str] | None) -> dict[str, Any]:
        filtro = "WHERE sistema_id = ANY(:ids)" if sistemas else ""
        p = {"ids": sistemas} if sistemas else {}
        resumido = (await s.execute(text(f"SELECT max(dia) FROM uso_diario {filtro}"), p)).scalar_one()
        crudos = (await s.execute(text(f"SELECT min(creada) FROM evento_uso {filtro}"), p)).scalar_one()
        tools = (await s.execute(text(f"SELECT min(creada) FROM llamadas_tool {filtro}"), p)).scalar_one()
        return {
            "resumido_hasta": resumido.isoformat() if resumido else None,
            "crudos_desde": crudos.astimezone(UTC).date().isoformat() if crudos else None,
            "tools_desde": tools.astimezone(UTC).date().isoformat() if tools else None,
        }

    async def series(
        self, sistemas: list[str], desde: date, hasta: date, *, filtrar: bool, tipo: str | None = None,
        resultado: str | None = None, agrupar: str = "detalle",
    ) -> dict[str, Any]:
        """`sistemas`: los que se calculan al vuelo (los del registro, o el elegido). `filtrar`: si es un
        sistema concreto, el resumen también se filtra por él; si no, entran todos (incluso los dados de baja)."""
        hoy = self._reloj().astimezone(UTC).date()
        ids = sistemas if filtrar else None
        async with self._sesiones() as s, s.begin():
            await s.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
            where = "dia BETWEEN :desde AND :hasta" + (" AND sistema_id = ANY(:ids)" if ids else "")
            p: dict[str, Any] = {"desde": desde, "hasta": hasta, **({"ids": ids} if ids else {})}
            filas = [_fila(r, "resumen") for r in await self._ejecutar(
                s, f"SELECT dia, sistema_id, tipo, modelo, resultado, motivo, canal, n, usuarios, tokens_in, "
                   f"tokens_in_cache, tokens_out, unidades, costo_valle_usd, costo_pico_usd, n_sin_tarifa, "
                   f"latencia_sum_ms, latencia_max_ms, p50_ms, p95_ms FROM uso_diario WHERE {where}", p)]
            ultimos = {r["sistema_id"]: r["ultimo"] for r in await self._ejecutar(
                s, "SELECT sistema_id, max(dia) AS ultimo FROM uso_diario WHERE tipo <> 'tool' "
                   "GROUP BY sistema_id", {})}
            for sid in sistemas:
                ultimo = ultimos.get(sid)
                inicio = max(desde, hoy - timedelta(days=RANGO_CRUDOS_MAX_DIAS))
                if ultimo is not None:
                    inicio = max(inicio, ultimo + timedelta(days=1))
                if inicio > hasta:
                    continue
                par = {"s": sid, "desde": _ts(inicio), "hasta": _ts(hasta + timedelta(days=1))}
                for sel, extra in ((SELECT_EVENTOS, {"extra": ""}), (SELECT_TOOLS, {})):
                    filas += [_fila(r, "crudos") for r in await self._ejecutar(s, sel.format(**extra), par)]
            cob = await self.cobertura(s, ids)
        if tipo:
            filas = [f for f in filas if f["tipo"] == tipo]
        if resultado:
            filas = [f for f in filas if f["resultado"] == resultado]
        filas.sort(key=lambda f: (f["dia"], f["sistema_id"], f["tipo"], f["modelo"], f["resultado"], f["motivo"],
                                  f["canal"]))
        if agrupar == "tipo":
            filas = _agrupar_por_tipo(filas)
        return {"cobertura": cob, "filas": filas}

    async def usuarios(
        self, sistemas: list[str] | None, desde: date, hasta: date, orden: str, limite: int,
    ) -> dict[str, Any]:
        """Top de usuarios sobre `evento_uso`. Percentiles y rangos: el llamador acota a 90 días."""
        col = ORDENES[orden]
        filtro = "AND sistema_id = ANY(:ids)" if sistemas else ""
        p: dict[str, Any] = {"desde": _ts(desde), "hasta": _ts(hasta + timedelta(days=1)), "lim": limite}
        if sistemas:
            p["ids"] = sistemas
        async with self._sesiones() as s, s.begin():
            await s.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
            filas = await self._ejecutar(s, f"""
                SELECT sistema_id, usuario_ref,
                       COALESCE(SUM(n) FILTER (WHERE tipo = 'llm' AND resultado <> 'limite'), 0) AS turnos,
                       COALESCE(SUM(n) FILTER (WHERE resultado = 'limite'), 0) AS rechazos,
                       COALESCE(SUM(n) FILTER (WHERE resultado = 'error'), 0) AS errores,
                       COALESCE(SUM(tokens_in + tokens_out), 0) AS tokens,
                       SUM(costo_valle_usd) AS costo_valle_usd, SUM(costo_pico_usd) AS costo_pico_usd,
                       COALESCE(SUM(n) FILTER (WHERE costo_valle_usd IS NULL AND resultado <> 'limite'), 0)
                           AS n_sin_tarifa,
                       max(creada) AS ultimo
                FROM evento_uso
                WHERE usuario_ref <> '' AND creada >= :desde AND creada < :hasta {filtro}
                GROUP BY sistema_id, usuario_ref
                ORDER BY {col} DESC, sistema_id, usuario_ref
                LIMIT :lim""", p)
            cob = await self.cobertura(s, sistemas)
        for f in filas:
            f["ultimo"] = f["ultimo"].astimezone(UTC).isoformat()
        return {"cobertura": cob, "filas": filas}

    async def contadores(self, claves: list[tuple[str, str]], sistemas: list[str]) -> dict[str, Any]:
        """Mensajes del día (UTC, la ventana `dia` de `limits.py`) por (sistema, usuario) y tokens del mes por
        sistema. Sin fila = 0."""
        ahora = self._reloj().astimezone(UTC)
        dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        mes = dia.replace(day=1)
        async with self._sesiones() as s, s.begin():
            await s.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
            usados: dict[tuple[str, str], int] = {}
            if claves:
                r = await s.execute(
                    text("SELECT sistema_id, usuario_ref, mensajes FROM contadores_uso "
                         "WHERE ventana = 'dia' AND inicio = :dia AND sistema_id = ANY(:ids) "
                         "AND usuario_ref = ANY(:refs)"),
                    {"dia": dia, "ids": sorted({c[0] for c in claves}), "refs": sorted({c[1] for c in claves})})
                usados = {(a, b): m for a, b, m in r.all()}
            tokens: dict[str, int] = {}
            if sistemas:
                r = await s.execute(
                    text("SELECT sistema_id, tokens FROM contadores_uso WHERE ventana = 'mes' "
                         "AND usuario_ref = '' AND inicio = :mes AND sistema_id = ANY(:ids)"),
                    {"mes": mes, "ids": sistemas})
                tokens = dict(r.all())
        return {"dia": usados, "mes": tokens, "reinicia_dia": (dia + timedelta(days=1)).isoformat(),
                "reinicia_mes": (mes.replace(day=28) + timedelta(days=4)).replace(day=1).isoformat()}

    async def tools(self, sistemas: list[str] | None, desde: date, hasta: date) -> dict[str, Any]:
        """Por tool: llamadas, errores y p50/p95 exactos sobre `llamadas_tool`. La duración incluye la espera
        del semáforo del conector: un p95 alto puede ser cola, no lentitud del sistema externo."""
        filtro = "AND sistema_id = ANY(:ids)" if sistemas else ""
        p: dict[str, Any] = {"desde": _ts(desde), "hasta": _ts(hasta + timedelta(days=1))}
        if sistemas:
            p["ids"] = sistemas
        async with self._sesiones() as s, s.begin():
            await s.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
            filas = await self._ejecutar(s, f"""
                SELECT sistema_id, tool, COUNT(*) AS n, COUNT(*) FILTER (WHERE NOT ok) AS errores,
                       (percentile_cont(0.5) WITHIN GROUP (ORDER BY duracion_ms))::int AS p50_ms,
                       (percentile_cont(0.95) WITHIN GROUP (ORDER BY duracion_ms))::int AS p95_ms,
                       MAX(duracion_ms) AS max_ms
                FROM llamadas_tool
                WHERE creada >= :desde AND creada < :hasta {filtro}
                GROUP BY sistema_id, tool
                ORDER BY sistema_id, n DESC, tool""", p)
            cob = await self.cobertura(s, sistemas)
        return {"cobertura": cob, "filas": filas}
