"""Правила автоматики: нейросеть их пишет, плата выполняет сама.

«Если дверь открыта дольше 10 секунд - включи лампу на минуту и зажги все светодиоды».
Нейросеть превращает фразу в правило через create_rule, а дальше плата проверяет условие
при каждом опросе датчиков. Нейросеть и интернет для этого уже не нужны, а все действия
проходят те же защиты, что и ручные (таймеры реле, аварийная кнопка, «только чтение»).
"""
import json
import math
import os
import threading
import time

SIGNALS = {
    "temperature_c": "температура, °C (#30)",
    "humidity_pct": "влажность, % (#30)",
    "light_lux": "освещённость, примерно лк (#28)",
    "shock_g": "встряска сейчас, g (#36)",
    "estop": "аварийная кнопка нажата (true/false)",
}
OPS = (">", "<", ">=", "<=", "==", "!=")
MAX_RULES = 20


class RuleError(ValueError):
    pass


def signal_value(snap, sig):
    if sig == "temperature_c":
        return (snap.get("climate") or {}).get("temperature_c")
    if sig == "humidity_pct":
        return (snap.get("climate") or {}).get("humidity_pct")
    if sig == "light_lux":
        raw = (snap.get("light") or {}).get("raw")
        return None if raw is None else raw / 1.2
    if sig == "shock_g":
        a = snap.get("accel")
        if not a:
            return None
        return abs(math.sqrt(a["x_mg"] ** 2 + a["y_mg"] ** 2 + a["z_mg"] ** 2) - 1000) / 1000.0
    if sig == "estop":
        return bool(snap.get("estop"))
    if sig.startswith("input:"):
        return (snap.get("inputs") or {}).get(sig[6:])
    return None


def compare(v, op, ref):
    if v is None:
        return False
    if isinstance(ref, bool) or isinstance(v, bool):
        v, ref = bool(v), bool(ref)
    try:
        return {">": v > ref, "<": v < ref, ">=": v >= ref, "<=": v <= ref, "==": v == ref, "!=": v != ref}[op]
    except TypeError:
        return False


