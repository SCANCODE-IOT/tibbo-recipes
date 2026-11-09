"""Инструменты MCP стенда: датчики, реле, светодиоды и проверки из ИИ-скиллов Tibbo."""
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time

from .hal import LED_COUNT, BoardError
from .mcp import Registry, ToolError

OBJ = lambda props=None, req=None: {"type": "object", "properties": props or {}, "required": req or [],
                                     "additionalProperties": False}


def build(stand, cfg):
    reg = Registry()
    hw = cfg.get("hardware", {})
    skills = cfg.get("skills_dir") or ""
    fw = os.path.join(skills, "tibbo-firmware", "scripts") if skills else ""
    board = stand.board
    last_svg = {"svg": None}

    def hw_call(fn, *a):
        try:
            with stand.lock:
                return fn(*a)
        except BoardError as e:
            raise ToolError(str(e))

    # ------------------------------------------------------------------ обзор
    def stand_status():
        snap = stand.poll_once(slow=True)
        return {
            "board": "эмулятор LTPP3(G2)" if board.kind == "sim" else "Tibbo LTPP3(G2)",
            "sensors": [t for k, t in (("climate", "Tibbit #30 температура и влажность"),
                                       ("light", "Tibbit #28 освещённость"), ("accel", "Tibbit #36 акселерометр"))
                        if hw.get(k) or board.kind == "sim"],
            "relays": [{"name": n, "title": m.get("title", n), "on": snap["relays"].get(n),
                        "max_on_s": m.get("max_on_s", stand.max_on_s)} for n, m in stand.relay_meta.items()],
            "inputs": [{"name": n, "title": m.get("title", n), "active": snap["inputs"].get(n)}
                       for n, m in stand.input_meta.items()],
            "led_bar": LED_COUNT,
            "read_only": stand.read_only,
            "estop_pressed": stand.estop,
            "system": snap.get("system"),
            "problems": snap.get("errors") or None,
        }

    reg.add("stand_status", "Что подключено к стенду и в каком всё состоянии: датчики, реле, входы, "
            "режим «только чтение», аварийная кнопка, температура процессора. Вызывай первым, если не знаешь стенд.",
            OBJ(), stand_status, title="Состояние стенда")

    # ------------------------------------------------------------------ датчики
    def read_climate():
        v = hw_call(board.read_climate)
        v["sensor"] = "Tibbit #30 (HIH6130)"
        return v

    reg.add("read_climate", "Температура (°C) и относительная влажность (%) с Tibbit #30.",
            OBJ(), read_climate, title="Температура и влажность")

    def read_light():
        v = hw_call(board.read_light)
        v["approx_lux"] = int(round(v["raw"] / 1.2))
        v["sensor"] = "Tibbit #28 (BH1721)"
        v["note"] = "approx_lux - оценка по даташиту BH1721, датчик не откалиброван"
        return v

    reg.add("read_light", "Освещённость с Tibbit #28: сырое значение и примерные люксы.",
            OBJ(), read_light, title="Освещённость")

    def read_motion():
        a = hw_call(board.read_accel)
        g = math.sqrt(a["x_mg"] ** 2 + a["y_mg"] ** 2 + a["z_mg"] ** 2) or 1
        tilt = math.degrees(math.acos(max(-1.0, min(1.0, a["z_mg"] / g))))
        peak, stand.peak_mg = stand.peak_mg, 0.0
        shock = stand.last_shock
        return {"x_mg": a["x_mg"], "y_mg": a["y_mg"], "z_mg": a["z_mg"], "tilt_deg": round(tilt, 1),
                "peak_since_last_read_g": round(peak / 1000.0, 2),
                "last_shock": None if not shock else {"ago_s": int(time.time() - shock["t"]),
                                                      "g": round(shock["mg"] / 1000.0, 2)},
                "sensor": "Tibbit #36 (ADXL312)"}

    reg.add("read_motion", "Акселерометр Tibbit #36: ускорение по осям (мг), наклон, сила последнего удара "
            "и пик с прошлого вызова. Подходит для вопросов «стучали ли по коробке», «как стоит плата».",
            OBJ(), read_motion, title="Движение и удары")

    def read_inputs():
        stand.poll_once(slow=False)
        out = []
        for n, m in stand.input_meta.items():
            out.append({"name": n, "title": m.get("title", n), "active": stand.input_state.get(n),
                        "state_text": (m.get("on_text", "активен") if stand.input_state.get(n)
                                       else m.get("off_text", "отпущен")),
                        "activations": stand.input_count.get(n, 0)})
        return {"inputs": out, "estop_pressed": stand.estop, "sensor": "Tibbit #54"}

    reg.add("read_inputs", "Входы с Tibbit #54 (кнопка, датчик двери шкафа): состояние и число срабатываний.",
            OBJ(), read_inputs, title="Кнопка и дверь")

    def recent_events(limit=10):
        limit = max(1, min(int(limit), 50))
        now = time.time()
        return {"events": [{"ago_s": int(now - e["t"]), "kind": e["kind"], "text": e["text"]}
                           for e in list(stand.events)[-limit:][::-1]]}

    reg.add("recent_events", "Последние события стенда: нажатия кнопки, дверь, удары, реле, аварийная кнопка.",
            OBJ({"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}}),
            recent_events, title="События")

    # ------------------------------------------------------------------ управление
    names = list(stand.relay_meta)
    relay_desc = "; ".join("%s - %s" % (n, m.get("title", n)) for n, m in stand.relay_meta.items())

    def set_relay(name, on, duration_s=None):
        try:
            return {"ok": True, "message": hw_call(stand.switch_relay, name, bool(on), duration_s)}
        except ValueError as e:
            raise ToolError(str(e))

    reg.add("set_relay", "Включить или выключить нагрузку через реле Tibbit #03. Реле: %s. "
            "Включение всегда с таймером (по умолчанию максимум); включай только по просьбе человека." % relay_desc,
            OBJ({"name": {"type": "string", "enum": names or ["none"]},
                 "on": {"type": "boolean"},
                 "duration_s": {"type": "number", "minimum": 1, "description": "через сколько секунд выключить"}},
                ["name", "on"]),
            set_relay, title="Реле", read_only=False)

    def set_leds(level=None, pattern=None):
        if pattern is not None:
            p = str(pattern).strip()
            if not re.fullmatch(r"[01]{%d}" % LED_COUNT, p):
                raise ToolError("pattern - %d символов 0/1, например 10101" % LED_COUNT)
            states = [c == "1" for c in p]
        elif level is not None:
            lv = int(level)
            if not 0 <= lv <= LED_COUNT:
                raise ToolError("level от 0 до %d" % LED_COUNT)
            states = [i < lv for i in range(LED_COUNT)]
        else:
            raise ToolError("нужен level или pattern")
        hw_call(board.set_leds, states)
        stand.poll_once(slow=False)
        return {"ok": True, "leds": "".join("1" if s else "0" for s in states)}

    reg.add("set_leds", "Шкала из %d синих светодиодов на плате: level - сколько горит слева (0-%d), "
            "или pattern - строка из 0/1, например 10101. Удобно показывать уровень (температуру, свет)." % (LED_COUNT, LED_COUNT),
            OBJ({"level": {"type": "integer", "minimum": 0, "maximum": LED_COUNT},
                 "pattern": {"type": "string", "pattern": "^[01]{%d}$" % LED_COUNT}}),
            set_leds, title="Светодиоды", read_only=False)

    # ------------------------------------------------------------------ проверки из скиллов
    def run_script(script, args, timeout=30):
        path = os.path.join(fw, script)
        if not fw or not os.path.exists(path):
            raise ToolError("скрипты ИИ-скиллов не найдены: укажите skills_dir в config.json")
        try:
            p = subprocess.run([sys.executable, "-I", path] + args, capture_output=True, text=True,
                               timeout=timeout, encoding="utf-8")
        except subprocess.TimeoutExpired:
            raise ToolError("проверка не уложилась в %d с" % timeout)
        return p

    def check_tps_config(board_name, slots, vin=12, poe=False, ambient_c=40):
        if not isinstance(slots, dict) or not slots:
            raise ToolError("slots - словарь {\"S1\": \"05\", ...}")
        conf = {"board": board_name, "slots": {k.upper(): str(v).lstrip("#") for k, v in slots.items()},
                "power": {"vin": vin}, "ambient_c": ambient_c, "poe_jumpers": "1-2" if poe else "2-3"}
        with tempfile.TemporaryDirectory() as d:
            cp, svg = os.path.join(d, "c.json"), os.path.join(d, "board.svg")
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(conf, f, ensure_ascii=False)
            p = run_script("tps_check.py", ["check", cp, "--json", "--svg", svg])
            if p.returncode == 2:
                raise ToolError((p.stdout + p.stderr).strip()[-800:] or "неверная конфигурация")
            try:
                res = json.loads(p.stdout)
            except ValueError:
                raise ToolError("tps_check: неожиданный ответ")
            if os.path.exists(svg):
                with open(svg, encoding="utf-8") as f:
                    last_svg["svg"] = f.read()
        r = res.get("result", res)
        out = {"board": r.get("board"), "ok": p.returncode == 0,
               "findings": [{"level": x.get("level"), "where": x.get("where"),
                             "text": x.get("msg") or x.get("message") or x.get("text")}
                            for x in (res.get("findings") or [])],
               "power_5v_ma": (r.get("power") or {}).get("total_5v_ma"),
               "capacity_5v_ma": (r.get("power") or {}).get("capacity_5v_ma"),
               "picture": "картинка платы показана на экране стенда" if last_svg["svg"] else None}
        if not out["findings"] and p.returncode == 1:
            out["raw"] = p.stdout[-1500:]
        stand.publish("svg", {"svg": last_svg["svg"], "title": "%s - проверка" % board_name})
        return out

    boards_enum = ["TPP2W", "TPP2W(G2)", "TPP2W(G3)", "TPP3W", "TPP3W(G2)", "TPP3W(G3)", "TPP2N", "TPP3N"]
    reg.add("check_tps_config", "Проверка конфигурации платы TPS (скрипт tps_check из ИИ-скиллов Tibbo): "
            "раскладка Tibbit по слотам, линии UART/INT, разъёмы, входное напряжение и бюджет питания +5 В. "
            "Рисует плату на экране стенда. Пример slots: {\"S1\": \"10\", \"S2\": \"18\", \"S3\": \"05\"}.",
            OBJ({"board_name": {"type": "string", "enum": boards_enum},
                 "slots": {"type": "object", "additionalProperties": {"type": "string"},
                           "description": "слот -> номер Tibbit, широкий модуль указывается один раз в первом слоте"},
                 "vin": {"type": "number", "description": "напряжение питания, В", "default": 12},
                 "poe": {"type": "boolean", "default": False},
                 "ambient_c": {"type": "number", "default": 40}},
                ["board_name", "slots"]),
            check_tps_config, title="Проверка платы TPS")

    def find_tibbit(query):
        p = run_script("tps_check.py", ["find", str(query)[:120]])
        txt = (p.stdout or p.stderr).strip()
        return {"matches": txt[:2500] or "ничего не найдено"}

    reg.add("find_tibbit", "Поиск по каталогу из 84 Tibbit: «rs485 modbus», «реле», «температура».",
            OBJ({"query": {"type": "string"}}, ["query"]), find_tibbit, title="Поиск Tibbit")

    def lint_tibbo_code(code, platform=None, language="basic"):
        if not code or len(code) > 200000:
            raise ToolError("пустой или слишком большой код")
        ext = ".tc" if language == "c" else ".tbs"
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "code" + ext)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(code)
            args = [fp, "--json"] + (["--platform", platform] if platform else [])
            p = run_script("tibbo_lint.py", args)
        try:
            res = json.loads(p.stdout)
        except ValueError:
            raise ToolError((p.stdout + p.stderr).strip()[-800:])
        return {"errors": res.get("errors", 0),
                "findings": [{"line": x.get("line"), "level": x.get("level"), "text": x.get("message")}
                             for x in res.get("findings", [])][:40]}

    reg.add("lint_tibbo_code", "Проверка кода на Tibbo BASIC или Tibbo C: выдуманные свойства и методы TiOS, "
            "неверные константы PL_*, объекты, которых нет на платформе. Подсказывает правильное имя.",
            OBJ({"code": {"type": "string"}, "platform": {"type": "string", "description": "например TPP3W(G2)"},
                 "language": {"type": "string", "enum": ["basic", "c"], "default": "basic"}}, ["code"]),
            lint_tibbo_code, title="Проверка кода Tibbo")

    # ------------------------------------------------------------------ правила автоматики
    from .rules import SIGNALS, RuleError, Rules
    rules = stand.rules = Rules(stand, cfg.get("rules_file"))
    sig_list = list(SIGNALS) + ["input:" + n for n in stand.input_meta]

    def create_rule(name, when, then, cooldown_s=None):
        try:
            r = rules.create(name, when, then, cooldown_s)
        except (RuleError, TypeError, ValueError) as e:
            raise ToolError(str(e))
        return {"ok": True, "rule": r, "note": "правило выполняет плата сама, нейросеть для этого не нужна"}

    reg.add("create_rule", "Создать правило автоматики, которое плата выполняет сама, без нейросети: «если <сигнал> "
            "<сравнение> <значение> дольше for_s секунд - выполнить действия». Сигналы: %s. Действия then: "
            "{\"do\": \"relay\", \"name\": ..., \"on\": true, \"duration_s\": ...}, {\"do\": \"leds\", \"level\": 0-5} "
            "или {\"do\": \"event\", \"text\": ...}. Пример: дверь открыта дольше 10 с -> лампа на 60 с: "
            "when={\"signal\": \"input:door\", \"op\": \"==\", \"value\": true, \"for_s\": 10}, "
            "then=[{\"do\": \"relay\", \"name\": \"lamp\", \"on\": true, \"duration_s\": 60}]." % ", ".join(sig_list),
            OBJ({"name": {"type": "string", "description": "коротко, по-человечески"},
                 "when": {"type": "object", "properties": {
                     "signal": {"type": "string", "enum": sig_list},
                     "op": {"type": "string", "enum": [">", "<", ">=", "<=", "==", "!="]},
                     "value": {"type": ["number", "boolean"]},
                     "for_s": {"type": "number", "minimum": 0}}, "required": ["signal", "op", "value"]},
                 "then": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 5},
                 "cooldown_s": {"type": "number", "minimum": 0, "default": 30}},
                ["name", "when", "then"]),
            create_rule, title="Создать правило", read_only=False)

    reg.add("list_rules", "Правила автоматики на плате: условия, действия, сколько раз сработали.",
            OBJ(), lambda: {"rules": rules.list()}, title="Правила")

    def delete_rule(rule_id):
        try:
            rules.delete(rule_id)
        except (RuleError, ValueError) as e:
            raise ToolError(str(e))
        return {"ok": True}

    reg.add("delete_rule", "Удалить правило автоматики по номеру.",
            OBJ({"rule_id": {"type": "integer"}}, ["rule_id"]), delete_rule, title="Удалить правило", read_only=False)

    # ------------------------------------------------------------------ флот контроллеров
    if cfg.get("fleet"):
        from .fleet import Fleet, FleetError
        fleet = Fleet(cfg)
        write_tools = {"set_relay", "set_leds", "create_rule", "delete_rule"}
        names_f = list(fleet.nodes)

        def fleet_status():
            return {"boards": fleet.status()}

        def fleet_call(board, tool, arguments=None):
            try:
                return fleet.call(board, tool, arguments, write_tools)
            except FleetError as e:
                raise ToolError(str(e))

        titles = "; ".join("%s - %s" % (k, v["title"]) for k, v in fleet.nodes.items())
        reg.add("fleet_status", "Сводка по всем площадкам флота контроллеров Tibbo (%s): кто на связи, датчики, "
                "реле, проблемы." % titles, OBJ(), fleet_status, title="Флот: сводка")
        reg.add("fleet_call", "Вызвать инструмент на другой площадке флота. tool - имя инструмента стенда "
                "(read_climate, read_inputs, set_relay ...), arguments - его аргументы. Площадки: %s." % titles,
                OBJ({"board": {"type": "string", "enum": names_f}, "tool": {"type": "string"},
                     "arguments": {"type": "object"}}, ["board", "tool"]),
                fleet_call, title="Флот: вызов", read_only=not fleet.allow_write)

    reg.last_svg = last_svg
    return reg
