"""Мост между нейросетью и инструментами стенда.

Нейросеть может быть локальной (Ollama, LM Studio, llama.cpp, vLLM - без интернета) или облачной
(Claude, ChatGPT, DeepSeek, Kimi, GLM, YandexGPT и любой сервис с OpenAI-совместимым API).
Можно задать цепочку: облако первым, а если интернет пропал - локальная модель.
Плата отправляет вопрос и список инструментов, выполняет вызовы и возвращает результаты.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

SYSTEM_PROMPT = """Ты - ИИ-помощник выставочного стенда Сканкод, официального дистрибьютора Tibbo.
Перед тобой настоящий Linux-контроллер Tibbo LTPP3(G2) с Tibbit-модулями: датчик температуры и влажности #30,
датчик света #28, акселерометр #36, реле #03, входы #54 и шкала из 5 синих светодиодов.

Правила:
- Отвечай на языке посетителя, коротко и дружелюбно: 1-3 предложения. Посетитель читает с экрана.
- Любые цифры о стенде бери только из инструментов. Не знаешь - вызови инструмент. Никогда не придумывай показания.
- Реле включай только когда человек прямо просит. Включение всегда на ограниченное время.
- Если инструмент вернул ошибку - честно скажи, что не получилось и почему.
- Про платы TPS и код Tibbo BASIC проверяй через check_tps_config и lint_tibbo_code, а не по памяти.
- Просьбы вида «если ..., то ...», «всегда», «каждый раз» оформляй правилом через create_rule:
  правило выполняет сама плата, даже без нейросети. Перед созданием кратко повтори правило словами.