class Rules:
    def __init__(self, stand, path=None):
        self.stand = stand
        self.path = path
        self.lock = threading.Lock()
        self.rules = []
        self.state = {}  # id -> {"since": t, "fired": bool, "last": t}
        self.next_id = 1
        self._load()

    # ---------------------------------------------------------------- хранение
    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                self.rules = json.load(f).get("rules", [])
            self.next_id = max([r["id"] for r in self.rules] + [0]) + 1
        except (OSError, ValueError, KeyError):
            self.rules = []

    def _save(self):
        if not self.path:
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"rules": self.rules}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ---------------------------------------------------------------- проверка правила
    def validate(self, name, when, then, cooldown_s):
        st = self.stand
        if not isinstance(when, dict):
            raise RuleError("when - объект {signal, op, value, for_s}")
        sig = when.get("signal")
        inputs = list(st.input_meta)
        if sig not in SIGNALS and not (isinstance(sig, str) and sig.startswith("input:") and sig[6:] in inputs):
            raise RuleError("неизвестный signal «%s». Есть: %s" % (sig, ", ".join(list(SIGNALS) + ["input:" + i for i in inputs])))
        op = when.get("op", "==")
        if op not in OPS:
            raise RuleError("op - одно из %s" % " ".join(OPS))
        if "value" not in when:
            raise RuleError("нужно value")
        for_s = float(when.get("for_s", 0))
        if not 0 <= for_s <= 86400:
            raise RuleError("for_s от 0 до 86400")
        if isinstance(then, dict):
            then = [then]
        if not then or len(then) > 5:
            raise RuleError("then - от 1 до 5 действий")
        for a in then:
            do = a.get("do")
            if do == "relay":
                if a.get("name") not in st.relay_meta:
                    raise RuleError("нет реле «%s». Есть: %s" % (a.get("name"), ", ".join(st.relay_meta)))
                if a.get("on", True) and not a.get("duration_s"):
                    raise RuleError("для включения реле в правиле нужен duration_s")
            elif do == "leds":
                if a.get("level") is None and a.get("pattern") is None:
                    raise RuleError("для leds нужен level или pattern")
            elif do == "event":
                if not a.get("text"):
                    raise RuleError("для event нужен text")
            else:
                raise RuleError("действие do - relay, leds или event")
        cd = float(cooldown_s if cooldown_s is not None else 30)
        if not 0 <= cd <= 86400:
            raise RuleError("cooldown_s от 0 до 86400")
        return {"name": str(name or "правило")[:80], "when": {"signal": sig, "op": op, "value": when["value"], "for_s": for_s},
                "then": then, "cooldown_s": cd, "enabled": True}

    # ---------------------------------------------------------------- API для инструментов
    def create(self, name, when, then, cooldown_s=None):
        r = self.validate(name, when, then, cooldown_s)
        with self.lock:
            if len(self.rules) >= MAX_RULES:
                raise RuleError("не больше %d правил - удалите лишние" % MAX_RULES)
            r["id"] = self.next_id
            r["created"] = int(time.time())
            self.next_id += 1
            self.rules.append(r)
            self._save()
        self.stand.event("rule", "Новое правило №%d: %s" % (r["id"], r["name"]))
        self.stand.publish("rules", self.list())
        return r

    def delete(self, rule_id):
        with self.lock:
            before = len(self.rules)
            self.rules = [r for r in self.rules if r["id"] != int(rule_id)]
            if len(self.rules) == before:
                raise RuleError("нет правила №%s" % rule_id)
            self.state.pop(int(rule_id), None)
            self._save()
        self.stand.event("rule", "Правило №%s удалено" % rule_id)
        self.stand.publish("rules", self.list())

    def list(self):
        with self.lock:
            out = []
            for r in self.rules:
                s = self.state.get(r["id"], {})
                out.append(dict(r, fired_count=s.get("count", 0), last_fired_ago_s=(
                    int(time.time() - s["last"]) if s.get("last") else None)))
            return out

    # ---------------------------------------------------------------- исполнение
    def evaluate(self, snap, now=None):
        now = now or time.time()
        fired = []
        with self.lock:
            rules = [r for r in self.rules if r.get("enabled", True)]
        for r in rules:
            w = r["when"]
            ok = compare(signal_value(snap, w["signal"]), w["op"], w["value"])
            s = self.state.setdefault(r["id"], {"since": None, "fired": False, "last": 0, "count": 0})
            if not ok:
                s["since"], s["fired"] = None, False
                continue
            if s["since"] is None:
                s["since"] = now
            if s["fired"] or now - s["since"] < w["for_s"] or now - s["last"] < r["cooldown_s"]:
                continue
            s["fired"], s["last"] = True, now
            s["count"] += 1
            fired.append(r)
            self._run(r)
        return fired

    def _run(self, r):
        st = self.stand
        done = []
        for a in r["then"]:
            try:
                if a["do"] == "relay":
                    done.append(st.switch_relay(a["name"], bool(a.get("on", True)), a.get("duration_s")))
                elif a["do"] == "leds":
                    lv, pat = a.get("level"), a.get("pattern")
                    states = [c == "1" for c in str(pat)] if pat is not None else [i < int(lv) for i in range(5)]
                    with st.lock:
                        st.board.set_leds(states)
                    done.append("светодиоды " + "".join("1" if x else "0" for x in states))
                elif a["do"] == "event":
                    done.append(str(a["text"])[:120])
            except Exception as e:  # защита отказала - это тоже событие, а не падение
                done.append("не выполнено: %s" % e)
        st.event("rule", "Сработало правило №%d «%s»: %s" % (r["id"], r["name"], "; ".join(done)), rule=r["id"])
