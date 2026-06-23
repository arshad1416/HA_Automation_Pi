# HA Automation Pi

A local-first Home Assistant brain running on a Raspberry Pi 5 that survives WAN outages with optional cloud fallback. Combines on-device LLM inference (Ollama + Gemma 3), Alexa voice announcements, and event-triggered proactive automations to create a smart home that stays intelligent when the internet goes down.

## What It Does

This project transforms a Raspberry Pi 5 into a self-contained smart home AI that:

- **Runs entirely on local hardware** — All LLM inference happens on the Pi via Ollama. Internet outage → lights, locks, thermostat, and voice announcements still work.
- **Makes proactive decisions** — Three event-driven automations monitor the home and narrate context-aware alerts through Alexa Echo devices (e.g., "Front door has been open for 5 minutes" instead of a generic beep).
- **Controls 18+ smart home entities** — Lights, door locks, thermostat, fans, blinds, switches, and door sensors exposed for both local LLM control and voice commands.
- **Offers cloud-enhanced reasoning** — Google Gemini handles default cloud queries; Claude Opus via OpenRouter available on-demand for complex reasoning tasks.

## Architecture

```
┌──────────────────────────────────────────────────┐
│ Pi 5 (always-on, aarch64, 8 GB RAM)              │
│                                                  │
│  Home Assistant (Docker, host network mode)     │
│   ├─ Ollama × 2 (chat + control)  ──┐            │
│   ├─ Google Gemini integration       │            │
│   ├─ OpenAI integration (Claude     ─┘← cloud    │
│   │   via OpenRouter base URL)                   │
│   └─ automations.yaml → notify.alexa_media      │
│                                         │        │
│  Ollama 0.21.2 (host, *:11434) ────────┘        │
│   ├─ orieg/gemma3-tools:4b-ft (primary, 2.5 GB) │
│   └─ qwen2.5:7b (contingency, 4.7 GB)           │
└──────────────────────────────────────────────────┘
                               │
                               ▼
                        Echo Dots (Amazon cloud)
```

### Four Conversation Agents

| Agent | Backend | Control | Purpose |
|---|---|---|---|
| **Local Chat** | Ollama → Gemma 3 4B | No | Fast, terse text responses. WAN-proof. |
| **Local Control** | Ollama → Gemma 3 4B | Yes | Tool-calling for device control (lights, locks, climate). |
| **Gemini** | Google Gemini | Yes | Cloud default — fast, cheap, handles 99% of cloud calls. |
| **Claude** | OpenRouter → Claude Opus | No | On-demand deep reasoning. |

### Proactive Automations

Three event-triggered automations that use the local LLM for contextual narration:

| Automation | Trigger | Behavior |
|---|---|---|
| `proactive_front_door_left_open` | Front door sensor stays open > 5 min | LLM generates a natural-language alert sent to Echo devices |
| `proactive_welcome_home` | Front door opens after being closed | LLM greets with context-aware message (time of day, weather-aware) |
| `proactive_nightly_lock_check` | Scheduled nightly | LLM checks lock states and announces any unsecured doors |

All three use `agent_id: conversation.local_chat` — the cloud-independent Ollama agent — so they work during WAN outages.

## Hardware & Software

| Component | Detail |
|---|---|
| **Device** | Raspberry Pi 5, 8 GB RAM, aarch64 |
| **Home Assistant** | Docker container, host network mode |
| **LLM Engine** | Ollama 0.21.2, bound to `*:11434` |
| **Primary Model** | `orieg/gemma3-tools:4b-ft` (2.5 GB) — Gemma 3 4B with QLoRA tool-calling fine-tune |
| **Contingency Model** | `qwen2.5:7b` (4.7 GB) — swap-in if Gemma misfire rate > 15% |
| **Voice** | Amazon Echo Dots via `notify.alexa_media` |
| **Exposed Entities** | 18 devices (8 lights, 2 locks, 1 climate, 2 fans, 2 covers, 2 switches, 1 door sensor) |

## Repository Structure

```
HA_Automation_Pi/
├── README.md                          # This file
├── plan.md                            # Full technical plan: architecture, decisions, phases
├── walkthrough.md                     # Step-by-step HA UI setup instructions
├── pi-config/
│   └── ollama-systemd-override.conf   # systemd override binding Ollama to *:11434
├── reference/
│   └── entities.md                    # Discovered HA entity IDs and their states
└── verification/
    └── smoke-tests.sh                 # End-to-end verification script for all 4 agents
```

## Key Design Decisions

- **Dual-agent pattern**: The same Gemma 3 4B model runs as two separate HA integrations — one for chat (no tool access), one for device control (tool access). HA recommends this for small models, which degrade when doing both chat and tool-calling simultaneously.
- **WAN independence**: Proactive automations and local chat use the Pi's Ollama instance, not cloud APIs. Smart home stays smart offline.
- **Measured contingency**: Gemma 3's tool-calling is realistically 70-85% reliable at 18 exposed entities. A pre-pulled `qwen2.5:7b` model sits ready as a one-field swap if misfires exceed 15%. Don't pre-optimize — measure first.
- **Alexa for voice, not LLM input**: Echo Dots handle TTS output only. Full LLM-by-voice through Alexa would require a custom Alexa skill (deferred).
- **Mac untouched**: The development Mac stays pinned at Ollama 0.20.3 (per project constraints), completely separate from the Pi's Ollama setup.

## Setup Summary

1. **Ollama on Pi**: Upgraded to 0.21.2, bound to LAN (`0.0.0.0:11434` via systemd override)
2. **Model pulled**: `orieg/gemma3-tools:4b-ft` with verified `tools` capability
3. **Contingency model**: `qwen2.5:7b` pre-pulled as fallback
4. **HA integrations**: 2× Ollama (Local Chat + Local Control), Google Gemini, Claude via OpenRouter
5. **Entities exposed**: 18 devices through Local Control's `llm_hass_api`
6. **Proactive automations**: Three event-driven LLM narrations through Alexa Echo devices

Full step-by-step instructions in [walkthrough.md](walkthrough.md).

## Tuning

- **System prompt tightened** (2026-04-30): Local Chat's prompt reduced output from ~40-60 words to ~15 words. Saved ~3-4× output tokens, shaving 5-10 seconds from proactive narration latency.
- **Entity count capped**: 18 entities exposed (below the ~22 entity threshold where Gemma 3 4B's tool-call accuracy degrades sharply).

## Known Caveats

- **TTS engine**: Uses `tts.google_translate_en_com` (internet-dependent). Proactive automations use `notify.alexa_media` directly, so they work offline. Only HA Assist sidebar audio replies need internet. Offline TTS would require a Piper Docker sidecar (separate work).
- **Gemma tool-call reliability**: Author benchmarks show degradation past ~22 entities. At 18 entities, expect 70-85% accuracy. If real-use misfire rate exceeds 15%, swap Local Control to `qwen2.5:7b`.

## Verification

```bash
# Run all 4 agent smoke tests
./verification/smoke-tests.sh

# Expected output:
# Local Chat:    PONG
# Local Control: kitchen light toggles on
# Gemini:        Paris
# Claude:        Free-form octopus facts
```

## License

MIT
