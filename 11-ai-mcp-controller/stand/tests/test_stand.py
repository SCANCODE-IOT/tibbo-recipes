"""Автотесты: python3 -m unittest discover -s tests -v (из папки проекта)."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from tibbo_mcp import hal  # noqa: E402
from tibbo_mcp.agent import Agent  # noqa: E402
from tibbo_mcp.mcp import Server  # noqa: E402
from tibbo_mcp.stand import Stand  # noqa: E402
from tibbo_mcp.tools import build  # noqa: E402
from tibbo_mcp.web import App  # noqa: E402

SKILLS = os.environ.get("TIBBO_SKILLS_DIR", os.path.join(os.path.dirname(ROOT), "tibbo-ai-skills", "skills"))


def config(**kw):
    with open(os.path.join(ROOT, "config.example.json"), encoding="utf-8") as f:
        c = json.load(f)
    c["board"] = "sim"
    c["skills_dir"] = SKILLS
    c.update(kw)
    return c


def make(cfg=None):
    cfg = cfg or config()
    st = Stand(hal.make_board(cfg), cfg)
    reg = build(st, cfg)
    st.poll_once()
    return st, reg, Server(reg, on_call=st.log_call)


def rpc(srv, method, params=None, mid=1):
    return json.loads(srv.handle_raw(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})))


class Protocol(unittest.TestCase):
    def setUp(self):
        self.st, self.reg, self.srv = make()

    def test_initialize_and_versions(self):
        r = rpc(self.srv, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-03-26")
        r = rpc(self.srv, "initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")

    def test_notification_has_no_reply(self):
        self.assertIsNone(self.srv.handle_raw('{"jsonrpc":"2.0","method":"notifications/initialized"}'))

    def test_errors(self):
        self.assertEqual(json.loads(self.srv.handle_raw("{bad"))["error"]["code"], -32700)
        self.assertEqual(rpc(self.srv, "nope")["error"]["code"], -32601)
        self.assertEqual(rpc(self.srv, "tools/call", {"name": "nope"})["error"]["code"], -32602)

    def test_tools_have_schemas(self):
        tools = rpc(self.srv, "tools/list")["result"]["tools"]
        self.assertGreaterEqual(len(tools), 11)
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(t["description"])

    def test_bad_args_are_tool_errors(self):
        r = rpc(self.srv, "tools/call", {"name": "read_climate", "arguments": {"x": 1}})
        self.assertTrue(r["result"]["isError"])

    def test_batch(self):
        out = json.loads(self.srv.handle_raw(json.dumps([
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}])))
        self.assertEqual(len(out), 1)


class Safety(unittest.TestCase):
    def call(self, reg, tool, **args):
        return reg.call(tool, args)

    def test_relay_with_timer_and_auto_off(self):
        st, reg, _ = make()
        data, err = self.call(reg, "set_relay", name="lamp", on=True, duration_s=1)
        self.assertFalse(err, data)
        self.assertTrue(st.board.get_relay("lamp"))
        time.sleep(1.1)
        st.poll_once(slow=False)
        self.assertFalse(st.board.get_relay("lamp"))
        self.assertIn("по таймеру", st.events[-1]["text"])

    def test_limits(self):
        st, reg, _ = make()
        data, err = self.call(reg, "set_relay", name="lamp", on=True, duration_s=10000)
        self.assertTrue(err)
        data, err = self.call(reg, "set_relay", name="ghost", on=True)
        self.assertTrue(err)
        self.call(reg, "set_relay", name="lamp", on=True, duration_s=5)
        self.call(reg, "set_relay", name="lamp", on=False)
        data, err = self.call(reg, "set_relay", name="lamp", on=True, duration_s=5)
        self.assertTrue(err)
        self.assertIn("часто", data["error"])

    def test_read_only(self):
        cfg = config()
        cfg["safety"]["read_only"] = True
        st, reg, _ = make(cfg)
        data, err = self.call(reg, "set_relay", name="fan", on=True)
        self.assertTrue(err)
        self.assertIn("только чтение", data["error"])

    def test_estop_turns_everything_off(self):
        st, reg, _ = make()
        self.call(reg, "set_relay", name="fan", on=True, duration_s=30)
        st.board.sim_set("estop", 1)
        st.poll_once(slow=False)
        self.assertFalse(st.board.get_relay("fan"))
        data, err = self.call(reg, "set_relay", name="fan", on=True, duration_s=30)
        self.assertTrue(err)

    def test_lamp_is_seen_by_light_sensor(self):
        st, reg, _ = make()
        before = self.call(reg, "read_light")[0]["approx_lux"]
        self.call(reg, "set_relay", name="lamp", on=True, duration_s=5)
        after = self.call(reg, "read_light")[0]["approx_lux"]
        self.assertGreater(after, before + 200)

    def test_knock_becomes_event(self):
        st, reg, _ = make()
        st.board.sim_set("knock", 3)
        st.poll_once(slow=False)
        m = self.call(reg, "read_motion")[0]
        self.assertIsNotNone(m["last_shock"])
        self.assertTrue(any(e["kind"] == "shock" for e in st.events))

    def test_inputs_and_leds(self):
        st, reg, _ = make()
        st.board.sim_set("door", 1)
        st.poll_once(slow=False)
        st.board.sim_set("door", 0)
        st.poll_once(slow=False)
        d = self.call(reg, "read_inputs")[0]
        door = [i for i in d["inputs"] if i["name"] == "door"][0]
        self.assertEqual(door["activations"], 1)
        self.assertEqual(self.call(reg, "set_leds", level=3)[0]["leds"], "11100")
        self.assertTrue(self.call(reg, "set_leds", pattern="12345")[1])


@unittest.skipUnless(os.path.isdir(SKILLS), "нет папки скиллов (TIBBO_SKILLS_DIR)")
class SkillChecks(unittest.TestCase):
    def test_tps_and_lint(self):
        st, reg, _ = make()
        d, err = reg.call("check_tps_config", {"board_name": "TPP3W(G2)", "slots": {"S1": "10", "S2": "18"}, "vin": 24})
        self.assertFalse(err, d)
        self.assertFalse(d["ok"])
        self.assertTrue(any("9–18" in (f["text"] or "") for f in d["findings"]))
        self.assertTrue(reg.last_svg["svg"].startswith("<"))
        d, err = reg.call("lint_tibbo_code", {"code": "sub on_sys_init()\n sock.conect\nend sub\n"})
        self.assertEqual(d["errors"], 1)
        self.assertIn("sock.connect", d["findings"][0]["text"])
        d, err = reg.call("find_tibbit", {"query": "rs485"})
        self.assertIn("#05", d["matches"])


class RealBoardOnFakeFiles(unittest.TestCase):
    """Драйвер LTPP3(G2) на поддельных /sys/class/gpio, /proc/tpsleds и pins.ini."""

    def test_gpio_leds_pins(self):
        with tempfile.TemporaryDirectory() as d:
            gb, ld = os.path.join(d, "gpio"), os.path.join(d, "tpsleds")
            os.makedirs(ld)
            for n in (8, 9, 40, 41, 42):
                os.makedirs(os.path.join(gb, "gpio%d" % n))
                for f, v in (("direction", "in"), ("value", "1")):
                    with open(os.path.join(gb, "gpio%d" % n, f), "w") as fh:
                        fh.write(v)
            with open(os.path.join(gb, "export"), "w"):
                pass
            for i in range(5):
                open(os.path.join(ld, str(i)), "w").close()
            pini = os.path.join(d, "pins.ini")
            with open(pini, "w") as f:
                f.write("[CPU]\nS9A=8\nS9B=9\nS11A=40\nS11B=41\nS11C=42\n")
            cfg = config(board="ltpp3g2")
            cfg["hardware"]["pins_ini"] = pini
            b = hal.Ltpp3Board(cfg["hardware"], gpio_base=gb, leds_dir=ld)
            # выход с active=high: при старте выключено (low)
            with open(os.path.join(gb, "gpio8", "direction")) as f:
                self.assertEqual(f.read(), "low")
            b.set_relay("lamp", True)
            with open(os.path.join(gb, "gpio8", "value")) as f:
                self.assertEqual(f.read(), "1")
            # вход active=low: value=1 -> не нажат
            self.assertFalse(b.read_input("button"))
            with open(os.path.join(gb, "gpio40", "value"), "w") as f:
                f.write("0")
            self.assertTrue(b.read_input("button"))
            b.set_leds([True, False, True, False, True])
            with open(os.path.join(ld, "2")) as f:
                self.assertEqual(f.read(), "1")
            with self.assertRaises(hal.BoardError):
                b.read_climate()  # шины /dev/i2c-1 тут нет - понятная ошибка, а не падение


class AgentAndWeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import mock_ollama
        cls.mock = ThreadingHTTPServer(("127.0.0.1", 0), mock_ollama.H)
        cls.mock.model = "qwen3:14b"
        threading.Thread(target=cls.mock.serve_forever, daemon=True).start()
        cfg = config()
        cfg["llm"]["url"] = "http://127.0.0.1:%d" % cls.mock.server_address[1]
        cls.st, cls.reg, cls.srv = make(cfg)
        cls.agent = Agent(cls.reg, cfg, cls.st)
        cls.app = App(cls.st, cls.reg, cls.srv, cls.agent, cfg)
        cls.httpd = cls.app.serve("127.0.0.1", 0)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.mock.shutdown()

    def post(self, path, body, headers=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers=dict({"Content-Type": "application/json"}, **(headers or {})))
        return urllib.request.urlopen(req, timeout=30)

    def test_agent_loop(self):
        seen = []
        text = self.agent.chat([{"role": "user", "content": "Какая температура?"}], lambda k, d: seen.append(k))
        self.assertIn("°C", text)
        self.assertEqual(seen, ["backend", "call", "result", "text"])

    def test_chat_over_http(self):
        r = self.post("/api/chat", {"history": [{"role": "user", "content": "Включи лампу на 20 секунд"}]})
        body = r.read().decode()
        self.assertIn("set_relay", body)
        self.assertIn("event: done", body)

    def test_mcp_over_http_and_origin(self):
        r = self.post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(len(json.loads(r.read())["result"]["tools"]), len(self.reg.tools))
        r = self.post("/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(r.status, 202)
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"Origin": "http://evil.example"})
        self.assertEqual(e.exception.code, 403)

    def test_health_and_state(self):
        h = json.loads(urllib.request.urlopen(self.base + "/api/health").read())
        self.assertTrue(h["llm"]["ok"])
        s = json.loads(urllib.request.urlopen(self.base + "/api/state").read())
        self.assertIn("relays", s)


class OpenAIFormat(unittest.TestCase):
    """Тот же мост с сервером в формате OpenAI (LM Studio, llama.cpp, vLLM)."""

    def test_openai_tool_calls(self):
        from http.server import BaseHTTPRequestHandler

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                has_tool = any(m["role"] == "tool" for m in b["messages"])
                if has_tool:
                    assert b["messages"][-1]["tool_call_id"] == "c1"
                    msg = {"role": "assistant", "content": "Готово"}
                else:
                    msg = {"role": "assistant", "content": None, "tool_calls": [
                        {"id": "c1", "type": "function", "function": {"name": "read_climate", "arguments": "{}"}}]}
                out = json.dumps({"choices": [{"message": msg}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        cfg = config()
        cfg["llm"] = {"api": "openai", "url": "http://127.0.0.1:%d" % srv.server_address[1], "model": "local"}
        st, reg, _ = make(cfg)
        self.assertEqual(Agent(reg, cfg, st).chat([{"role": "user", "content": "?"}]), "Готово")
        srv.shutdown()


class RulesEngine(unittest.TestCase):
    def test_door_rule_fires_once_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = config(rules_file=os.path.join(d, "rules.json"))
            st, reg, _ = make(cfg)
            r, err = reg.call("create_rule", {"name": "дверь -> лампа",
                                              "when": {"signal": "input:door", "op": "==", "value": True, "for_s": 1},
                                              "then": [{"do": "relay", "name": "lamp", "on": True, "duration_s": 30},
                                                       {"do": "leds", "level": 5}]})
            self.assertFalse(err, r)
            st.board.sim_set("door", 1)
            t = time.time()
            self.assertEqual(st.rules.evaluate(st.poll_once(slow=False), now=t), [])      # ещё рано
            self.assertEqual(len(st.rules.evaluate(st.snapshot, now=t + 1.5)), 1)        # прошло for_s
            self.assertTrue(st.board.get_relay("lamp"))
            self.assertEqual(st.board.get_leds(), [True] * 5)
            self.assertEqual(st.rules.evaluate(st.snapshot, now=t + 3), [])              # не повторяется
            # правило пережило перезапуск
            st2, reg2, _ = make(cfg)
            self.assertEqual(len(reg2.call("list_rules", {})[0]["rules"]), 1)

    def test_rule_validation_and_safety(self):
        cfg = config()
        cfg["safety"]["read_only"] = True
        st, reg, _ = make(cfg)
        bad = [{"signal": "nope", "op": "==", "value": 1},
               {"signal": "temperature_c", "op": "~", "value": 1}]
        for w in bad:
            self.assertTrue(reg.call("create_rule", {"name": "x", "when": w, "then": [{"do": "event", "text": "x"}]})[1])
        self.assertTrue(reg.call("create_rule", {"name": "x", "when": {"signal": "temperature_c", "op": ">", "value": 1},
                                                 "then": [{"do": "relay", "name": "lamp", "on": True}]})[1])  # без таймера
        r, err = reg.call("create_rule", {"name": "жарко", "when": {"signal": "temperature_c", "op": ">", "value": 0},
                                          "then": [{"do": "relay", "name": "fan", "on": True, "duration_s": 10}]})
        self.assertFalse(err)
        st.rules.evaluate(st.poll_once())
        self.assertFalse(st.board.get_relay("fan"))  # «только чтение» сильнее правила
        self.assertIn("не выполнено", st.events[-1]["text"])


class Fleet(unittest.TestCase):
    def test_hub_sees_two_boards(self):
        servers = []
        for i in range(2):
            st, reg, srv = make()
            app = App(st, reg, srv, Agent(reg, config(), st), config())
            h = app.serve("127.0.0.1", 0)
            threading.Thread(target=h.serve_forever, daemon=True).start()
            servers.append(h)
        cfg = config(fleet=[{"name": "a", "title": "Шоурум", "url": "http://127.0.0.1:%d/mcp" % servers[0].server_address[1]},
                            {"name": "b", "title": "Котельная", "url": "http://127.0.0.1:%d/mcp" % servers[1].server_address[1]},
                            {"name": "dead", "url": "http://127.0.0.1:9/mcp", "timeout_s": 1}])
        st, reg, _ = make(cfg)
        d, err = reg.call("fleet_status", {})
        self.assertEqual([b["online"] for b in d["boards"]], [True, True, False])
        d, err = reg.call("fleet_call", {"board": "b", "tool": "read_climate"})
        self.assertFalse(err, d)
        self.assertIn("temperature_c", d["result"])
        d, err = reg.call("fleet_call", {"board": "a", "tool": "set_relay", "arguments": {"name": "lamp", "on": True}})
        self.assertTrue(err)  # fleet_write=false
        for h in servers:
            h.shutdown()


class Cloud(unittest.TestCase):
    def serve(self, handler):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        srv.model = "qwen3:14b"
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return "http://127.0.0.1:%d" % srv.server_address[1]

    def test_anthropic_format(self):
        from http.server import BaseHTTPRequestHandler
        seen = {}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen["key"] = self.headers.get("x-api-key")
                seen["path"] = self.path
                last = b["messages"][-1]
                if last["role"] == "user" and isinstance(last["content"], list):
                    assert last["content"][0]["type"] == "tool_result"
                    out = {"content": [{"type": "text", "text": "Тепло"}]}
                else:
                    assert b["tools"][0]["input_schema"]["type"] == "object"
                    out = {"content": [{"type": "tool_use", "id": "t1", "name": "read_climate", "input": {}}]}
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        url = self.serve(H)
        os.environ["TEST_ANTHROPIC_KEY"] = "k-123"
        cfg = config(llm={"api": "anthropic", "url": url, "api_key_env": "TEST_ANTHROPIC_KEY", "model": "claude-x"})
        st, reg, _ = make(cfg)
        self.assertEqual(Agent(reg, cfg, st).chat([{"role": "user", "content": "?"}]), "Тепло")
        self.assertEqual(seen, {"key": "k-123", "path": "/v1/messages"})

    def test_fallback_to_local_when_internet_is_gone(self):
        import mock_ollama
        local = self.serve(mock_ollama.H)
        cfg = config(llm_chain=[{"name": "cloud", "api": "openai", "url": "http://127.0.0.1:9/v1", "model": "gpt", "timeout_s": 2},
                                {"name": "local", "api": "ollama", "url": local, "model": "qwen3:14b"}])
        st, reg, _ = make(cfg)
        ag = Agent(reg, cfg, st)
        seen = []
        text = ag.chat([{"role": "user", "content": "Какая температура?"}], lambda k, d: seen.append((k, d)))
        self.assertIn("°C", text)
        self.assertEqual([d["name"] for k, d in seen if k == "backend"], ["cloud", "local"])


class InternetAccess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = config(mcp={"secret_path": "s3cret-path", "internet_write": False})
        cls.st, cls.reg, cls.srv = make(cfg)
        cls.app = App(cls.st, cls.reg, cls.srv, Agent(cls.reg, cfg, cls.st), cfg)
        cls.h = cls.app.serve("127.0.0.1", 0)
        threading.Thread(target=cls.h.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.h.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.h.shutdown()

    def req(self, path, body=None, headers=None):
        r = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                   headers=dict({"Content-Type": "application/json"}, **(headers or {})))
        try:
            with urllib.request.urlopen(r, timeout=10) as x:
                return x.status, x.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_secret_path_is_read_only(self):
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "read_climate"}}
        code, body = self.req("/mcp/s3cret-path", call)
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(body)["result"]["isError"])
        call["params"] = {"name": "set_relay", "arguments": {"name": "lamp", "on": True}}
        code, body = self.req("/mcp/s3cret-path", call)
        self.assertTrue(json.loads(body)["result"]["isError"])
        self.assertEqual(self.req("/mcp/wrong", call)[0], 404)

    def test_panel_hidden_from_tunnel(self):
        self.assertEqual(self.req("/", headers={"Cf-Connecting-Ip": "1.2.3.4"})[0], 403)
        self.assertEqual(self.req("/api/chat", {"history": []}, {"X-Forwarded-For": "1.2.3.4"})[0], 403)
        self.assertEqual(self.req("/")[0], 200)


if __name__ == "__main__":
    unittest.main()
