#!/usr/bin/env python3
"""Pre-agent webhook stub — logs Alertmanager payloads on :8080/alerts.

Stands in for the Sentinel agent (Phase 4) so Phase 3 can prove the
alert -> Alertmanager -> webhook path end to end. Prints each group's groupKey
plus every alert's name/service/severity/status, so you can eyeball:
  * routing   (the right alert with the right service label arrives), and
  * dedup     (a repeated fault shows the SAME groupKey — contracts §7).

Stdlib only, so it runs on ctrl-1 with no pip install. The agent will later
claim this same :8080/alerts route.
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/alerts":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return
        self._log(payload)
        self._send(200, {"received": True})

    def _log(self, p: dict) -> None:
        print(
            f"\n=== webhook: groupKey={p.get('groupKey')} status={p.get('status')} ===",
            flush=True,
        )
        for a in p.get("alerts", []):
            lb = a.get("labels", {})
            print(
                f"  [{a.get('status')}] {lb.get('alertname')} "
                f"service={lb.get('service')} severity={lb.get('severity')} "
                f"fingerprint={a.get('fingerprint')}",
                flush=True,
            )

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        pass  # suppress default access logs; we print our own


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
