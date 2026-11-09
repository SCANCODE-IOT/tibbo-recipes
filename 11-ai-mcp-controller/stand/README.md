# Tibbo MCP Stand - AI that drives real Tibbo hardware

> ### ⚠️ BETA - needs work
> Built and tested end-to-end on a **simulator** (27 tests, the official MCP Python SDK, desktop and phone).
> It has **not yet run on a real Tibbo LTPP3(G2)**. That last step needs someone with the board on the desk,
> and that person may be **you**.
>
> 🇷🇺 [Русская версия](README.ru.md) · 📊 Presentation: [EN](docs/presentation-en.pdf) · [RU](docs/presentation-ru.pdf)

![Stand panel](docs/panel.png)

## Found this repo by accident? Good. We were hoping you would.

Most AI demos stop at the screen. This one reaches out of it and **flips a real relay, reads a real sensor
and notices when somebody knocks on the box**. The controller is a Tibbo LTPP3(G2), Linux on DIN-rail-friendly
hardware with plug-in Tibbit modules. The protocol is MCP, the open standard that lets any AI call tools.
The AI can be Claude, ChatGPT, DeepSeek, Kimi, GLM, YandexGPT or a model running on a laptop with no
internet at all.

The skeleton works. The first contact with real silicon still has to happen. What is missing is
listed below, each item small enough for one evening:

- **You have an LTPP3(G2)?** Run `python3 -m tibbo_mcp --probe`, open a
  [hardware report](../../issues/new?template=hardware-report.md) and tell us what you see. This is the
  most valuable contribution right now.
- **You know Linux GPIO and I²C?** Check our sysfs and `/dev/i2c` code against the real board, or port it
  to libgpiod.
- **You like AI agents?** Try other models, tune the system prompt and send us transcripts where the model
  got confused.
- **You build UIs?** The panel is a single HTML file with no dependencies. Make it bilingual, add charts,
  add voice.
- **You have an idea we did not think of?** Open an issue. "Wouldn't it be cool if…" is a perfectly
  good title.

Read [CONTRIBUTING.md](CONTRIBUTING.md) and say hi. Every merged PR gets a thank-you in the release notes.

## What it does

Four ways to run it, from a box with no network to a fleet of sites:

| Mode | The AI lives… | Internet | What you get |
|---|---|---|---|
| **1. Offline stand** | on a laptop next to the board (Ollama, LM Studio, llama.cpp) | not needed | trade-show demo that never depends on venue Wi-Fi |
| **2. Cloud brains** | Claude, ChatGPT, DeepSeek, Kimi, GLM, YandexGPT… | yes, with automatic **fallback to a local model** when the link drops | the smartest model, and a stand that keeps working when the link drops |
| **3. Board as a cloud tool** | in claude.ai or any remote MCP client, via a tunnel | yes | your phone's AI app reads the showroom sensors; **read-only by default** |
| **4. Fleet** | one AI, many boards (`fleet_status`, `fleet_call`) | LAN or VPN | "Which of our 12 sites is overheating?" |

And one feature that makes the AI much more than a chatbot:

### Rules: the AI writes the automation, the board runs it
Say *"if the cabinet door stays open for more than 10 seconds, turn the lamp on for a minute"*. The AI
creates a rule with `create_rule`. From then on **the board executes it by itself**, every poll cycle,
even after the AI is switched off. Rules go through the same safety layer as manual commands: relay timers,
e-stop and read-only mode.

### Tools exposed over MCP

