# Ported from ai-dlc (https://github.com/Sean-Koval/ai-dlc), src/ai_dlc/verification/test_proxy.py
# at f5be4f4206a8469f17d4b54296e41e06a2d1a41e, the handoff commit
# (tag eval-handoff-2026-10). Changes for flightdeck are listed in the docstring.
#
# MIT License
#
# Copyright (c) 2024 AI DLC contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""HTTPS CONNECT allowlisting proxy used only by live conformance containers.

Copied, not moved: ai-dlc keeps its own for provider conformance. Unchanged. The local runner never imports it:
`attempt.py` reads this file as text (`PROXY_SOURCE`) and runs it inside the proxy container, so no host path is
mounted.
"""

import ipaddress
import json
import os
import select
import socket
import socketserver


def resolve(host: str) -> list[str]:
    return sorted(
        {str(item[4][0]) for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    )


def allowed_destination(host, port, allowlist, resolver=resolve):
    if host not in allowlist or port != 443:
        return False
    addresses = resolver(host)
    return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline(8192).decode("ascii", errors="replace").strip().split()
        if len(line) != 3 or line[0] != "CONNECT":
            self.wfile.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            return
        try:
            host, port_text = line[1].rsplit(":", 1)
            port = int(port_text)
            addresses = resolve(host) if host in os.environ["ALLOW_HOSTS"].split(",") else []
            allowed = allowed_destination(
                host, port, set(os.environ["ALLOW_HOSTS"].split(",")), lambda _: addresses
            )
            # One line per decision; the evaluation runner retains this log as evidence.
            print(
                json.dumps({"allowed": allowed, "host": host, "port": port}, sort_keys=True),
                flush=True,
            )
            if not allowed:
                raise ValueError("denied destination")
            for _ in range(100):
                if self.rfile.readline(8192) in {b"\r\n", b"\n", b""}:
                    break
            else:
                raise ValueError("too many headers")
            # Connect the validated numeric address: a second DNS lookup cannot rebind it.
            remote = socket.create_connection((addresses[0], port), timeout=10)
        except (ValueError, OSError):
            self.wfile.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            return
        with remote:
            self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self.wfile.flush()
            while True:
                readable, _, _ = select.select([self.connection, remote], [], [], 60)
                if not readable:
                    break
                for stream in readable:
                    data = stream.recv(65536)
                    if not data:
                        return
                    (remote if stream is self.connection else self.connection).sendall(data)


if __name__ == "__main__":
    with socketserver.ThreadingTCPServer(("0.0.0.0", 8080), Handler) as server:
        server.serve_forever()
