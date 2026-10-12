"""Resumen diario (`uso_diario`) y purga de las métricas crudas (`evento_uso`, `contadores_uso`).

El resumen se recalcula de forma idempotente (ON CONFLICT DO UPDATE) sobre una ventana de días UTC; la purga de
`evento_uso` solo borra días completos que ya tienen resumen, así recalcular nunca sobrescribe con datos parciales.
"""

from datetime import UTC, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

VENTANA_DIAS = 7  # días hacia atrás que se recalculan en cada pasada
RETENCION_MAX_DIAS = 90  # tope de los crudos de `evento_uso`
CONTADORES_DIAS = 2  # filas `min` y `dia` de `contadores_uso` más viejas que esto ya no sirven
LOTE = 5000

_DIA = "(creada AT TIME ZONE 'UTC')::date"
_COLUMNAS = (
    "dia, sistema_id, tipo, modelo, resultado, motivo, canal, n, usuarios, tokens_in, tokens_in_cache, "
    "tokens_out, unidades, costo_valle_usd, costo_pico_usd, n_sin_tarifa, latencia_sum_ms, latencia_max_ms, "
    "p50_ms, p95_ms"
)
_CLAVE = "dia, sistema_id, tipo, modelo, resultado, motivo, canal"
_ACTUALIZAR = ", ".join(
    f"{c} = EXCLUDED.{c}"
    for c in _COLUMNAS.replace(" ", "").split(",")
    if c not in _CLAVE.replace(" ", "").split(",")
)
_UPSERT = f"ON CONFLICT ({_CLAVE}) DO UPDATE SET {_ACTUALIZAR}"

# Los SELECT se reutilizan para calcular al vuelo los días aún sin resumen (`lectura_metricas`), con los mismos
# alias que las columnas de `uso_diario`.
SELECT_EVENTOS = f"""
SELECT {_DIA} AS dia, sistema_id, tipo, modelo, resultado, motivo, canal,
       SUM(n) AS n, COUNT(DISTINCT NULLIF(usuario_ref, '')) AS usuarios, SUM(tokens_in) AS tokens_in,
       SUM(tokens_in_cache) AS tokens_in_cache, SUM(tokens_out) AS tokens_out, SUM(unidades) AS unidades,
       SUM(costo_valle_usd) AS costo_valle_usd, SUM(costo_pico_usd) AS costo_pico_usd,
       COALESCE(SUM(n) FILTER (WHERE costo_valle_usd IS NULL AND resultado <> 'limite'), 0) AS n_sin_tarifa,
       COALESCE(SUM(duracion_ms), 0) AS latencia_sum_ms, MAX(duracion_ms) AS latencia_max_ms,
       (percentile_cont(0.5) WITHIN GROUP (ORDER BY duracion_ms))::int AS p50_ms,
       (percentile_cont(0.95) WITHIN GROUP (ORDER BY duracion_ms))::int AS p95_ms
FROM evento_uso e
WHERE sistema_id = :s AND creada >= :desde AND creada < :hasta {{extra}}
GROUP BY {_DIA}, sistema_id, tipo, modelo, resultado, motivo, canal
"""
_EVENTOS = f"INSERT INTO uso_diario ({_COLUMNAS}) {SELECT_EVENTOS} {_UPSERT}"

# Un día de un sistema se considera resumido si tiene alguna fila que no sea de tools.
_SIN_RESUMEN = f"""AND NOT EXISTS (
    SELECT 1 FROM uso_diario u
    WHERE u.sistema_id = e.sistema_id AND u.dia = {_DIA} AND u.tipo <> 'tool')"""

SELECT_TOOLS = f"""
SELECT {_DIA} AS dia, sistema_id, 'tool' AS tipo, tool AS modelo,
       CASE WHEN ok THEN 'ok' ELSE 'error' END AS resultado, '' AS motivo, '' AS canal,
       COUNT(*) AS n, COUNT(DISTINCT usuario_ref) AS usuarios, 0 AS tokens_in, 0 AS tokens_in_cache,
       0 AS tokens_out, 0 AS unidades, NULL::float AS costo_valle_usd, NULL::float AS costo_pico_usd,
       0 AS n_sin_tarifa, COALESCE(SUM(duracion_ms), 0) AS latencia_sum_ms, MAX(duracion_ms) AS latencia_max_ms,
       (percentile_cont(0.5) WITHIN GROUP (ORDER BY duracion_ms))::int AS p50_ms,
       (percentile_cont(0.95) WITHIN GROUP (ORDER BY duracion_ms))::int AS p95_ms
FROM llamadas_tool
WHERE sistema_id = :s AND creada >= :desde AND creada < :hasta
GROUP BY {_DIA}, sistema_id, tool, ok
"""
_TOOLS = f"INSERT INTO uso_diario ({_COLUMNAS}) {SELECT_TOOLS} {_UPSERT}"

