"""Registro de métricas de uso: cola en memoria y escritura en lote a `evento_uso`.

Sirve para observar, no para facturar (eso es `uso_modelo`/`uso_voz`, transaccional): por eso registrar es
síncrono, no espera y nunca lanza, y si la BD falla o la cola se llena el evento se descarta y se cuenta.
Los rechazos por límite se agregan por (sistema, usuario, motivo, minuto) para que un abuso no multiplique filas.
"""

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente import precios
from asistente.core.ports import EventoMetrica
from asistente.store.models import EventoUso

log = logging.getLogger(__name__)

_COLUMNAS_MAX = {"motivo": 32, "usuario_ref": 256, "modelo": 200, "canal": 16}


class MetricasSql:
    def __init__(
        self, sesiones: async_sessionmaker[AsyncSession], tarifas: Callable[[], dict[str, dict]] | None = None,
        *, max_cola: int = 10_000, lote: int = 200, intervalo_s: float = 1.0,
        reloj: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sesiones = sesiones
        self._tarifas = tarifas or dict
        self._max_cola = max_cola
        self._lote = lote
        self._intervalo_s = intervalo_s
        self._reloj = reloj
        self._cola: deque[tuple[datetime, EventoMetrica]] = deque()
        self._limites: dict[tuple, tuple[datetime, EventoMetrica]] = {}
        self._avisado = False
        self.descartados = 0

    # ── registro (camino caliente: sin await, sin excepciones) ──
    def registrar(self, evento: EventoMetrica) -> None:
        try:
            ahora = self._reloj()
            evento = self._normalizar(evento)
            if evento.resultado == "limite":
                clave = (evento.sistema_id, evento.usuario_ref, evento.tipo, evento.motivo, evento.canal,
                         ahora.replace(second=0, microsecond=0))
                previo = self._limites.get(clave)
                if previo is not None:
                    self._limites[clave] = (previo[0], replace(previo[1], n=previo[1].n + evento.n))
                    return
                if self._llena():
                    return
                self._limites[clave] = (ahora, evento)
                return
            if self._llena():
                return
            self._cola.append((ahora, self._con_costo(evento)))
        except Exception:  # noqa: BLE001 contrato: registrar nunca afecta al turno
            self.descartados += 1
            log.warning("métricas: evento no registrado", exc_info=False)

    def _llena(self) -> bool:
        if len(self._cola) + len(self._limites) < self._max_cola:
            return False
        self.descartados += 1
        if not self._avisado:  # un solo aviso por cola llena, no uno por evento
            self._avisado = True
            log.warning("métricas: cola llena (%d); se descartan eventos", self._max_cola)
        return True

    @staticmethod
    def _normalizar(e: EventoMetrica) -> EventoMetrica:
        cambios = {c: getattr(e, c)[:n] for c, n in _COLUMNAS_MAX.items() if len(getattr(e, c)) > n}
        return replace(e, **cambios) if cambios else e

    def _con_costo(self, e: EventoMetrica) -> EventoMetrica:
        if e.costo_valle_usd is not None or e.costo_pico_usd is not None or not e.modelo:
            return e
        tarifa = self._tarifas().get(e.modelo)
        if not tarifa:
            return e  # sin tarifa: NULL, nunca 0
        if e.tipo == "tts":
            c = precios.costo_tts(e.unidades, tarifa)
            return replace(e, costo_valle_usd=c, costo_pico_usd=c)
        if e.tipo == "llm":
            return replace(
                e,
                costo_valle_usd=precios.costo(e.tokens_in, e.tokens_in_cache, e.tokens_out, tarifa, "valle"),
                costo_pico_usd=precios.costo(e.tokens_in, e.tokens_in_cache, e.tokens_out, tarifa, "pico"),
            )
        return e

    # ── escritura ──
    def pendientes(self) -> int:
        return len(self._cola) + len(self._limites)

    async def vaciar(self) -> None:
        """Escribe todo lo encolado, en lotes. Un lote que falla se descarta (no se reintenta ni se propaga)."""
        while self._cola or self._limites:
            filas: list[dict] = []
            while self._cola and len(filas) < self._lote:
                filas.append(self._fila(*self._cola.popleft()))
            while self._limites and len(filas) < self._lote:
                _, (creada, e) = self._limites.popitem()
                filas.append(self._fila(creada, self._con_costo(e)))
            self._avisado = False
            try:
                async with self._sesiones.begin() as s:
                    await s.execute(insert(EventoUso), filas)
            except Exception as e:  # noqa: BLE001 la BD caída no tumba nada; solo se pierde observabilidad
                self.descartados += len(filas)
                log.warning("métricas: lote de %d eventos descartado (%s)", len(filas), type(e).__name__)

    @staticmethod
    def _fila(creada: datetime, e: EventoMetrica) -> dict:
        return {**asdict(e), "creada": creada}

    async def bucle(self) -> None:
        """Vacía la cola cada `intervalo_s`. Se cancela al apagar; entonces el lifespan llama a `vaciar`."""
        while True:
            await asyncio.sleep(self._intervalo_s)
            await self.vaciar()
