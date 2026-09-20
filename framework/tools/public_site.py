#!/usr/bin/env python3
"""
public_site.py — hardened read-only server for the static StoryOS stage.

Deliberately minimal, because this one gets a PUBLIC tunnel:
  • binds 127.0.0.1 only (reached via the tunnel, never directly)
  • serves only files under STORYOS_SITE_DIR, extension-allowlisted
  • no directory listing, no write routes, no project paths, NO chapter prose
"""
from __future__ import annotations

import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(os.environ.get("STORYOS_SITE_DIR", str(Path.home() / "storyos-site"))).resolve()
OK = {".html", ".md", ".txt", ".json", ".jsonl", ".css", ".js"}
CT = {".html": "text/html; charset=utf-8", ".md": "text/plain; charset=utf-8",
      ".txt": "text/plain; charset=utf-8", ".json": "application/json",
      ".jsonl": "application/json", ".css": "text/css", ".js": "text/javascript"}


class H(BaseHTTPRequestHandler):
    server_version = "StoryOS/1.0"

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % a))

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", cache)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):                                # noqa: N802
        self._serve()

    def do_HEAD(self):                                # noqa: N802
        self._serve()

    def do_POST(self):                                # noqa: N802
        self._send(405, b"read-only public mirror: no writes here\n")

    def _serve(self):
        if not ROOT.is_dir():
            return self._send(503, f"stage not built at {ROOT}\n".encode())
        raw = unquote(urlparse(self.path).path)
        if "\x00" in raw or ".." in raw:
            return self._send(400, b"bad path\n")
        rel = raw.lstrip("/") or "index.html"
        f = (ROOT / rel)
        try:
            f = f.resolve()
            f.relative_to(ROOT)                      # containment check, always
        except (ValueError, OSError):
            return self._send(404, b"not found\n")
        if f.is_dir():
            f = f / "index.html"                     # one deliberate exception: / → portal
        if not f.is_file() or f.suffix not in OK:
            return self._send(404, b"not found\n")
        try:
            data = f.read_bytes()
        except OSError as e:
            return self._send(500, str(e).encode())
        cache = "public, max-age=300" if f.suffix in (".html", ".css", ".js") else "no-store"
        self._send(200, data, CT.get(f.suffix, "application/octet-stream"), cache)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4181
    print(f"public mirror: {ROOT} → http://127.0.0.1:{port}  (read-only, allowlisted extensions)")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