_DIA_E = _DIA.replace("creada", "e.creada")
_BORRAR_EVENTOS = f"""
DELETE FROM evento_uso WHERE id IN (
    SELECT e.id FROM evento_uso e
    WHERE e.sistema_id = :s AND e.creada < :corte
      AND EXISTS (SELECT 1 FROM uso_diario u
                  WHERE u.sistema_id = e.sistema_id AND u.dia = {_DIA_E}
                    AND u.tipo <> 'tool')
    LIMIT :lote)
"""

_BORRAR_CONTADORES = """
DELETE FROM contadores_uso WHERE id IN (
    SELECT id FROM contadores_uso WHERE ventana IN ('min', 'dia') AND inicio < :corte LIMIT :lote)
"""


def _inicio_dia(ahora: datetime) -> datetime:
    return datetime.combine(ahora.astimezone(UTC).date(), time.min, tzinfo=UTC)


def _corte_eventos(hoy: datetime, retencion_dias: int) -> datetime:
    """Primer instante conservado de `evento_uso`: frontera de día UTC, para purgar solo días completos."""
    return hoy - timedelta(days=max(1, min(RETENCION_MAX_DIAS, retencion_dias)))


class ResumenSql:
    def __init__(self, sesiones: async_sessionmaker[AsyncSession]) -> None:
        self._sesiones = sesiones

    async def resumir(self, sistema_id: str, retencion_dias: int, ahora: datetime | None = None) -> int:
        """Recalcula `uso_diario` de `hoy-7` a `ayer` (UTC). Los eventos no se recalculan por debajo del
        corte de purga (un día a medio borrar daría un resumen parcial). Las tools se leen de
        `llamadas_tool`, que se purga a `retencion_dias` sin avisar: su ventana queda por debajo para no
        recalcular un día ya recortado. Devuelve las filas escritas."""
        hoy = _inicio_dia(ahora or datetime.now(UTC))
        n = 0
        async with self._sesiones.begin() as s:
            r = await s.execute(
                text(_EVENTOS.format(extra="")),
                {"s": sistema_id, "desde": max(hoy - timedelta(days=VENTANA_DIAS), _corte_eventos(hoy, retencion_dias)),
                    "hasta": hoy},
            )
            n += r.rowcount
            dias_tools = min(VENTANA_DIAS, retencion_dias - 1)
            if dias_tools >= 1:
                r = await s.execute(
                    text(_TOOLS), {"s": sistema_id, "desde": hoy - timedelta(days=dias_tools), "hasta": hoy}
                )
                n += r.rowcount
        return n

    async def purgar_eventos(self, sistema_id: str, retencion_dias: int, ahora: datetime | None = None) -> int:
        """Borra los crudos de `evento_uso` más viejos que `min(90, retencion_dias)`, por días UTC completos
        y solo si el día ya tiene resumen. Un día sin resumen (p. ej. tras una caída larga) se resume antes."""
        corte = _corte_eventos(_inicio_dia(ahora or datetime.now(UTC)), retencion_dias)
        async with self._sesiones.begin() as s:
            await s.execute(
                text(_EVENTOS.format(extra=_SIN_RESUMEN)),
                {"s": sistema_id, "desde": datetime(2000, 1, 1, tzinfo=UTC), "hasta": corte},
            )
        return await self._borrar_en_lotes(_BORRAR_EVENTOS, {"s": sistema_id, "corte": corte})

    async def purgar_contadores(self, ahora: datetime | None = None) -> int:
        """Quita las ventanas `min` y `dia` antiguas de `contadores_uso` (la mensual se conserva)."""
        corte = (ahora or datetime.now(UTC)) - timedelta(days=CONTADORES_DIAS)
        return await self._borrar_en_lotes(_BORRAR_CONTADORES, {"corte": corte})

    async def _borrar_en_lotes(self, sql: str, params: dict) -> int:
        total = 0
        while True:
            async with self._sesiones.begin() as s:
                r = await s.execute(text(sql), {**params, "lote": LOTE})
            total += r.rowcount
            if r.rowcount < LOTE:
                return total
