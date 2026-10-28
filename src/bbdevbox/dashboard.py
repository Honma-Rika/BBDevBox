import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlparse

from .report import compare


def handler_class(store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond_headers(self, kind):
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
            self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            try:
                if parsed.path == "/":
                    self.respond_headers("text/html; charset=utf-8")
                    self.wfile.write(files("bbdevbox").joinpath("web/index.html").read_bytes())
                    return
                if parsed.path == "/dashboard.js":
                    self.respond_headers("text/javascript; charset=utf-8")
                    self.wfile.write(files("bbdevbox").joinpath("web/dashboard.js").read_bytes())
                    return
                if parsed.path == "/api/runs":
                    payload = store.overview()
                elif parsed.path == "/api/info":
                    payload = {"root": str(store.root), "database": str(store.path)}
                elif parsed.path.startswith("/api/run/"):
                    key = parsed.path.removeprefix("/api/run/")
                    run = store.run(key)
                    payload = {"run": {k: v for k, v in run.items() if k != "tasks"},
                               "attempts": store.attempts(key)}
                elif parsed.path == "/api/compare":
                    ids = params.get("ids", [""])[0].split(",")
                    if not 1 <= len(ids) <= 20:
                        raise ValueError("Compare 1..20 runs")
                    payload = compare(store, ids)
                elif parsed.path == "/api/events":
                    key = params.get("run", [""])[0]
                    store.run(key)
                    cursor = int(self.headers.get("Last-Event-ID", params.get("after", ["0"])[0]))
                    self.respond_headers("text/event-stream; charset=utf-8")
                    while True:
                        events = store.events(key, cursor)
                        for event in events:
                            cursor = event["seq"]
                            self.wfile.write(f"id: {cursor}\ndata: {json.dumps(event)}\n\n".encode())
                        if not events:
                            self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        if not events and store.run(key)["status"] != "running":
                            self.wfile.write(b"event: done\ndata: {}\n\n")
                            self.wfile.flush()
                            return
                        time.sleep(1)
                    return
                else:
                    self.send_error(404)
                    return
                self.respond_headers("application/json; charset=utf-8")
                self.wfile.write(json.dumps(payload, ensure_ascii=False).encode())
            except (BrokenPipeError, ConnectionResetError):
                return
            except (ValueError, KeyError) as exc:
                self.send_error(400, str(exc))

    return Handler


def serve(store, host="127.0.0.1", port=8765):
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Dashboard is read-only and binds to loopback only; use an authenticated SSH tunnel")
    server = ThreadingHTTPServer((host, port), handler_class(store))
    print(f"BBDevBox dashboard: http://{host}:{server.server_port}", flush=True)
    print(f"Data directory: {store.root}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
