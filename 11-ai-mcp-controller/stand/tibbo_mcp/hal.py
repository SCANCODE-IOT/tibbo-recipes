"""Доступ к железу: эмулятор платы и настоящая LTPP3(G2).

Обе платы дают одинаковый набор методов, поэтому инструменты MCP не знают,
с чем работают. Всё на стандартной библиотеке Python 3.8+.
"""
import math
import os
import random
import threading
import time

LED_COUNT = 5


class BoardError(Exception):
    pass


# --------------------------------------------------------------------------- эмулятор

class SimBoard:
    """Правдоподобный стенд без железа: датчики шумят, лампа светит в датчик света,
    вентилятор охлаждает, по коробке можно «постучать»."""

    kind = "sim"

    def __init__(self, hw):
        self.hw = hw
        self.lock = threading.Lock()
        self.t0 = time.time()
        self.temp = 23.4
        self.hum = 41.0
        self.relays = {r["name"]: False for r in hw.get("relays", [])}
        self.inputs = {i["name"]: False for i in hw.get("inputs", [])}
        self.estop = False
        self.leds = [False] * LED_COUNT
        self.shock_until = 0.0
        self.shock_g = 0.0
        self.rng = random.Random(7)

    # --- управление эмулятором с панели
    def sim_set(self, what, value):
        with self.lock:
            if what == "knock":
                self.shock_until = time.time() + 0.8
                self.shock_g = float(value or 2.5)
            elif what in self.inputs:
                self.inputs[what] = bool(value)
            elif what == "estop":
                self.estop = bool(value)
            elif what == "temp":
                self.temp = float(value)
            else:
                raise BoardError("неизвестный параметр эмулятора: %s" % what)

    def _step(self):
        # медленная «физика»: вентилятор охлаждает, иначе возвращаемся к 23.4
        target = 21.0 if self.relays.get("fan") else 23.4
        self.temp += (target - self.temp) * 0.02 + self.rng.uniform(-0.03, 0.03)
        self.hum += (41.0 - self.hum) * 0.05 + self.rng.uniform(-0.1, 0.1)

    def read_climate(self):
        with self.lock:
            self._step()
            return {"temperature_c": round(self.temp, 1), "humidity_pct": round(self.hum, 1)}

    def read_light(self):
        with self.lock:
            base = 310 + 20 * math.sin((time.time() - self.t0) / 30.0)
            if self.relays.get("lamp"):
                base += 420
            raw = int(base * 1.2 + self.rng.uniform(-6, 6))
            return {"raw": raw}

    def read_accel(self):
        with self.lock:
            n = lambda: self.rng.uniform(-12, 12)
            x, y, z = n(), n(), 1000 + n()
            if time.time() < self.shock_until:
                k = self.shock_g * 1000
                x += self.rng.uniform(-k, k)
                y += self.rng.uniform(-k, k)
                z += self.rng.uniform(-k / 2, k / 2)
            return {"x_mg": int(x), "y_mg": int(y), "z_mg": int(z)}

    def read_input(self, name):
        with self.lock:
            return self.inputs[name]

    def read_estop(self):
        with self.lock:
            return self.estop

    def set_relay(self, name, on):
        with self.lock:
            self.relays[name] = bool(on)

    def get_relay(self, name):
        with self.lock:
            return self.relays[name]

    def set_leds(self, states):
        with self.lock:
            self.leds = [bool(s) for s in states]

    def get_leds(self):
        with self.lock:
            return list(self.leds)

    def system(self):
        return {"cpu_temp_c": round(46.0 + self.rng.uniform(-0.5, 0.5), 1),
                "uptime_s": int(time.time() - self.t0), "load": 0.12}


# --------------------------------------------------------------------------- LTPP3(G2)

PINS_INI = "/opt/tps-shared/hwini/pins.ini"


def read_pins_ini(path=PINS_INI):
    """[CPU] S1A=8 ... - карта линий сокетов в номера выводов процессора (как в node-ltps/pinmap)."""
    pins, section = {}, None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.split(";")[0].split("#")[0].strip()
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1].strip()
                elif "=" in line and section == "CPU":
                    k, v = line.split("=", 1)
                    try:
                        pins[k.strip().upper()] = int(v.strip())
                    except ValueError:
                        pass
    except OSError:
        pass
    return pins


class SysfsGpio:
    """Линия GPIO через /sys/class/gpio. Номер берётся из конфигурации или pins.ini."""

    def __init__(self, num, out, active_low, base="/sys/class/gpio"):
        self.num, self.base, self.active_low = num, base, active_low
        d = "%s/gpio%d" % (base, num)
        if not os.path.isdir(d):
            try:
                with open(base + "/export", "w") as f:
                    f.write(str(num))
            except OSError as e:
                raise BoardError("не удалось открыть GPIO %d: %s" % (num, e))
            for _ in range(50):  # udev выставляет права не сразу
                if os.path.exists(d + "/value"):
                    break
                time.sleep(0.02)
        self.dir = d
        want = "out" if out else "in"
        try:
            with open(d + "/direction") as f:
                cur = f.read().strip()
        except OSError:
            cur = ""
        if cur != want:
            with open(d + "/direction", "w") as f:
                # для выхода сразу задаём «выключено», чтобы реле не щёлкнуло при старте
                f.write(("high" if active_low else "low") if out else "in")

    def read(self):
        with open(self.dir + "/value") as f:
            v = f.read().strip() == "1"
        return (not v) if self.active_low else v

    def write(self, on):
        level = (not on) if self.active_low else bool(on)
        with open(self.dir + "/value", "w") as f:
            f.write("1" if level else "0")


