"""Destinos salientes: una sola implementación del control anti-SSRF para todo lo que el panel puede apuntar
(`base_url` del conector y del manifiesto, `jwks_url`, `llm.base_url`).

La frontera de confianza es quien despliega, no quien edita en el panel: por defecto solo se conecta a direcciones
públicas; los destinos internos legítimos (otro contenedor, el LLM del host) se declaran en el entorno con
`ASISTENTE_HOSTS_INTERNOS_PERMITIDOS` (nombres exactos y/o redes CIDR).

El control real ocurre al conectar (`TransporteSeguro`): se resuelve el nombre, se validan **todas** las IPs y la
conexión va a una de ellas con `Host` y SNI del nombre original, así un DNS que cambie de respuesta entre la
comprobación y la conexión (rebinding) no lleva a otro lado. Nada puede saltarse la denegación fija (metadatos de
nube, link-local, `0.0.0.0/8`, multicast), ni siquiera una IP o nombre de la lista de permitidos.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

import httpx

IP = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[list[str]]]

_DENEGADAS = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "169.254.0.0/16", "100.100.100.200/32", "224.0.0.0/4",  # IPv4: any, link-local/metadatos, multicast
    "::/128", "fe80::/10", "fd00:ec2::254/128", "ff00::/8",              # IPv6: unspecified, link-local, metadatos
))
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_6TO4 = ipaddress.ip_network("2002::/16")


def _ipv4_incrustadas(ip: IP) -> list[ipaddress.IPv4Address]:
    """IPv4 que lleva dentro una IPv6 (mapeada, NAT64, 6to4): se evalúan igual que la IPv4 real."""
    if not isinstance(ip, ipaddress.IPv6Address):
        return []
    if ip.ipv4_mapped is not None:
        return [ip.ipv4_mapped]
    if ip in _NAT64:
        return [ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)]
    if ip in _6TO4:
        return [ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF)]
    return []


def _a_evaluar(ip: IP) -> list[IP]:
    incrustadas = _ipv4_incrustadas(ip)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return list(incrustadas)  # una IPv4 mapeada vale lo que la IPv4
    return [ip, *incrustadas]


def denegada(ip: IP) -> bool:
    """Destinos que ninguna lista de permitidos habilita."""
    return any(x in red for x in _a_evaluar(ip) for red in _DENEGADAS)


def ip_publica(ip: IP) -> bool:
    """Dirección enrutable en internet (no privada, loopback, reservada ni multicast), incluida la IPv4 que lleve
    dentro una IPv6 mapeada, NAT64 o 6to4."""
    return all(x.is_global and not x.is_multicast for x in _a_evaluar(ip)) and not denegada(ip)


@dataclass(frozen=True)
class ReglasRed:
    nombres: frozenset[str] = frozenset()
    redes: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()

    @classmethod
    def desde_texto(cls, texto: str, extra_nombres: Iterable[str] = ()) -> "ReglasRed":
        """`texto`: nombres y/o redes CIDR separados por coma (`mock-a,host.docker.internal,10.0.5.0/24`)."""
        nombres = {n.strip().rstrip(".").lower() for n in extra_nombres if n and n.strip()}
        redes = []
        for parte in (p.strip() for p in texto.split(",")):
            if not parte:
                continue
            try:
                redes.append(ipaddress.ip_network(parte, strict=False))
            except ValueError:
                nombres.add(parte.rstrip(".").lower())
        return cls(frozenset(nombres), tuple(redes))

    def permite(self, host: str, ips: list[IP]) -> bool:
        """`host`: el nombre pedido. Se comprueba primero contra la lista (nombres de Docker sin punto, cuya IP
        privada cambia al recrear el contenedor) y después la IP resuelta: lo denegado de forma fija no pasa nunca."""
        if not ips or any(denegada(ip) for ip in ips):
            return False
        if host in self.nombres:
            return True
        return all(ip_publica(ip) or any(ip in red for red in self.redes) for ip in ips)


class DestinoNoPermitido(httpx.ConnectError):
    """El destino no es una dirección pública ni está en la lista de permitidos. Subclase de `httpx.HTTPError`: los
    llamadores que ya manejan fallos de conexión lo tratan como tal."""


async def resolver_dns(host: str, puerto: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, puerto, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(i[4][0] for i in infos))


class TransporteSeguro(httpx.AsyncBaseTransport):
    """Transporte httpx que valida el destino al conectar y lo fija a la IP comprobada. Usarlo con
    `follow_redirects=False`: una API legítima no debería redirigir, y un salto nuevo exigiría revalidar y no
    reenviar credenciales a otro origen."""

    def __init__(self, reglas: ReglasRed, *, resolver: Resolver = resolver_dns,
                 transporte: httpx.AsyncBaseTransport | None = None) -> None:
        self._reglas = reglas
        self._resolver = resolver
        self._t = transporte or httpx.AsyncHTTPTransport()

    async def _destinos(self, request: httpx.Request) -> tuple[str, list[IP]]:
        url = request.url
        if url.scheme not in ("http", "https"):
            raise DestinoNoPermitido("esquema no permitido", request=request)
        host = url.host.rstrip(".").lower()
        puerto = url.port or (443 if url.scheme == "https" else 80)
        try:
            ips: list[IP] = [ipaddress.ip_address(host)]
        except ValueError:
            try:
                crudas = await self._resolver(host, puerto)
                ips = [ipaddress.ip_address(i.split("%", 1)[0]) for i in crudas]
            except (OSError, ValueError) as e:
                raise httpx.ConnectError("no se pudo resolver el host", request=request) from e
        if not self._reglas.permite(host, ips):
            # Sin la IP resuelta ni el cuerpo del destino: el mensaje llega al modelo y a los logs.
            raise DestinoNoPermitido(f"destino no permitido: {host}", request=request)
        return host, ips

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host, ips = await self._destinos(request)
        ultimo: httpx.ConnectError | None = None
        for ip in ips:
            ext = dict(request.extensions)
            if request.url.scheme == "https" and host != str(ip):
                ext["sni_hostname"] = host  # SNI y verificación del certificado contra el nombre, no la IP
            fijada = httpx.Request(request.method, request.url.copy_with(host=str(ip)), headers=request.headers,
                                   stream=request.stream, extensions=ext)
            try:
                return await self._t.handle_async_request(fijada)
            except httpx.ConnectError as e:  # solo antes de enviar nada: se puede probar la siguiente IP
                ultimo = e
        raise ultimo or httpx.ConnectError("sin direcciones", request=request)

    async def aclose(self) -> None:
        await self._t.aclose()
