"""HTTP-сервер стенда: панель, MCP (Streamable HTTP) и чат с локальной нейросетью."""
import json
import os
import queue
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .agent import LLMError

STATIC = os.path.join(os.path.dirname(__file__), "static")
TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        server_version = "tibbo-stand"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            if app.verbose:
                sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

        # ---------------------------------------------------------- утилиты
        def _send(self, code, body=b"", ctype="application/json; charset=utf-8", headers=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if body and self.command != "HEAD":
                self.wfile.write(body)

        def _body(self, limit=1_000_000):
            n = int(self.headers.get("Content-Length") or 0)
            if n > limit:
                raise ValueError("слишком большой запрос")
            return self.rfile.read(n) if n else b""

        def _json_body(self):
            raw = self._body()
            return json.loads(raw.decode("utf-8")) if raw else {}

        def _origin_ok(self):
            """Защита от DNS rebinding: чужой сайт в браузере посетителя не должен управлять стендом."""
            origin = self.headers.get("Origin")
            if not origin:
                return True
            host = urlparse(origin).netloc
            return host == self.headers.get("Host") or origin in app.allowed_origins

        def _token_ok(self):
            if not app.token:
                return True
            return _eq(self.headers.get("Authorization", ""), "Bearer " + app.token)

        def _sse_start(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

        def _sse(self, kind, data):
            self.wfile.write(("event: %s\ndata: %s\n\n" % (kind, json.dumps(data, ensure_ascii=False))).encode("utf-8"))
            self.wfile.flush()

        # ---------------------------------------------------------- GET
        def _via_tunnel(self):
            return bool(self.headers.get("Cf-Connecting-Ip") or self.headers.get("X-Forwarded-For"))

        def _tunnel_blocked(self, path):
            """Через интернет-туннель доступен только MCP; панель и чат - только в сети стенда."""
            if not self._via_tunnel() or app.panel_internet:
                return False
            if path == "/mcp" or path.startswith("/mcp/"):
                return False
            self._send(403, {"error": "панель доступна только в сети стенда"})
            return True

        def do_GET(self):
            path = urlparse(self.path).path
            if self._tunnel_blocked(path):
                return
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path == "/api/state":
                return self._send(200, dict(app.stand.snapshot, board=app.stand.board.kind,
                                            relays_meta=_meta(app.stand.relay_meta),
                                            inputs_meta=_meta(app.stand.input_meta),
                                            model=app.agent.model))
            if path == "/api/health":
                return self._send(200, {"llm": app.agent.health(), "board": app.stand.board.kind,
                                        "tools": len(app.registry.tools)})
            if path == "/api/rules":
                r = getattr(app.stand, "rules", None)
                return self._send(200, {"rules": r.list() if r else []})
            if path == "/api/log":
                return self._send(200, {"calls": list(app.stand.calls)[-50:], "events": list(app.stand.events)[-50:]})
            if path == "/api/svg":
                svg = app.registry.last_svg.get("svg")
                return self._send(200, svg, "image/svg+xml") if svg else self._send(404, {"error": "нет картинки"})
            if path == "/api/events":
                return self._events()
            if path == "/mcp" or path.startswith("/mcp/"):
                return self._send(405, {"error": "используйте POST"}, headers={"Allow": "POST"})
            return self._send(404, {"error": "не найдено"})

        def do_HEAD(self):
            self.do_GET()

        def _static(self, name):
            fp = os.path.normpath(os.path.join(STATIC, name))
            if not fp.startswith(STATIC) or not os.path.isfile(fp):
                return self._send(404, {"error": "не найдено"})
            with open(fp, "rb") as f:
                return self._send(200, f.read(), TYPES.get(os.path.splitext(fp)[1], "application/octet-stream"))

        def _events(self):
            q = app.stand.subscribe()
            try:
                self._sse_start()
                self._sse("state", app.stand.snapshot)
                last = time.time()
                while True:
                    try:
                        msg = q.get(timeout=15)
                        self._sse(msg["type"], msg["data"])
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    if time.time() - last > 3600:
                        break
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                app.stand.unsubscribe(q)

        # ---------------------------------------------------------- POST
        def do_POST(self):
            path = urlparse(self.path).path
            if self._tunnel_blocked(path):
                return
            if not self._origin_ok():
                return self._send(403, {"error": "чужой Origin"})
            try:
                if path == "/mcp" or path.startswith("/mcp/"):
                    return self._mcp(path)
                if path == "/api/chat":
                    return self._chat()
                if path == "/api/sim":
                    b = self._json_body()
                    app.stand.board.sim_set(b.get("what"), b.get("value"))
                    app.stand.poll_once(slow=True)
                    return self._send(200, {"ok": True})
                if path == "/api/relay":
                    b = self._json_body()
                    msg = app.stand.switch_relay(b.get("name"), bool(b.get("on")), b.get("duration_s"))
                    return self._send(200, {"ok": True, "message": msg})
                if path == "/api/safety":
                    b = self._json_body()
                    if "read_only" in b:
                        app.stand.read_only = bool(b["read_only"])
                        if app.stand.read_only:
                            app.stand.all_relays_off("режим только чтение")
                        app.stand.event("safety", "Режим «только чтение» %s" % ("включён" if app.stand.read_only else "выключен"))
                    app.stand.poll_once(slow=False)
                    return self._send(200, {"ok": True, "read_only": app.stand.read_only})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:  # noqa
                return self._send(400, {"error": str(e)})
            return self._send(404, {"error": "не найдено"})

        def _mcp(self, path):
            # /mcp/<секрет> - для облачных клиентов, которые умеют только адрес без заголовков
            secret = path[len("/mcp/"):] if path.startswith("/mcp/") else None
            if secret is not None:
                if not app.mcp_secret or not _eq(secret, app.mcp_secret):
                    return self._send(404, {"error": "не найдено"})
            elif not self._token_ok():
                return self._send(401, {"error": "нужен токен"}, headers={"WWW-Authenticate": "Bearer"})
            via_tunnel = secret is not None or self._via_tunnel()
            allow = app.remote_write if via_tunnel else app.lan_write
            raw = self._body()
            out = app.mcp.handle_raw(raw, source="mcp-internet" if via_tunnel else "mcp-lan", allow_write=allow)
            if out is None:
                return self._send(202, b"", "text/plain")
            return self._send(200, out, "application/json")

        def _chat(self):
            b = self._json_body()
            hist = [m for m in (b.get("history") or []) if m.get("role") in ("user", "assistant")
                    and isinstance(m.get("content"), str)][-12:]
            if not hist or hist[-1]["role"] != "user":
                return self._send(400, {"error": "нужно сообщение пользователя"})
            if not app.chat_lock.acquire(blocking=False):
                return self._send(409, {"error": "нейросеть ещё отвечает на прошлый вопрос"})
            q = queue.Queue()

            def emit(kind, data):
                q.put((kind, data))
                app.stand.publish("chat", {"kind": kind, "data": data})

            def run():
                try:
                    app.stand.publish("chat", {"kind": "user", "data": {"text": hist[-1]["content"]}})
                    app.agent.chat(hist, emit)
                except LLMError as e:
                    emit("error", {"error": str(e)})
                except Exception as e:  # noqa
                    emit("error", {"error": "сбой: %s" % e})
                finally:
                    q.put(None)
                    app.chat_lock.release()

            threading.Thread(target=run, daemon=True).start()
            try:
                self._sse_start()
                while True:
                    item = q.get()
                    if item is None:
                        break
                    self._sse(item[0], item[1])
                self._sse("done", {})
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def do_OPTIONS(self):
            self._send(204, b"", "text/plain", {"Allow": "GET, POST, OPTIONS"})

        def do_DELETE(self):
            self._send(405, {"error": "сессии не используются"})

    return H


def _eq(a, b):
    import hmac
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


def _meta(d):
    return [{"name": k, "title": v.get("title", k)} for k, v in d.items()]


class App:
    def __init__(self, stand, registry, mcp_server, agent, cfg, verbose=False):
        self.stand, self.registry, self.mcp, self.agent = stand, registry, mcp_server, agent
        self.token = cfg.get("token") or ""
        m = cfg.get("mcp", {})
        self.mcp_secret = m.get("secret_path") or ""
        self.lan_write = bool(m.get("lan_write", True))        # клиенты в сети стенда
        self.remote_write = bool(m.get("internet_write", False))  # клиенты через туннель: по умолчанию только чтение
        self.panel_internet = bool(m.get("panel_internet", False))
        self.allowed_origins = set(cfg.get("allowed_origins", []))
        self.chat_lock = threading.Lock()
        self.verbose = verbose

    def serve(self, host, port):
        httpd = ThreadingHTTPServer((host, port), make_handler(self))
        httpd.daemon_threads = True
        return httpd