| Tool | What it does | Hardware |
|---|---|---|
| `stand_status` | what is connected, modes, CPU temperature | board |
| `read_climate` | temperature and humidity | Tibbit #30 (HIH6130) |
| `read_light` | ambient light | Tibbit #28 (BH1721) |
| `read_motion` | tilt, shocks, "did someone knock?" | Tibbit #36 (ADXL312) |
| `read_inputs` | button and cabinet door, activation counters | Tibbit #54 |
| `recent_events` | event log | - |
| `set_relay` | lamp and fan, always with a timer | Tibbit #03 |
| `set_leds` | the board's 5 blue LEDs: level or pattern | board |
| `create_rule` / `list_rules` / `delete_rule` | automation rules executed by the board | - |
| `check_tps_config` | checks a visitor's TPS board layout and draws it | [tibbo-ai-skills](https://github.com/SCANCODE-IOT/tibbo-ai-skills) |
| `find_tibbit` | search the catalogue of 84 Tibbits | tibbo-ai-skills |
| `lint_tibbo_code` | catches invented API names in Tibbo BASIC / C | tibbo-ai-skills |
| `fleet_status` / `fleet_call` | other boards in the fleet (hub mode) | - |

Pure Python 3.9+ standard library. Nothing to `pip install` on the board.

## Quick start: simulator, 2 minutes, no hardware

```bash
git clone https://github.com/SCANCODE-IOT/tibbo-mcp-stand
git clone https://github.com/SCANCODE-IOT/tibbo-ai-skills     # board/code checks
cd tibbo-mcp-stand
python3 tools/mock_ollama.py --port 11434 &                    # fake LLM, or run a real Ollama
python3 -m tibbo_mcp --sim --listen 127.0.0.1:8080
```

Open http://127.0.0.1:8080/. In the simulator the lamp shines into the light sensor, the fan cools the
cabinet, and the panel has buttons to knock on the box, open the door or press the e-stop.
Staff panel: `/?staff`.

With a real local model instead of the mock: `ollama pull qwen3:14b` (about 9 GB, GPU with 12 GB+), copy
`config.example.json` to `config.json`, set `llm.url` to `http://127.0.0.1:11434`, then run
`python3 -m tibbo_mcp --config config.json --sim`.

## Mode 2: cloud models with local fallback

Use `config.cloud.example.json`. `llm_chain` is tried in order. If a provider cannot be reached (no internet,
5xx, 429), the next one answers. Keep keys out of the file: `api_key_env` reads them from the environment.

```json
"llm_chain": [
  {"name": "claude", "api": "anthropic", "model": "claude-sonnet-5-5", "api_key_env": "ANTHROPIC_API_KEY"},
  {"name": "local",  "api": "ollama", "url": "http://192.168.10.2:11434", "model": "qwen3:14b"}
]
```

Provider presets (`api` + `url`) are in [docs/providers.md](docs/providers.md): Anthropic, OpenAI, DeepSeek,
Kimi (Moonshot), GLM (Z.ai), YandexGPT, GigaChat (through `gpt2giga`), OpenRouter, LM Studio, llama.cpp,
vLLM. Always check the current model names in each provider's docs.

## Mode 3: the board as a tool for cloud AI apps

A cloud AI needs a public HTTPS address. The easiest way is a Cloudflare quick tunnel on the board or on
the laptop:

```bash
cloudflared tunnel --url http://localhost:8080
# -> https://<random>.trycloudflare.com
```

Set a long random `mcp.secret_path` in the config. The MCP address becomes
`https://<random>.trycloudflare.com/mcp/<secret_path>`. Use it in any client that connects to remote MCP
servers by URL. For clients that can send headers, use `/mcp` plus `Authorization: Bearer <token>`.

Through a tunnel (requests carrying `Cf-Connecting-Ip` or `X-Forwarded-For`) the server:
- exposes **only MCP**, so the panel and the chat stay inside the stand's network;
- is **read-only** unless you set `mcp.internet_write: true`.

Tested with the official MCP Python SDK. Specific cloud apps are on the "please test" list.

## Mode 4: fleet

Run a hub with `config.hub.example.json`: list the other boards' MCP URLs and tokens. The hub can be a board,
a laptop or a server. The AI gets `fleet_status` (summary of all sites in parallel) and `fleet_call(board,
tool, arguments)`. Remote writes are off unless `fleet_write: true`, and each board still enforces its own
safety rules.

