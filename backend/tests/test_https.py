"""HTTPS path of the http.request node, against a local TLS server with a throwaway CA."""

import json
import ssl
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
import trustme

from app.domain.nodes import NodeContext
from app.nodes.builtin.http_request import HttpRequestNode


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps({"secure": True, "host": self.headers.get("Host")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def tls() -> Iterator[dict[str, Any]]:
    ca = trustme.CA()
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ca.issue_cert("localhost").configure_cert(server_ctx)  # certificate valid for "localhost" only
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.socket = server_ctx.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    client_ctx = ssl.create_default_context()
    ca.configure_trust(client_ctx)  # trusts the throwaway CA
    yield {"port": httpd.server_address[1], "trusting": client_ctx}
    httpd.shutdown()


def ctx() -> NodeContext:
    return NodeContext(8)


async def fetch(node: HttpRequestNode, url: str) -> Any:
    return await node.execute(ctx(), None, {"url": url, "timeout_s": 5})


async def test_https_succeeds_with_a_trusted_certificate(tls: dict[str, Any]) -> None:
    node = HttpRequestNode(allow_private=True, ssl_context=tls["trusting"])
    res = await fetch(node, f"https://localhost:{tls['port']}/")
    assert res.status == "succeeded", res.error
    assert res.output["body"]["secure"] is True


async def test_certificate_is_verified_against_the_url_hostname_not_the_pinned_ip(
    tls: dict[str, Any],
) -> None:
    """The guard connects to the resolved IP; TLS must still check the name from the URL."""
    node = HttpRequestNode(allow_private=True, ssl_context=tls["trusting"])
    ok = await fetch(node, f"https://localhost:{tls['port']}/")
    assert ok.status == "succeeded"
    # same server, same CA, but the URL names an address the certificate does not cover
    bad = await fetch(node, f"https://127.0.0.1:{tls['port']}/")
    assert bad.status == "failed" and bad.error and bad.error.type == "network_error"


async def test_untrusted_certificate_is_rejected_by_default(tls: dict[str, Any]) -> None:
    node = HttpRequestNode(allow_private=True)  # default context: certifi bundle only
    res = await fetch(node, f"https://localhost:{tls['port']}/")
    assert res.status == "failed" and res.error and res.error.type == "network_error"
    assert "CERTIFICATE" in res.error.message.upper() or "SSL" in res.error.message.upper()


async def test_https_to_private_address_is_still_blocked_by_the_guard(tls: dict[str, Any]) -> None:
    node = HttpRequestNode(ssl_context=tls["trusting"])  # allow_private False
    res = await fetch(node, f"https://localhost:{tls['port']}/")
    assert res.error and res.error.type == "blocked_request"
