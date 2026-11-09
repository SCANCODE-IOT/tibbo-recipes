"""Ядро протокола MCP (JSON-RPC 2.0) без внешних библиотек.

Поддерживает initialize, ping, tools/list, tools/call. Транспорт - снаружи:
stdio (построчный JSON) и Streamable HTTP (см. web.py).
"""
import json
import sys
import traceback

from . import __version__

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "tibbo-stand", "title": "Стенд Tibbo LTPP3(G2)", "version": __version__}

INSTRUCTIONS = (
    "Сервер работает на Linux-контроллере Tibbo LTPP3(G2) с Tibbit-модулями. "
    "Значения датчиков бери только из инструментов, не придумывай. "
    "Реле включай только по просьбе человека. Для проверки платы TPS и кода Tibbo BASIC "
    "используй check_tps_config и lint_tibbo_code."
)


class ToolError(Exception):
    """Ошибка, которую стоит показать модели как результат инструмента (isError=true)."""


class Registry:
    def __init__(self):
        self.tools = {}

    def add(self, name, description, schema, func, title=None, read_only=True):
        self.tools[name] = {
            "def": {
                "name": name,
                "title": title or name,
                "description": description,
                "inputSchema": schema,
                "annotations": {"readOnlyHint": read_only, "openWorldHint": False},
            },
            "func": func,
        }

    def list(self):
        return [t["def"] for t in self.tools.values()]

    def call(self, name, args, allow_write=True):
        """Возвращает (структура, is_error). Используется и MCP, и мостом к нейросети."""
        if name not in self.tools:
            return {"error": "нет такого инструмента: %s" % name}, True
        if not allow_write and not self.tools[name]["def"]["annotations"]["readOnlyHint"]:
            return {"error": "этому клиенту разрешено только чтение: %s недоступен" % name}, True
        try:
            return self.tools[name]["func"](**(args or {})), False
        except ToolError as e:
            return {"error": str(e)}, True
        except TypeError as e:
            return {"error": "неверные аргументы: %s" % e}, True
        except Exception as e:  # ошибка железа не должна ронять сервер
            traceback.print_exc(file=sys.stderr)
            return {"error": "сбой инструмента: %s" % e}, True


def tool_result(data, is_error):
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    res = {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}
    if isinstance(data, dict) and not is_error:
        res["structuredContent"] = data
    return res


class Server:
    def __init__(self, registry, on_call=None):
        self.reg = registry
        self.on_call = on_call  # колбэк для журнала вызовов на панели

    def handle(self, msg, source="mcp", allow_write=True):
        """Один JSON-RPC объект -> ответ (dict) или None для уведомлений."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _err(None, -32600, "Invalid Request")
        mid = msg.get("id")
        method = msg.get("method")
        is_note = "id" not in msg
        if not isinstance(method, str):
            return None if is_note else _err(mid, -32600, "Invalid Request")
        params = msg.get("params") or {}
        try:
            if method == "initialize":
                want = params.get("protocolVersion")
                ver = want if want in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
                result = {
                    "protocolVersion": ver,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER_INFO,
                    "instructions": INSTRUCTIONS,
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.reg.list()}
            elif method == "tools/call":
                name = params.get("name")
                if name not in self.reg.tools:
                    return _err(mid, -32602, "Unknown tool: %s" % name)
                data, is_error = self.reg.call(name, params.get("arguments") or {}, allow_write)
                if self.on_call:
                    self.on_call(source, name, params.get("arguments") or {}, data, is_error)
                result = tool_result(data, is_error)
            elif method.startswith("notifications/"):
                return None
            else:
                return None if is_note else _err(mid, -32601, "Method not found: %s" % method)
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            return None if is_note else _err(mid, -32603, str(e))
        return None if is_note else {"jsonrpc": "2.0", "id": mid, "result": result}

    def handle_raw(self, raw, source="mcp", allow_write=True):
        """Строка/байты JSON -> строка ответа или None."""
        try:
            msg = json.loads(raw)
        except ValueError:
            return json.dumps(_err(None, -32700, "Parse error"))
        if isinstance(msg, list):  # пакет (протокол 2025-03-26)
            out = [r for r in (self.handle(m, source, allow_write) for m in msg) if r is not None]
            return json.dumps(out, ensure_ascii=False) if out else None
        r = self.handle(msg, source, allow_write)
        return None if r is None else json.dumps(r, ensure_ascii=False)


def _err(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def serve_stdio(server):
    """MCP по stdio: одно JSON-сообщение на строку. Логи - только в stderr."""
    stdin = sys.stdin.buffer if hasattr(sys.stdin, "buffer") else sys.stdin
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        out = server.handle_raw(line, source="stdio")
        if out is not None:
            sys.stdout.write(out + "\n")
            sys.stdout.flush()