## On real hardware (LTPP3(G2))

Suggested layout, reliable and without overpaying. The board's built-in 8-60 V supply powers everything.

| Sockets | Tibbits | Purpose |
|---|---|---|
| S3 + S4 | #00-3 + #30 | temperature / humidity |
| S5 + S6 | #00-3 + #28 | light |
| S7 + S8 | #00-3 + #36 | accelerometer |
| S9 + S10 | #03-1 + #21 | relays: 12 V lamp and fan |
| S11 + S12 | #54 + #21 | button, door reed switch, e-stop |
| *expansion* S13 + S14 | #05 + #21 | RS-485 Modbus meter |

```bash
python3 -m tibbo_mcp --probe     # finds I2C buses and sensors, reads /opt/tps-shared/hwini/pins.ini
sh deploy/install.sh             # installs to /opt/tibbo-stand, systemd service
```

**Unverified on hardware, and this is where we need you:** I²C bus numbers, GPIO numbering from `pins.ini`
(as used by Tibbo's `node-ltps`), relay and input polarity, the `tpsleds` kernel module interface, and the
Python version shipped with the board image. The sensor I²C addresses come from Tibbo's
CA-Test-Tibbit-28/30/36 projects.

Trade-show trick: once the stand is set up, enable the LTPP3(G2) **overlay** root filesystem. Any power
cycle then brings the stand back to a clean state.

## Safety

- Relays switch on only with a timer: 10 minutes max by default, then auto-off.
- Rate limits: one switch per relay per 2 s, at most 20 per minute.
- A hardware **e-stop** input switches every load off immediately and blocks switching on.
- **Read-only** mode: the AI sees sensors, touches nothing.
- All relays switch off when the server stops.
- Cross-site requests (foreign `Origin`) are rejected, so a web page cannot drive the stand.
- Internet clients get MCP only, read-only by default.

## Roadmap - pick one!

- [ ] **First run on a real LTPP3(G2)** ← the big one
- [ ] libgpiod backend, interrupt-driven inputs, ADXL312 tap/activity interrupt instead of polling
- [ ] Modbus RTU tool through #05 ("AI reads a real energy meter")
- [ ] Voice: offline speech-to-text (whisper.cpp / Vosk) and text-to-speech at the stand
- [ ] Bilingual panel (EN/RU switch), history charts
- [ ] OAuth for remote MCP clients that require it
- [ ] TiOS boards (TPP2/TPP3, DS, EM) as fleet members via a small HTTP bridge in Tibbo BASIC
- [ ] Home Assistant / Node-RED integration
- [ ] Rules: time-of-day conditions, AND/OR, notifications to Telegram

## How it is built

```
tibbo_mcp/mcp.py      MCP protocol (stdio + Streamable HTTP), no dependencies
tibbo_mcp/hal.py      simulator and LTPP3(G2) driver: sysfs GPIO, /dev/i2c via ioctl, /proc/tpsleds, --probe
tibbo_mcp/stand.py    polling, events, relay safety layer
tibbo_mcp/rules.py    automation rules engine
tibbo_mcp/fleet.py    minimal MCP client and fleet hub
tibbo_mcp/agent.py    LLM bridge: Ollama, OpenAI-compatible, Anthropic, fallback chain
tibbo_mcp/web.py      HTTP server: panel, /mcp, chat, server-sent events
tibbo_mcp/static/     the panel (single HTML file, works offline)
tools/mock_ollama.py  fake LLM for tests and rehearsals
tests/                python3 -m unittest discover -s tests
```

## License and credits

MIT © 2026 [Scancode](https://tibbo.ru), the official Tibbo distributor in Russia and the CIS.
Tibbo, Tibbit, TiOS and AppBlocks are trademarks of Tibbo Technology Inc. This is a community project and is
not an official Tibbo product. Model and service names belong to their owners.
