"""Флот: один ИИ - много контроллеров Tibbo.

Каждый контроллер со своим tibbo-stand уже MCP-сервер. Узел-«диспетчер» (любая плата,
ноутбук или сервер в облаке) знает адреса остальных и даёт нейросети два инструмента:
fleet_status - сводка по всем площадкам, fleet_call - вызвать инструмент на нужной плате.
Так одна нейросеть видит шкафы в разных цехах, зданиях и городах.
"""
import json
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


class FleetError(Exception):
    pass


class MCPClient:
    """Минимальный клиент MCP Streamable HTTP (ответы application/json и text/event-stream)."""

    def __init__(self, url, token="", timeout=10):
        self.url, self.token, self.timeout = url, token, timeout
        self.session = None
        self.ready = False
        self.lock = threading.Lock()
        self.n = 0

    def _rpc(self, method, params=None, note=False):
        self.n += 1
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not note:
            msg["id"] = self.n
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "MCP-Protocol-Version": "2025-06-18"}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        if self.session:
            h["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, data=json.dumps(msg).encode("utf-8"), headers=h)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                self.session = r.headers.get("Mcp-Session-Id") or self.session
                body = r.read().decode("utf-8")
                ctype = r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raise FleetError("%s ответил %s" % (self.url, e.code))
        except (urllib.error.URLError, OSError) as e:
            raise FleetError("нет связи с %s: %s" % (self.url, getattr(e, "reason", e)))
        if note:
            return None
        if "text/event-stream" in ctype:
            data = [ln[5:].strip() for ln in body.splitlines() if ln.startswith("data:")]
            body = data[-1] if data else "{}"
        res = json.loads(body or "{}")
        if "error" in res:
            raise FleetError(res["error"].get("message", "ошибка MCP"))
        return res.get("result")

    def ensure(self):
        with self.lock:
            if not self.ready:
                self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                         "clientInfo": {"name": "tibbo-fleet", "version": "0.2"}})
                self._rpc("notifications/initialized", note=True)
                self.ready = True

    def call(self, tool, args=None):
        self.ensure()
        try:
            r = self._rpc("tools/call", {"name": tool, "arguments": args or {}})
        except FleetError:
            self.ready = False  # сервер мог перезапуститься - в следующий раз начнём заново
            raise
        txt = "".join(c.get("text", "") for c in (r or {}).get("content", []) if c.get("type") == "text")
        try:
            data = r.get("structuredContent") or json.loads(txt)
        except ValueError:
            data = {"text": txt}
        return data, bool((r or {}).get("isError"))

    def tools(self):
        self.ensure()
        return [t["name"] for t in (self._rpc("tools/list") or {}).get("tools", [])]


class Fleet:
    def __init__(self, cfg):
        self.nodes = {}
        for n in cfg.get("fleet", []):
            self.nodes[n["name"]] = {"title": n.get("title", n["name"]), "client": MCPClient(
                n["url"], n.get("token", ""), float(n.get("timeout_s", 10)))}
        self.allow_write = bool(cfg.get("fleet_write", False))

    def status(self):
        def one(item):
            name, n = item
            try:
                d, err = n["client"].call("stand_status")
                return {"name": name, "title": n["title"], "online": True, "status": d, "error": err or None}
            except FleetError as e:
                return {"name": name, "title": n["title"], "online": False, "error": str(e)}
        with ThreadPoolExecutor(max_workers=min(8, len(self.nodes) or 1)) as ex:
            return list(ex.map(one, self.nodes.items()))

    def call(self, board, tool, arguments=None, write_tools=()):
        if board not in self.nodes:
            raise FleetError("нет площадки «%s». Есть: %s" % (board, ", ".join(self.nodes)))
        if tool in write_tools and not self.allow_write:
            raise FleetError("управление удалёнными площадками выключено (fleet_write=false), доступно только чтение")
        data, err = self.nodes[board]["client"].call(tool, arguments or {})
        return {"board": board, "tool": tool, "result": data, "remote_error": err}
