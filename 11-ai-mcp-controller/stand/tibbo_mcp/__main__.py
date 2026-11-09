"""Запуск:
  python3 -m tibbo_mcp --config config.json          панель + MCP по HTTP + чат с локальной нейросетью
  python3 -m tibbo_mcp --config config.json --stdio  MCP по stdio (для MCP-клиента на этой же машине или по SSH)
  python3 -m tibbo_mcp --sim                         эмулятор платы без файла настроек
  python3 -m tibbo_mcp --probe                       разведка на плате: шины I2C, датчики, pins.ini
"""
import argparse
import json
import os
import signal
import sys

from . import __version__
from .agent import Agent
from .hal import make_board, probe
from .mcp import Server, serve_stdio
from .stand import Stand
from .tools import build
from .web import App

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(os.path.dirname(HERE), "config.example.json")


def load(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    sd = cfg.get("skills_dir")
    if sd and not os.path.isabs(sd):
        cfg["skills_dir"] = os.path.normpath(os.path.join(base, sd))
    return cfg


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tibbo_mcp", description="MCP-сервер стенда Tibbo LTPP3(G2)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--sim", action="store_true", help="эмулятор платы вместо железа")
    ap.add_argument("--stdio", action="store_true", help="MCP по stdio вместо HTTP")
    ap.add_argument("--listen", default=None, help="адрес:порт, по умолчанию из config или 0.0.0.0:8080")
    ap.add_argument("--probe", action="store_true", help="найти датчики и линии на плате и выйти")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--version", action="version", version=__version__)
    a = ap.parse_args(argv)

    if a.probe:
        print(json.dumps(probe(), ensure_ascii=False, indent=1))
        return 0
    cfg = load(a.config or DEFAULT)
    if a.sim:
        cfg["board"] = "sim"
    board = make_board(cfg)
    stand = Stand(board, cfg)
    reg = build(stand, cfg)
    mcp = Server(reg, on_call=stand.log_call)
    stand.poll_once(slow=True)
    stand.start()
    if a.stdio:
        try:
            serve_stdio(mcp)
        finally:
            stand.all_relays_off("выход")
        return 0
    agent = Agent(reg, cfg, stand)
    app = App(stand, reg, mcp, agent, cfg, verbose=a.verbose)
    host, _, port = (a.listen or cfg.get("listen") or "0.0.0.0:8080").rpartition(":")
    httpd = app.serve(host or "0.0.0.0", int(port))

    def bye(*_):
        stand.all_relays_off("остановка сервера")
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, bye)
    print("Стенд Tibbo %s: плата %s, панель http://%s:%s/ , MCP http://%s:%s/mcp , нейросеть %s (%s)" % (
        __version__, board.kind, host or "0.0.0.0", port, host or "0.0.0.0", port, agent.model, agent.url),
        file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stand.all_relays_off("остановка сервера")
        stand.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