class I2CDev:
    """Шина /dev/i2c-N через ioctl I2C_RDWR (ctypes, без smbus)."""

    I2C_RDWR = 0x0707
    I2C_M_RD = 0x0001

    def __init__(self, bus):
        import ctypes
        try:
            import fcntl
        except ImportError:
            raise BoardError("I2C доступен только на Linux")
        self.ctypes, self.fcntl = ctypes, fcntl
        self.path = "/dev/i2c-%d" % bus
        try:
            self.fd = os.open(self.path, os.O_RDWR)
        except OSError as e:
            raise BoardError("нет шины %s: %s" % (self.path, e))

        class Msg(ctypes.Structure):
            _fields_ = [("addr", ctypes.c_uint16), ("flags", ctypes.c_uint16),
                        ("len", ctypes.c_uint16), ("buf", ctypes.POINTER(ctypes.c_uint8))]

        class RdWr(ctypes.Structure):
            _fields_ = [("msgs", ctypes.POINTER(Msg)), ("nmsgs", ctypes.c_uint32)]

        self.Msg, self.RdWr = Msg, RdWr
        self.lock = threading.Lock()

    def transfer(self, addr, write=b"", read=0, write_only_empty=False):
        """Запись и/или чтение одной транзакцией (repeated start). Пустая запись - тоже транзакция."""
        c = self.ctypes
        msgs, bufs = [], []
        if write or write_only_empty or not read:
            wb = (c.c_uint8 * max(1, len(write)))(*write)
            bufs.append(wb)
            msgs.append(self.Msg(addr, 0, len(write), c.cast(wb, c.POINTER(c.c_uint8))))
        rb = None
        if read:
            rb = (c.c_uint8 * read)()
            bufs.append(rb)
            msgs.append(self.Msg(addr, self.I2C_M_RD, read, c.cast(rb, c.POINTER(c.c_uint8))))
        arr = (self.Msg * len(msgs))(*msgs)
        data = self.RdWr(c.cast(arr, c.POINTER(self.Msg)), len(msgs))
        with self.lock:
            try:
                self.fcntl.ioctl(self.fd, self.I2C_RDWR, data)
            except OSError as e:
                raise BoardError("I2C %s адрес 0x%02X: %s" % (self.path, addr, e))
        return bytes(rb) if rb is not None else b""


# Адреса взяты из тестовых проектов Tibbo CA-Test-Tibbit-28/30/36 (8-битные &h46, &h4E, &hA6 >> 1)
ADDR_BH1721 = 0x23   # Tibbit #28, датчик освещённости
ADDR_HIH6130 = 0x27  # Tibbit #30, температура и влажность
ADDR_ADXL312 = 0x53  # Tibbit #36, акселерометр


