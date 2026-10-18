"""SSRF protection for outbound requests made by built-in nodes.

The guard resolves the hostname itself, checks every resolved address and then connects to that
exact address, so a DNS answer cannot change between "check" and "use" (DNS rebinding). TLS still
verifies the original hostname because httpcore passes it separately from the connect address.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from typing import Any

import httpcore

_NAT64 = ipaddress.ip_network("64:ff9b::/96")


class BlockedAddress(Exception):
    pass


def _embedded_v4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if ip.ipv4_mapped:
        return ip.ipv4_mapped
    if ip.sixtofour:
        return ip.sixtofour
    if ip in _NAT64:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip.teredo:
        return ip.teredo[1]
    return None


def check_ip(address: str) -> None:
    """Raise BlockedAddress unless `address` is a public, globally routable unicast address."""
    ip = ipaddress.ip_address(address.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _embedded_v4(ip)
        if embedded is not None:
            check_ip(str(embedded))
    if not ip.is_global or ip.is_multicast:
        raise BlockedAddress(f"{address} is not a public address")


class GuardedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, allow_private: bool = False) -> None:
        self.allow_private = allow_private
        self._inner = httpcore.AnyIOBackend()

    async def resolve(self, host: str, port: int) -> list[str]:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise httpcore.ConnectError(f"cannot resolve {host}") from e
        addrs: list[str] = []
        for info in infos:
            addr = str(info[4][0])
            if addr not in addrs:
                addrs.append(addr)
        if not addrs:
            raise httpcore.ConnectError(f"cannot resolve {host}")
        if not self.allow_private:
            for addr in addrs:  # one private answer poisons the whole lookup
                try:
                    check_ip(addr)
                except BlockedAddress as e:
                    raise BlockedAddress(f"{host}: {e}") from e
        return addrs

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        last: Exception | None = None
        for addr in await self.resolve(host, port):
            try:
                return await self._inner.connect_tcp(
                    addr, port, timeout, local_address, socket_options
                )
            except httpcore.ConnectError as e:
                last = e
        raise last or httpcore.ConnectError(f"cannot connect to {host}")

    async def connect_unix_socket(self, *args: Any, **kwargs: Any) -> httpcore.AsyncNetworkStream:
        raise BlockedAddress("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)
