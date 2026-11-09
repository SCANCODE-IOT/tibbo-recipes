# LLM providers / Нейросети

One entry of `llm` or `llm_chain` = one model. Put keys in environment variables (`api_key_env`), not in
the file. Model names change often - check the provider's docs.

Одна запись `llm` или `llm_chain` - одна модель. Ключи - в переменных окружения (`api_key_env`), а не в
файле. Имена моделей меняются часто - сверяйтесь с документацией сервиса.

| Provider / Сервис | `api` | `url` | Notes / Заметки |
|---|---|---|---|
| **Ollama** (local) | `ollama` | `http://<host>:11434` | `OLLAMA_HOST=0.0.0.0` to accept LAN requests; `"think": false` makes qwen3 faster |
| **LM Studio** (local) | `openai` | `http://<host>:1234/v1` | enable the local server in LM Studio |
| **llama.cpp server / vLLM** (local) | `openai` | `http://<host>:<port>/v1` | start with tool calling enabled |
| **Anthropic (Claude)** | `anthropic` | *(default)* `https://api.anthropic.com` | `"api_key_env": "ANTHROPIC_API_KEY"`, e.g. `"model": "claude-sonnet-5-5"` |
| **OpenAI (ChatGPT)** | `openai` | `https://api.openai.com/v1` | `"api_key_env": "OPENAI_API_KEY"` |
| **DeepSeek** | `openai` | `https://api.deepseek.com/v1` | `"api_key_env": "DEEPSEEK_API_KEY"` |
| **Kimi (Moonshot)** | `openai` | `https://api.moonshot.ai/v1` | China region: `https://api.moonshot.cn/v1` |
| **GLM (Z.ai)** | `openai` | `https://api.z.ai/api/paas/v4` | GLM Coding Plan: `https://api.z.ai/api/coding/paas/v4` |
| **YandexGPT (AI Studio)** | `openai` | `https://llm.api.cloud.yandex.net/v1` | `"model": "gpt://<folder_id>/yandexgpt/latest"`, `"headers": {"OpenAI-Project": "<folder_id>"}`; tools: `tool_choice` auto only |
| **ГигаЧат** | `openai` | address of a local [`gpt2giga`](https://pypi.org/project/gpt2giga/) proxy | the proxy turns the GigaChat API into an OpenAI-compatible one; experimental |
| **OpenRouter** | `openai` | `https://openrouter.ai/api/v1` | hundreds of models behind one key |

Extra fields / Дополнительные поля: `timeout_s`, `max_steps` (tool-call steps per answer), `options.temperature`,
`headers`, `extra_body` (merged into the request, e.g. provider-specific switches), `local: true/false`
(overrides the "local / cloud" label on the panel).

Example chain: cloud first, local model when the internet is gone / облако первым, без интернета - локальная:

```json
"llm_chain": [
  {"name": "deepseek", "api": "openai", "url": "https://api.deepseek.com/v1", "model": "<model>", "api_key_env": "DEEPSEEK_API_KEY", "timeout_s": 40},
  {"name": "local", "api": "ollama", "url": "http://192.168.10.2:11434", "model": "qwen3:14b"}
]
```

Sources / источники: [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling),
[Yandex AI Studio OpenAI compatibility](https://yandex.cloud/en/docs/ai-studio/concepts/openai-compatibility).