class Ltpp3Board:
    kind = "ltpp3g2"

    def __init__(self, hw, gpio_base="/sys/class/gpio", leds_dir="/proc/tpsleds"):
        self.hw = hw
        self.t0 = time.time()
        self.pins = read_pins_ini(hw.get("pins_ini", PINS_INI))
        self.gpio_base = gpio_base
        self.leds_dir = leds_dir
        self.lines = {}
        self.buses = {}
        self.relay_state = {}
        self.led_state = [False] * LED_COUNT
        self.accel_ready = False
        self.light_ready = False
        for r in hw.get("relays", []):
            self.lines["relay:" + r["name"]] = self._gpio(r, out=True)
            self.relay_state[r["name"]] = False
        for i in hw.get("inputs", []):
            self.lines["input:" + i["name"]] = self._gpio(i, out=False)
        if hw.get("estop"):
            self.lines["estop"] = self._gpio(hw["estop"], out=False)

    def _gpio(self, spec, out):
        num = spec.get("gpio")
        if num is None:
            line = str(spec.get("line", "")).upper()
            if line not in self.pins:
                raise BoardError("линия %s не найдена в %s - укажите \"gpio\" вручную" % (line, PINS_INI))
            num = self.pins[line]
        active_low = spec.get("active", "low" if not out else "high") == "low"
        return SysfsGpio(int(num), out, active_low, self.gpio_base)

    def _bus(self, name):
        spec = self.hw.get(name)
        if not spec:
            raise BoardError("датчик %s не настроен в config.json" % name)
        bus = int(spec["i2c_bus"])
        if bus not in self.buses:
            self.buses[bus] = I2CDev(bus)
        return self.buses[bus]

    def read_climate(self):
        b = self._bus("climate")
        b.transfer(ADDR_HIH6130, b"", write_only_empty=True)  # запрос измерения
        time.sleep(0.05)
        d = b.transfer(ADDR_HIH6130, read=4)
        status = d[0] >> 6
        if status == 3:
            raise BoardError("HIH6130 в командном режиме")
        hum = ((d[0] & 0x3F) << 8 | d[1]) * 100.0 / 16383
        temp = ((d[2] << 8 | d[3]) >> 2) * 165.0 / 16383 - 40
        return {"temperature_c": round(temp, 1), "humidity_pct": round(hum, 1),
                "stale": status == 1}

    def read_light(self):
        b = self._bus("light")
        if not self.light_ready:
            b.transfer(ADDR_BH1721, b"\x01")   # power on
            b.transfer(ADDR_BH1721, b"\x12")   # H-resolution mode
            time.sleep(0.18)
            self.light_ready = True
        d = b.transfer(ADDR_BH1721, read=2)
        return {"raw": d[0] << 8 | d[1]}

    def read_accel(self):
        b = self._bus("accel")
        if not self.accel_ready:
            dev = b.transfer(ADDR_ADXL312, b"\x00", read=1)[0]
            if dev != 0xE5:
                raise BoardError("ADXL312 не отвечает (DEVID=0x%02X)" % dev)
            b.transfer(ADDR_ADXL312, b"\x31\x0B")  # full resolution, ±12 g
            b.transfer(ADDR_ADXL312, b"\x2D\x08")  # measure
            self.accel_ready = True
        d = b.transfer(ADDR_ADXL312, b"\x32", read=6)

        def s16(lo, hi):
            v = hi << 8 | lo
            return v - 65536 if v & 0x8000 else v
        k = 2.9  # мг на единицу в режиме full resolution
        return {"x_mg": int(s16(d[0], d[1]) * k), "y_mg": int(s16(d[2], d[3]) * k),
                "z_mg": int(s16(d[4], d[5]) * k)}

    def read_input(self, name):
        return self.lines["input:" + name].read()

    def read_estop(self):
        line = self.lines.get("estop")
        return line.read() if line else False

    def set_relay(self, name, on):
        self.lines["relay:" + name].write(on)
        self.relay_state[name] = bool(on)

    def get_relay(self, name):
        return self.relay_state[name]

    def set_leds(self, states):
        if not os.path.isdir(self.leds_dir):
            raise BoardError("нет %s - не загружен модуль tpsleds" % self.leds_dir)
        for i, s in enumerate(states[:LED_COUNT]):
            with open("%s/%d" % (self.leds_dir, i), "w") as f:
                f.write("1" if s else "0")
        self.led_state = [bool(s) for s in states[:LED_COUNT]]

    def get_leds(self):
        return list(self.led_state)

    def system(self):
        out = {"uptime_s": None, "cpu_temp_c": None, "load": None}
        try:
            with open("/proc/uptime") as f:
                out["uptime_s"] = int(float(f.read().split()[0]))
            out["load"] = os.getloadavg()[0]
        except (OSError, AttributeError):
            pass
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                out["cpu_temp_c"] = round(int(f.read()) / 1000.0, 1)
        except (OSError, ValueError):
            pass
        return out

    def sim_set(self, what, value):
        raise BoardError("это настоящая плата, эмулятор недоступен")


def probe():
    """Разведка на плате: какие шины I2C есть и кто на них отвечает по адресам Tibbit."""
    found = []
    names = {ADDR_BH1721: "#28 BH1721", ADDR_HIH6130: "#30 HIH6130", ADDR_ADXL312: "#36 ADXL312"}
    try:
        buses = sorted(int(n[4:]) for n in os.listdir("/dev") if n.startswith("i2c-"))
    except OSError:
        buses = []
    for bus in buses:
        try:
            dev = I2CDev(bus)
        except BoardError as e:
            found.append({"bus": bus, "error": str(e)})
            continue
        for addr, title in names.items():
            try:
                if addr == ADDR_ADXL312:
                    ok = dev.transfer(addr, b"\x00", read=1)[0] == 0xE5
                else:
                    dev.transfer(addr, read=1)
                    ok = True
            except BoardError:
                ok = False
            if ok:
                found.append({"bus": bus, "addr": "0x%02X" % addr, "tibbit": title})
    return {
        "i2c_buses": buses,
        "sensors": found,
        "pins_ini": PINS_INI if os.path.exists(PINS_INI) else None,
        "pins": read_pins_ini(),
        "gpio_sysfs": os.path.isdir("/sys/class/gpio"),
        "tpsleds": os.path.isdir("/proc/tpsleds"),
    }


def make_board(cfg):
    if cfg.get("board", "sim") == "sim":
        return SimBoard(cfg.get("hardware", {}))
    return Ltpp3Board(cfg.get("hardware", {}))