- Можно делать несколько шагов: например, прочитать свет, включить лампу и показать уровень на светодиодах.
"""


class LLMError(Exception):
    pass


class LLMUnreachable(LLMError):
    """Нет связи (нет интернета, сервер выключен) - повод перейти к следующей модели."""


def _post(url, body, timeout, headers=None):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=dict({"Content-Type": "application/json"}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")[:300]
        if e.code in (401, 403):
            raise LLMError("сервис нейросети отклонил ключ доступа (%s)" % e.code)
        if e.code >= 500 or e.code == 429:
            raise LLMUnreachable("сервис нейросети недоступен (%s): %s" % (e.code, txt))
        raise LLMError("нейросеть ответила %s: %s" % (e.code, txt))
    except (urllib.error.URLError, OSError) as e:
        raise LLMUnreachable("нет связи с %s: %s" % (urlparse(url).netloc, getattr(e, "reason", e)))
    except ValueError:
        raise LLMError("нейросеть вернула не JSON")


def _get(url, timeout, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _args(a):
    if isinstance(a, str):
        try:
            return json.loads(a or "{}")
        except ValueError:
            return {"_bad_json": a}
    return a or {}


def tools_for_llm(registry):
    return [{"type": "function", "function": {"name": d["name"], "description": d["description"],
                                              "parameters": d["inputSchema"]}} for d in registry.list()]


# ----------------------------------------------------------------------------- бэкенды
# Внутренний формат диалога одинаков для всех:
#   {"role": "user", "content": str}
#   {"role": "assistant", "content": str, "calls": [{"id", "name", "args"}]}
#   {"role": "tool", "call": {...}, "content": str}

class Backend:
    def __init__(self, c):
        self.c = c
        self.name = c.get("name") or c.get("api", "ollama")
        self.model = c.get("model", "")
        self.timeout = float(c.get("timeout_s", 120))
        self.options = c.get("options", {"temperature": 0.3})
        key = c.get("api_key") or ""
        if c.get("api_key_env"):
            key = os.environ.get(c["api_key_env"], "") or key
        self.api_key = key
        self.headers = dict(c.get("headers") or {})
        self.local = c.get("local")

    def describe(self):
        return {"name": self.name, "model": self.model, "local": self.is_local()}

    def is_local(self):
        if self.local is not None:
            return bool(self.local)
        host = (urlparse(self.c.get("url", "")).hostname or "").lower()
        return host in ("localhost", "127.0.0.1", "::1") or host.startswith(("192.168.", "10.", "172.")) or host.endswith(".local")


class Ollama(Backend):
    def __init__(self, c):
        super().__init__(c)
        self.url = c.get("url", "http://127.0.0.1:11434").rstrip("/")
        self.model = self.model or "qwen3:14b"
        self.think = c.get("think", False)

    def step(self, system, conv, tools):
        msgs = [{"role": "system", "content": system}]
        for m in conv:
            if m["role"] == "assistant":
                x = {"role": "assistant", "content": m.get("content") or ""}
                if m.get("calls"):
                    x["tool_calls"] = [{"function": {"name": c["name"], "arguments": c["args"]}} for c in m["calls"]]
                msgs.append(x)
            elif m["role"] == "tool":
                msgs.append({"role": "tool", "tool_name": m["call"]["name"], "content": m["content"]})
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        body = {"model": self.model, "messages": msgs, "tools": tools, "stream": False, "options": self.options}
        if self.think is not None:
            body["think"] = self.think
        m = (_post(self.url + "/api/chat", body, self.timeout, self.headers).get("message")) or {}
        calls = [{"id": None, "name": (tc.get("function") or {}).get("name"),
                  "args": _args((tc.get("function") or {}).get("arguments"))} for tc in m.get("tool_calls") or []]
        return m.get("content") or "", calls

    def health(self):
        d = _get(self.url + "/api/tags", 4, self.headers)
        names = [x.get("name") for x in d.get("models", [])]
        return self.model in names or any((n or "").split(":")[0] == self.model.split(":")[0] for n in names)


class OpenAICompat(Backend):
    """OpenAI, DeepSeek, Kimi (Moonshot), GLM (Z.ai), YandexGPT, OpenRouter, LM Studio, llama.cpp, vLLM..."""

    def __init__(self, c):
        super().__init__(c)
        url = c.get("url", "http://127.0.0.1:1234/v1").rstrip("/")
        if urlparse(url).path in ("", "/"):
            url += "/v1"
        self.url = url

    def _hdr(self):
        h = dict(self.headers)
        if self.api_key:
            h["Authorization"] = "Bearer " + self.api_key
        return h

    def step(self, system, conv, tools):
        msgs = [{"role": "system", "content": system}]
        for m in conv:
            if m["role"] == "assistant":
                x = {"role": "assistant", "content": m.get("content") or None}
                if m.get("calls"):
                    x["tool_calls"] = [{"id": c["id"], "type": "function",
                                        "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}}
                                       for c in m["calls"]]
                msgs.append(x)
            elif m["role"] == "tool":
                msgs.append({"role": "tool", "tool_call_id": m["call"]["id"], "content": m["content"]})
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        body = {"model": self.model, "messages": msgs, "tools": tools, "stream": False}
        if "temperature" in self.options:
            body["temperature"] = self.options["temperature"]
        body.update(self.c.get("extra_body") or {})
        r = _post(self.url + "/chat/completions", body, self.timeout, self._hdr())
        try:
            m = r["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("неожиданный ответ сервиса: %s" % json.dumps(r, ensure_ascii=False)[:200])
        calls = []
        for i, tc in enumerate(m.get("tool_calls") or []):
            f = tc.get("function") or {}
            calls.append({"id": tc.get("id") or "call_%d" % i, "name": f.get("name"), "args": _args(f.get("arguments"))})
        return m.get("content") or "", calls

    def health(self):
        d = _get(self.url + "/models", 6, self._hdr())
        ids = [x.get("id") for x in d.get("data", [])]
        return (not ids) or self.model in ids


class Anthropic(Backend):
    """Claude через Messages API."""

    def __init__(self, c):
        super().__init__(c)
        self.url = c.get("url", "https://api.anthropic.com").rstrip("/")
        self.model = self.model or "claude-sonnet-5-5"
        self.max_tokens = int(c.get("max_tokens", 1024))

    def _hdr(self):
        return dict(self.headers, **{"x-api-key": self.api_key, "anthropic-version": "2023-06-01"})

    def step(self, system, conv, tools):
        msgs = []
        for m in conv:
            if m["role"] == "assistant":
                blocks = ([{"type": "text", "text": m["content"]}] if m.get("content") else [])
                blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in m.get("calls") or []]
                msgs.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "…"}]})
            elif m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["call"]["id"], "content": m["content"]}
                if msgs and msgs[-1]["role"] == "user" and isinstance(msgs[-1]["content"], list) \
                        and msgs[-1]["content"] and msgs[-1]["content"][0].get("type") == "tool_result":
                    msgs[-1]["content"].append(block)
                else:
                    msgs.append({"role": "user", "content": [block]})
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        body = {"model": self.model, "max_tokens": self.max_tokens, "system": system, "messages": msgs,
                "tools": [{"name": t["function"]["name"], "description": t["function"]["description"],
                           "input_schema": t["function"]["parameters"]} for t in tools]}
        if "temperature" in self.options:
            body["temperature"] = self.options["temperature"]
        r = _post(self.url + "/v1/messages", body, self.timeout, self._hdr())
        text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
        calls = [{"id": b["id"], "name": b["name"], "args": b.get("input") or {}}
                 for b in r.get("content", []) if b.get("type") == "tool_use"]
        return text, calls

    def health(self):
        return bool(self.api_key)


KINDS = {"ollama": Ollama, "openai": OpenAICompat, "anthropic": Anthropic}


def make_backend(c):
    api = c.get("api", "ollama")
    if api not in KINDS:
        raise ValueError("неизвестный api нейросети: %s (есть: %s)" % (api, ", ".join(KINDS)))
    return KINDS[api](c)


# ----------------------------------------------------------------------------- агент

class Agent:
    def __init__(self, registry, cfg, stand=None):
        self.reg = registry
        self.stand = stand
        chain = cfg.get("llm_chain") or [cfg.get("llm", {})]
        self.backends = [make_backend(c) for c in chain]
        first = chain[0]
        self.max_steps = int(first.get("max_steps", cfg.get("llm", {}).get("max_steps", 6)))
        self.system = first.get("system_prompt") or cfg.get("system_prompt") or SYSTEM_PROMPT
        self.active = self.backends[0]

    @property
    def model(self):
        return self.active.model

    @property
    def url(self):
        return getattr(self.active, "url", "")

    def chat(self, history, emit=lambda kind, data: None):
        """history - [{role, content}]. Возвращает текст. emit(kind, data): backend, call, result, text."""
        conv = [{"role": m["role"], "content": m["content"]} for m in history]
        tools = tools_for_llm(self.reg)
        t0 = time.time()
        errors = []
        for b in self.backends:
            self.active = b
            emit("backend", b.describe())
            try:
                return self._loop(b, conv, tools, t0, emit)
            except LLMUnreachable as e:
                errors.append("%s: %s" % (b.name, e))
                continue
        raise LLMError("ни одна нейросеть не ответила. " + " | ".join(errors))

    def _loop(self, b, conv, tools, t0, emit):
        for _ in range(self.max_steps):
            content, calls = b.step(self.system, conv, tools)
            if not calls:
                text = _clean(content) or "(нейросеть не ответила текстом)"
                emit("text", {"text": text, "seconds": round(time.time() - t0, 1), "model": b.model,
                              "local": b.is_local()})
                return text
            conv.append({"role": "assistant", "content": content, "calls": calls})
            for c in calls:
                emit("call", {"tool": c["name"], "args": c["args"]})
                if "_bad_json" in c["args"]:
                    data, err = {"error": "аргументы не в формате JSON"}, True
                else:
                    data, err = self.reg.call(c["name"], c["args"])
                if self.stand:
                    self.stand.log_call("llm:" + b.name, c["name"], c["args"], data, err)
                emit("result", {"tool": c["name"], "result": data, "error": err})
                conv.append({"role": "tool", "call": c, "content": json.dumps(data, ensure_ascii=False)})
        text = "Задача оказалась длинной: я сделал %d шагов и остановился. Спросите проще?" % self.max_steps
        emit("text", {"text": text, "seconds": round(time.time() - t0, 1), "model": b.model, "local": b.is_local()})
        return text

    def health(self):
        out = []
        for b in self.backends:
            d = b.describe()
            try:
                d["ok"] = True
                d["available"] = bool(b.health())
            except Exception as e:  # noqa
                d["ok"], d["available"], d["error"] = False, False, str(e)[:200]
            out.append(d)
        first_ok = next((d for d in out if d["ok"] and d["available"]), None)
        main = first_ok or out[0]
        return dict(main, chain=out, model=main["model"])


def _clean(text):
    """Убираем рассуждения <think>…</think>, если модель их выдала в тексте."""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
