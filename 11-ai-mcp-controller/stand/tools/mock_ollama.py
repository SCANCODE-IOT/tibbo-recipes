"""Заглушка Ollama для тестов и репетиций без видеокарты.

Понимает /api/tags и /api/chat с инструментами, как настоящая Ollama, но вместо
нейросети - простые правила по ключевым словам. Нужна, чтобы проверить панель,
мост и инструменты; качество ответов настоящей модели она не показывает.

  python3 tools/mock_ollama.py --port 11434
"""
import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def plan(text, results):
    """Список вызовов для вопроса. results - уже полученные ответы инструментов (по порядку)."""
    t = text.lower()
    if "плат" in t and re.search(r"s\d+", t):
        slots = {}
        for m in re.finditer(r"\b(s\d+)\b[^#]{0,30}#(\d+(?:_\d)?)", text, re.I):
            slots[m.group(1).upper()] = m.group(2)
        vin = re.search(r"(\d+)\s*в\b", t)
        board = re.search(r"(TPP[23][WN](?:\(G[23]\))?)", text, re.I)
        return [("check_tps_config", {"board_name": board.group(1).upper().replace("(G", "(G") if board else "TPP3W(G2)",
                                      "slots": slots, "vin": int(vin.group(1)) if vin else 12})]
    if t.startswith("если") or " если " in t:
        sig, val = ("input:door", True) if "двер" in t else (("input:button", True) if "кнопк" in t else ("temperature_c", 25))
        op = "==" if sig.startswith("input") else ">"
        m = re.search(r"дольше\s+(\d+)", t)
        dur = 60 if "минут" in t else 30
        return [("create_rule", {"name": text[:60], "when": {"signal": sig, "op": op, "value": val,
                                                               "for_s": int(m.group(1)) if m else 0},
                                 "then": [{"do": "relay", "name": "lamp", "on": True, "duration_s": dur},
                                          {"do": "leds", "level": 5}]})]
    if "код" in t:
        code = text.split(":", 1)[1] if ":" in text else text
        code = re.sub(r"\s+(?=(sock|end sub|sys|ser|io)\b)", "\n", code.strip())
        return [("lint_tibbo_code", {"code": code})]
    if "ламп" in t and "включ" in t:
        dur = re.search(r"(\d+)\s*(сек|с\b)", t)
        return [("read_light", {}), ("set_relay", {"name": "lamp", "on": True, "duration_s": int(dur.group(1)) if dur else 30}),
                ("read_light", {})]
    if "светодиод" in t:
        if not results:
            return [("read_light", {})]
        lux = results[0].get("approx_lux", 0)
        return [("read_light", {}), ("set_leds", {"level": max(0, min(5, int(round(lux / 160.0))))})]
    if "стуч" in t or "происход" in t or "событ" in t:
        return [("read_motion", {}), ("recent_events", {"limit": 8})]
    if "температ" in t or "влажн" in t or "жарко" in t:
        return [("read_climate", {})]
    return [("stand_status", {})]


def answer(text, calls, results):
    t = text.lower()
    r = dict(zip([c[0] for c in calls], results))
    if "create_rule" in r:
        x = r["create_rule"]
        if x.get("error"):
            return "Правило не создано: " + x["error"]
        return "Записал правило №%d. Теперь плата сама следит за этим - даже если меня выключить." % x["rule"]["id"]
    if "check_tps_config" in r:
        x = r["check_tps_config"]
        errs = [f["text"] for f in x.get("findings", []) if f.get("level") == "error"]
        return ("Проверил плату скриптом tps_check. " + ("Ошибок нет." if not errs else
                "Нашёл ошибки: " + " ".join(errs[:2])) + " Картинка платы - на экране.")
    if "lint_tibbo_code" in r:
        x = r["lint_tibbo_code"]
        if not x.get("errors"):
            return "Линтер ошибок в именах API не нашёл."
        return "Линтер нашёл ошибку: " + x["findings"][0]["text"]
    if "set_relay" in r:
        before, after = results[0].get("approx_lux"), results[-1].get("approx_lux")
        msg = r["set_relay"].get("message") or r["set_relay"].get("error")
        if r["set_relay"].get("error"):
            return "Не получилось включить лампу: " + msg
        return "Готово: %s. Свет вырос с %s до %s лк по датчику #28." % (msg, before, after)
    if "set_leds" in r:
        return "Сейчас около %s лк - зажёг %s из 5 светодиодов." % (results[0].get("approx_lux"), r["set_leds"].get("leds", "").count("1"))
    if "read_motion" in r:
        m, ev = r["read_motion"], r.get("recent_events", {}).get("events", [])
        s = "Последний удар был %s с назад, %s g." % (m["last_shock"]["ago_s"], m["last_shock"]["g"]) if m.get("last_shock") else "Ударов не было."
        return s + (" Ещё события: " + "; ".join(e["text"] for e in ev[:3]) if ev else "")
    if "read_climate" in r:
        x = r["read_climate"]
        return "В шкафу %s °C и %s %% влажности - по датчику Tibbit #30." % (x.get("temperature_c"), x.get("humidity_pct"))
    x = r.get("stand_status", {})
    return "Это стенд %s: %s. Спросите меня о температуре или попросите включить лампу." % (
        x.get("board"), ", ".join(x.get("sensors", [])))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/api/tags":
            return self._json({"models": [{"name": self.server.model}]})
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path != "/api/chat":
            return self._json({"error": "not found"}, 404)
        msgs = body.get("messages", [])
        idx = max(i for i, m in enumerate(msgs) if m["role"] == "user")
        user = msgs[idx]["content"]
        results = [json.loads(m["content"]) for m in msgs[idx + 1:] if m["role"] == "tool"]
        calls = plan(user, results)
        if len(results) < len(calls):
            name, args = calls[len(results)]
            msg = {"role": "assistant", "content": "",
                   "tool_calls": [{"function": {"name": name, "arguments": args}}]}
        else:
            msg = {"role": "assistant", "content": answer(user, calls, results)}
        self._json({"model": body.get("model"), "message": msg, "done": True})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=11434)
    ap.add_argument("--model", default="qwen3:14b")
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    srv.model = a.model
    print("заглушка Ollama на http://127.0.0.1:%d" % a.port)
    srv.serve_forever()


if __name__ == "__main__":
    main()
