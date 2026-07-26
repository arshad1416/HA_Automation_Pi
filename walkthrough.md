# HA UI Walkthrough — Add the four conversation agents

Pi-side prep is done. This walkthrough sets up the four HA conversation agents (2 local Ollama + Gemini + Claude/OpenRouter) via the HA web UI. After this, the proactive automations in `automations/proactive.yaml` can be installed.

Open HA at http://homeassistant.local:8123 (or your usual URL) and follow each section.

---

## 1. Local Chat (Ollama, no HA control)

**Settings → Devices & Services → Add Integration → Ollama**

| Field | Value |
|---|---|
| URL | `http://localhost:11434` |
| Model | `orieg/gemma3-tools:4b-ft` |
| Name (after add → Configure) | `Local Chat` |
| Control Home Assistant | **OFF** |
| System prompt | `You are the home's local assistant. Be terse and direct. Never call tools — just reply with text.` |
| Max history | `20` |

After it's added, **Configure** → set the name to `Local Chat` (this becomes the agent slug `conversation.local_chat` used in automations).

---

## 2. Local Control (Ollama, HA control ON)

**Settings → Devices & Services → Add Integration → Ollama** (yes, add a second instance)

| Field | Value |
|---|---|
| URL | `http://localhost:11434` |
| Model | `orieg/gemma3-tools:4b-ft` |
| Name (after add → Configure) | `Local Control` |
| Control Home Assistant | **ON** |
| System prompt | `You are a smart home controller. Only call a tool if the user explicitly asks to change a device or query a device's state. For conversational questions, reply with one short sentence and do NOT call tools.` |
| Max history | `5` |

**Then expose entities**: **Settings → Voice assistants → Expose** → toggle ON for **<25 entities** total. Suggested set:
- Lights: kitchen, living room, bedroom (3-5 lights)
- Climate: ecobee thermostat
- Locks: `lock.front_door`, `lock.garages_entry_door` (skip `lock.airbnb`)
- Sensors: `binary_sensor.front_door_door`
- Media: a couple of Echos for queries
- Scripts: any "good night" / "leaving" routines you want voice-controllable

**Why <25**: the model's tool-call accuracy degrades sharply past ~22 tools per the author's benchmarks.

---

## 3. Google Gemini (cloud default)

**Settings → Devices & Services → Add Integration → Google Generative AI**

| Field | Value |
|---|---|
| API key | (paste from `~/.zshenv` `GEMINI_API_KEY`) |
| Name | `Gemini` |
| Model | `gemini-2.5-flash` (default — fast, cheap, generous free tier) |
| Control Home Assistant | **ON** |
| System prompt | (leave default) |

To get the key: `grep GEMINI_API_KEY ~/.zshenv` on the Mac.

---

## 4. Claude via OpenRouter (cloud, on-demand)

**Settings → Devices & Services → Add Integration → OpenAI Conversation**

| Field | Value |
|---|---|
| API key | (paste from `~/.zshenv` `OPENROUTER_API_KEY`) |
| Base URL | `https://openrouter.ai/api/v1` |
| Name | `Claude` |
| Model | `anthropic/claude-opus-4-6` |
| Control Home Assistant | **OFF** |
| System prompt | `You are a thoughtful home assistant. Provide reasoned, well-explained answers. Reply concisely.` |

Cost note: Claude Opus is the priciest model — only use when you actually want its reasoning. Gemini Flash handles 99% of calls.

---

## 5. Verify all four agents exist

Open HA's Assist sidebar (chat bubble icon, top right). The agent dropdown should now show:

- Home Assistant (default rule-based)
- **Local Chat**
- **Local Control**
- **Gemini**
- **Claude**

### Smoke tests

| Agent | Prompt | Expected |
|---|---|---|
| Local Chat | `Reply with PONG only` | `PONG` |
| Local Control | `Turn on the kitchen light` | Light toggles on |
| Gemini | `What's the capital of France?` | `Paris` |
| Claude | `What's a fun fact about octopuses?` | Free-form answer |

---

## 6. Then ping me

Once all four are added and the smoke tests pass, let me know — I'll grep `/config/.storage/core.config_entries` on the Pi for the actual `agent_id` slugs and finalize `automations/proactive.yaml`. Until then the automation file has placeholder agent_ids that won't resolve.
