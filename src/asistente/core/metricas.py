"""Colector de métricas en memoria: para tests y para ejecuciones sin base de datos (evals)."""

from asistente.core.ports import EventoMetrica


class MetricasMemoria:
    def __init__(self) -> None:
        self.eventos: list[EventoMetrica] = []

    def registrar(self, evento: EventoMetrica) -> None:
        self.eventos.append(evento)
