"""Состояние стенда: опрос датчиков, события, защита реле, журнал вызовов ИИ."""
import collections
import math
import queue
import sys
import threading
import time

from .hal import BoardError


class Stand:
    def __init__(self, board, cfg):
        self.board = board
        self.cfg = cfg
        self.hw = cfg.get("hardware", {})
        s = cfg.get("safety", {})
        self.read_only = bool(s.get("read_only", False))
        self.max_on_s = float(s.get("relay_max_on_s", 600))
        self.min_interval_s = float(s.get("relay_min_interval_s", 2))
        self.max_switch_per_min = int(s.get("relay_max_switch_per_min", 20))
        self.shock_mg = float(s.get("shock_threshold_mg", 600))
        self.lock = threading.RLock()
        self.events = collections.deque(maxlen=200)
        self.calls = collections.deque(maxlen=200)
        self.snapshot = {}
        self.errors = {}
        self.relay_meta = {r["name"]: r for r in self.hw.get("relays", [])}
        self.input_meta = {i["name"]: i for i in self.hw.get("inputs", [])}
        self.relay_off_at = {}       # name -> время автоотключения
        self.relay_changed_at = {}
        self.switch_times = collections.deque(maxlen=200)
        self.input_state = {}
        self.input_count = {n: 0 for n in self.input_meta}
        self.estop = False
        self.peak_mg = 0.0
        self.last_shock = None
        self.subs = []
        self.rules = None
        self.started = time.time()
        self._stop = threading.Event()

    # ------------------------------------------------------------------ публикация на панель
    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self.lock:
            self.subs.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)

    def publish(self, kind, data):
        msg = {"type": kind, "data": data, "t": time.time()}
        with self.lock:
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def event(self, kind, text, **extra):
        ev = dict(extra, kind=kind, text=text, t=time.time())
        self.events.append(ev)
        self.publish("event", ev)

    def log_call(self, source, name, args, result, is_error):
        rec = {"source": source, "tool": name, "args": args, "result": result,
               "error": bool(is_error), "t": time.time()}
        self.calls.append(rec)
        self.publish("call", rec)

    # ------------------------------------------------------------------ опрос
    def start(self):
        threading.Thread(target=self._loop, name="poller", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _safe(self, key, fn):
        try:
            v = fn()
            self.errors.pop(key, None)
            return v
        except (BoardError, OSError, KeyError, ValueError) as e:
            if self.errors.get(key) != str(e):
                print("[%s] %s" % (key, e), file=sys.stderr)
            self.errors[key] = str(e)
            return None

    def poll_once(self, slow=True):
        now = time.time()
        with self.lock:
            snap = dict(self.snapshot)
            # аварийная кнопка
            if self.hw.get("estop") or self.board.kind == "sim":
                es = bool(self._safe("estop", self.board.read_estop))
                if es and not self.estop:
                    self.all_relays_off("аварийная кнопка")
                    self.event("estop", "Нажата аварийная кнопка - все реле выключены")
                elif not es and self.estop:
                    self.event("estop", "Аварийная кнопка отпущена")
                self.estop = es
            # автоотключение реле
            for name, t_off in list(self.relay_off_at.items()):
                if now >= t_off:
                    self._relay_write(name, False)
                    self.event("relay", "%s: выключено по таймеру" % self.title(name), relay=name)
            # входы
            for name, meta in self.input_meta.items():
                v = self._safe("input:" + name, lambda n=name: self.board.read_input(n))
                if v is None:
                    continue
                old = self.input_state.get(name)
                if old is not None and v != old:
                    if v:
                        self.input_count[name] += 1
                    self.event("input", "%s: %s" % (meta.get("title", name),
                                                     meta.get("on_text", "активен") if v else meta.get("off_text", "отпущен")),
                               input=name, state=v)
                self.input_state[name] = v
            # акселерометр - чаще остальных, ловим пик
            if self.hw.get("accel") or self.board.kind == "sim":
                a = self._safe("accel", self.board.read_accel)
                if a:
                    dev = abs(math.sqrt(a["x_mg"] ** 2 + a["y_mg"] ** 2 + a["z_mg"] ** 2) - 1000)
                    self.peak_mg = max(self.peak_mg, dev)
                    if dev >= self.shock_mg and (not self.last_shock or now - self.last_shock["t"] > 2):
                        self.last_shock = {"t": now, "mg": int(dev)}
                        self.event("shock", "Удар или встряска: %.1f g" % (dev / 1000.0), mg=int(dev))
                    snap["accel"] = a
            if slow:
                for key, fn in (("climate", self.board.read_climate), ("light", self.board.read_light)):
                    if self.hw.get(key) or self.board.kind == "sim":
                        v = self._safe(key, fn)
                        if v is not None:
                            snap[key] = v
                snap["system"] = self._safe("system", self.board.system)
            snap["relays"] = {n: self.board.get_relay(n) for n in self.relay_meta}
            snap["inputs"] = dict(self.input_state)
            snap["leds"] = self.board.get_leds()
            snap["estop"] = self.estop
            snap["read_only"] = self.read_only
            snap["errors"] = dict(self.errors)
            snap["t"] = now
            self.snapshot = snap
        self.publish("state", snap)
        return snap

    def _loop(self):
        fast = float(self.cfg.get("poll_fast_s", 0.2))
        slow = float(self.cfg.get("poll_slow_s", 2.0))
        last_slow = 0.0
        while not self._stop.is_set():
            t = time.time()
            snap = self.poll_once(slow=(t - last_slow >= slow))
            if self.rules is not None:
                try:
                    self.rules.evaluate(snap)
                except Exception as e:  # noqa - правило не должно останавливать опрос
                    print("rules: %s" % e, file=sys.stderr)
            if t - last_slow >= slow:
                last_slow = t
            self._stop.wait(fast)

    # ------------------------------------------------------------------ реле
    def title(self, name):
        return self.relay_meta.get(name, {}).get("title", name)

    def _relay_write(self, name, on):
        self.board.set_relay(name, on)
        self.relay_changed_at[name] = time.time()
        if not on:
            self.relay_off_at.pop(name, None)

    def all_relays_off(self, why):
        with self.lock:
            for name in self.relay_meta:
                try:
                    if self.board.get_relay(name):
                        self._relay_write(name, False)
                except BoardError as e:
                    print("relay off %s: %s" % (name, e), file=sys.stderr)

    def switch_relay(self, name, on, duration_s=None):
        """Все проверки безопасности в одном месте. Возвращает текст для модели или бросает ValueError."""
        now = time.time()
        with self.lock:
            if name not in self.relay_meta:
                raise ValueError("нет реле «%s». Есть: %s" % (name, ", ".join(self.relay_meta) or "нет"))
            if on and self.read_only:
                raise ValueError("стенд в режиме «только чтение» - включать нагрузку нельзя")
            if on and self.estop:
                raise ValueError("нажата аварийная кнопка - включение запрещено, пока её не отпустят")
            cur = self.board.get_relay(name)
            if cur == bool(on) and not (on and duration_s):
                return "%s: уже %s" % (self.title(name), "включено" if on else "выключено")
            last = self.relay_changed_at.get(name, 0)
            if on and now - last < self.min_interval_s:
                raise ValueError("слишком часто: подождите %.0f с между переключениями" % self.min_interval_s)
            while self.switch_times and now - self.switch_times[0] > 60:
                self.switch_times.popleft()
            if on and len(self.switch_times) >= self.max_switch_per_min:
                raise ValueError("лимит %d переключений в минуту исчерпан" % self.max_switch_per_min)
            limit = float(self.relay_meta[name].get("max_on_s", self.max_on_s))
            if on:
                dur = limit if duration_s is None else float(duration_s)
                if dur <= 0:
                    raise ValueError("длительность должна быть больше нуля")
                if dur > limit:
                    raise ValueError("максимум %d с для «%s»" % (limit, self.title(name)))
                self._relay_write(name, True)
                self.relay_off_at[name] = now + dur
                msg = "%s: включено на %d с" % (self.title(name), dur)
            else:
                self._relay_write(name, False)
                msg = "%s: выключено" % self.title(name)
            self.switch_times.append(now)
        self.event("relay", msg, relay=name, state=bool(on))
        self.poll_once(slow=False)
        return msg
