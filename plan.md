# Local-First Home Assistant Brain — Gemma 3 (tools fine-tune) on Pi 5

## Context

Goal: make Home Assistant intelligent and proactive without depending on the internet. Smart-home automation must keep working when the WAN is down, with optional cloud "smarter" mode when reach is available.

Why these choices (locked from clarification round):
- **Gemma 4 won't fit on the Pi** — smallest variant (`gemma4:e2b`, 7.2 GB on disk / similar runtime RAM) exceeds the Pi 5's 6 GB usable RAM. Skipping Gemma 4.
- **Local brain = `orieg/gemma3-tools:4b-ft`** (2.5 GB) — Gemma 3 4B QLoRA fine-tuned for `<tool_call>` XML tags, active community model (updated ~3 weeks ago). Base `gemma3:4b` does **not** declare `tools` capability in its Ollama manifest, so HA's "Control Home Assistant" toggle won't enable on it; this fine-tune does. Reliability on Pi-scale entity counts (~25 exposed) realistically 70-85% — author warns of tool-call over-firing bias.
- **Documented contingency**: if real-use misfire rate >15% (tools fired when shouldn't, or wrong tool picked), swap model to `qwen2.5:7b` in the HA UI. One-field change. ~5 GB, slower but tool-calling much more reliable. Don't pre-optimize; measure first.
- **Voice = existing Alexa Echos** (no new hardware). Trade-offs documented in §6.
- **Cloud fallback = both** Gemini (default) + Claude via OpenRouter (on-demand).
- **Proactivity = event-triggered LLM narration** through Alexa announcements.

Outcome when done:
- Pi runs the local brain. Internet outage → automations + LLM responses still fire.
- Echos announce contextual, LLM-generated narration on real-world events.
- HA's Assist text input + mobile app can ask the local LLM anything; cloud agents picked explicitly when more reasoning is wanted.

## Architecture

```
                    ┌──────────────────────────────────────┐
                    │ Pi 5 (always-on, aarch64, 8 GB RAM) │
                    │                                      │
   Echo announce ←──┤  Home Assistant (Docker)            │
   (Amazon cloud)   │   ├─ Ollama × 2 (chat + control)   │← local brain
                    │   ├─ Google Gemini integration     │← cloud (default)
                    │   ├─ OpenAI integration (Claude    │← cloud (on-demand)
                    │   │   via OpenRouter base URL)     │
                    │   └─ automations.yaml              │
                    │                                      │
                    │  Ollama 0.21.2 (host)              │
                    │   └─ orieg/gemma3-tools:4b-ft       │
                    │      (2.5 GB, tool-calling enabled) │
                    └──────────────────────────────────────┘
```

## Phase 1 — Pi cleanup + Ollama upgrade

Critical files:
- `/etc/systemd/system/ollama.service` (or `/etc/systemd/system/ollama.service.d/override.conf`) on Pi
- `~/.ollama/models/` on Pi

Steps:
1. **Delete unused model on Pi**: `ssh pi-lan "ollama rm qwen2.5:1.5b"` — frees 986 MB. Confirms ShiftLogic no longer needs Pi-resident models.
2. **Investigate disk pressure** (Pi root at 96%, 82 GB free): `ssh pi-lan "sudo du -h -d 1 / 2>/dev/null | sort -rh | head -20"` to identify what's filling 1.7 TB. Not blocking install, but worth flagging — most likely culprit is HA's recorder DB (`/config/home-assistant_v2.db*`) which grows unbounded by default; tunable via the `recorder:` integration's `purge_keep_days` (default 10). Other candidates: `/var/lib/docker`, camera recordings.
3. **Upgrade Ollama on Pi** to v0.21.2: `ssh pi-lan "curl -fsSL https://ollama.com/install.sh | sh"`. The installer handles systemd cleanly on aarch64 Linux and preserves models. Verify: `ssh pi-lan "ollama --version"` → expect `0.21.2`.
4. **Bind Ollama to LAN** so HA's Docker container can reach it. HA runs in a Docker container; `localhost:11434` from inside the container would not hit the host's Ollama. Add systemd override on Pi:
   ```
   /etc/systemd/system/ollama.service.d/override.conf:
   [Service]
   Environment="OLLAMA_HOST=0.0.0.0:11434"
   ```
   Then `sudo systemctl daemon-reload && sudo systemctl restart ollama`.

   **Security note**: `0.0.0.0` exposes Ollama to anyone on `192.168.0.0/24`. Per project topology this is the trusted LAN (eero Max 7 + Bell Hub DMZ), so this is acceptable. If LAN trust ever changes (guest network bridge, IoT VLAN spillover), bind to the Pi's specific LAN IP (`OLLAMA_HOST=192.168.0.X:11434`) or add an iptables rule limiting tcp/11434 to the HA container's bridge IP.

5. **Pull the brain**: `ssh pi-lan "ollama pull orieg/gemma3-tools:4b-ft"` (~2.5 GB download).
6. **Verify tools capability**: `ssh pi-lan "ollama show orieg/gemma3-tools:4b-ft | head -40"` — confirm `Capabilities` block lists `tools`. If absent, the HA "Control Home Assistant" toggle will refuse to enable; abort and fall back to `qwen2.5:7b` (`ollama pull qwen2.5:7b`).
7. **Smoke-test inference**:
   ```
   ssh pi-lan 'curl -s http://localhost:11434/api/chat -d "{\"model\":\"orieg/gemma3-tools:4b-ft\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply only with the word PONG\"}],\"stream\":false}"'
   ```
   Expect `"PONG"` in the response. First call cold-loads the model (~10-15 s on Pi 5).

## Phase 2 — Mac is **not** modified

- Mac stays pinned at Ollama **0.20.3** per `CLAUDE.md` (0.20.7+ break Metal for ShiftLogic).
- Mac model cleanup is **deferred** — user did not confirm which of the 5 Mac-side models (`qwen2.5:14b`, `llama3.2-vision`, `qwen3.5:latest`, `qwen2.5:3b`, `gemma4:latest`) are unused. Surface the question separately after this work lands; don't touch Mac models in this plan.

## Phase 3 — Wire HA to the local brain (Ollama)

HA UI: **Settings → Devices & Services → Add Integration → Ollama**.

Use the dual-config pattern (per HA docs §Controlling Home Assistant — small models are unreliable when chatting *and* tool-calling on the same agent):

**Integration A — "Local Chat"** (no HA control):
- URL: `http://<pi-lan-ip>:11434` (use the Pi's LAN IP — `192.168.0.X` — from inside the HA container; `localhost` won't work)
- Model: `orieg/gemma3-tools:4b-ft`
- Control Home Assistant: **off**
- System prompt: short conversational identity ("You are the home's local assistant. Be terse.").

**Integration B — "Local Control"** (HA tool-calling on):
- Same URL + model.
- Control Home Assistant: **on**
- Expose **fewer than 25 entities** via Settings → Voice assistants → Expose. Pick the most-used: a few lights, thermostats, locks, the front door sensor. Do not expose every entity — the model's accuracy degrades fast past ~25, and the author's own data shows steeper degradation past 22 tools.
- System prompt: "You are a smart home controller. Only call a tool if the user explicitly asks to change a device or query its state. For conversational questions, reply with one short sentence and do NOT call tools." — explicit anti-over-fire prompting because the fine-tune biases toward emitting `<tool_call>` even on chat.

Acceptance check: in HA Assist (sidebar chat), pick "Local Control", say "Turn on the kitchen light" → light toggles. Pick "Local Chat", ask "Why is the sky blue?" → free-text answer (no tool calls).

**Misfire-rate contingency** (per locked decision): track for first ~50 real interactions. If >15% misfire rate (tool fired when not asked, or wrong tool picked), swap *Integration B* model field to `qwen2.5:7b` (4.7 GB — pull it preemptively to avoid downtime: `ssh pi-lan "ollama pull qwen2.5:7b"`). Keep *Integration A* on Gemma for narration if you like its voice.

## Phase 4 — Cloud fallbacks (smarter on demand)

**Gemini (default cloud)**:
- HA UI: Add Integration → **Google Generative AI**.
- API key: read from `~/.zshenv` (`GEMINI_API_KEY`).
- Model: `gemini-2.5-flash` (fast/cheap default) — `gemini-2.5-pro` available for harder questions.
- Control Home Assistant: **on** — Gemini's tool-calling is solid. Same exposed-entities set as Integration B.

**Claude via OpenRouter (on-demand)**:
- HA UI: Add Integration → **OpenAI Conversation** (built-in supports custom base URL).
- Base URL: `https://openrouter.ai/api/v1`
- API key: `OPENROUTER_API_KEY` from `~/.zshenv`.
- Model: `anthropic/claude-opus-4-6` (or whatever you prefer at runtime).
- Control Home Assistant: **off** — keep Claude as a "ask me hard questions" agent, not a controller. Reduces blast radius and cost.

Acceptance check: HA Assist agent picker shows four agents — Local Chat, Local Control, Gemini, Claude (OpenRouter). User can pick any per-conversation.

## Phase 5 — Default Assist pipeline + offline routing

- Update HA's default Assist pipeline (`/config/.storage/assist_pipeline.pipelines` is currently a single default pipeline) via UI: **Settings → Voice assistants → Add assistant**:
  - "Local-first": Conversation = *Local Control*, TTS = `tts.cloud` (current Nabu Casa) → fallback OK while online.
  - "Smart": Conversation = *Gemini*, TTS = `tts.cloud`.
- The local pipeline keeps working with no internet (TTS will fall back to a local Piper engine if added later — out of scope for this plan).

## Phase 6 — Voice via Alexa (with caveats)

What works **today**:
- **Outbound TTS** — `notify.alexa_media` with `{type: announce}` pushes LLM-generated narration to Echos. Used in Phase 7 automations.
- **Basic entity control via Alexa NLP** — already works through `alexa_media` / Nabu Casa Alexa skill. Bypasses our local LLM (Amazon's NLP handles intent) but works offline-from-HA-side.

What does **not** work without more setup:
- **"Alexa, ask Home Assistant ..."** routed to the local LLM — requires a custom Alexa skill backed by an HA conversation endpoint (Nabu Casa Cloud has this; self-hosted needs Lambda or a public HA URL).

Decision for this plan: **don't build the custom skill yet**. Document it as a future upgrade. If later you want true LLM-via-voice on Echos, the path is Nabu Casa → Alexa skill → routes to `conversation.process` with the *Local Control* agent.

## Phase 7 — Proactive automations (event-triggered LLM narration)

Add to `/config/automations.yaml` on Pi. Three concrete examples covering the major proactivity patterns. The pattern is: trigger → ask LLM via `conversation.process` for a one-sentence message → push to Echo.

```yaml
# 1. Door left open
- alias: "Proactive: front door left open"
  trigger:
    - platform: state
      entity_id: binary_sensor.front_door
      to: "on"
      for: "00:05:00"
  action:
    - service: conversation.process
      data:
        agent_id: conversation.local_chat   # narration only — no tool calls needed
        text: >
          The front door has been open for 5 minutes. Compose a one-sentence,
          friendly reminder to close it. Mention the current outdoor temp
          ({{ states('sensor.outdoor_temperature') }}°C) only if it is below 5
          or above 30.
      response_variable: agent
    - service: notify.alexa_media
      data:
        target:
          - media_player.kitchen_echo
        message: "{{ agent.response.speech.plain.speech }}"
        data:
          type: announce

# 2. Welcome home (presence-triggered greeting)
#    Debounce: `for: 00:01:00` swallows brief Wi-Fi/GPS flaps that would re-trigger.
#    Cooldown: don't greet twice within 30 min (e.g., dog walk).
- alias: "Proactive: welcome home"
  trigger:
    - platform: state
      entity_id: person.arshad
      to: "home"
      for: "00:01:00"
  condition:
    - condition: time
      after: "06:00:00"
      before: "23:00:00"
    - condition: template
      value_template: >
        {{ (now() - states.automation.proactive_welcome_home.attributes.last_triggered | default(now() - timedelta(hours=1))).total_seconds() > 1800 }}
  action:
    - service: conversation.process
      data:
        agent_id: conversation.local_chat   # narration only
        text: >
          Arshad just got home. Compose a one-sentence greeting using the
          weather ({{ states('weather.home') }}, {{ state_attr('weather.home','temperature') }}°C)
          and the next calendar event ({{ states('calendar.arshad') }}).
      response_variable: agent
    - service: notify.alexa_media
      data:
        target: [media_player.living_room_echo]
        message: "{{ agent.response.speech.plain.speech }}"
        data: {type: announce}

# 3. Anomaly narration (locks left unlocked at night)
#    Pre-compute unlocked list in Jinja; only call the LLM if there's something
#    to announce. Saves a model call most nights and avoids passing raw Python
#    list-as-string into the prompt.
- alias: "Proactive: nightly lock check"
  trigger:
    - platform: time
      at: "23:30:00"
  variables:
    unlocked: >
      {{ states.lock
         | selectattr('state', 'eq', 'unlocked')
         | map(attribute='attributes.friendly_name')
         | list
         | join(', ') }}
  condition:
    - condition: template
      value_template: "{{ unlocked != '' }}"
  action:
    - service: conversation.process
      data:
        agent_id: conversation.local_chat   # narration only — no tool calls needed
        text: >
          Compose a one-sentence, calm bedtime reminder that these locks are
          still unlocked: {{ unlocked }}.
      response_variable: agent
    - service: notify.alexa_media
      data:
        target: [media_player.bedroom_echo]
        message: "{{ agent.response.speech.plain.speech }}"
        data: {type: announce}
```

Quiet hours: HA's `notify.alexa_media` honors Alexa "Do Not Disturb" set per-device — configure in the Alexa app, not HA. Document this for the user.

The exact `media_player.*_echo` entity IDs and `calendar.arshad`/`person.arshad` IDs need to be matched to actuals — list them with `ssh pi-lan "docker exec homeassistant grep -hE 'entity_id|name' /config/.storage/core.entity_registry 2>/dev/null | grep -iE 'echo|arshad' | head"` before pasting in.

## Phase 8 — Verification (end-to-end)

Run after Phase 7 lands, before declaring done:

1. **Local brain reachable from HA**: Developer Tools → Services → `conversation.process` → `agent_id: conversation.local_chat`, text: "Reply with PONG". Expect "PONG".
2. **Tool calling works**: same service, `agent_id: conversation.local_control`, text: "Turn on the kitchen light." Verify the light turns on and response confirms.
3. **Cloud agents reachable**: repeat (1) for Gemini and Claude/OpenRouter agents.
4. **Offline resilience test**: pull Pi's WAN cable (or block egress at the router for 5 min). Confirm:
   - HA Assist still works on Local Chat + Local Control.
   - An automation with a local trigger still fires.
   - Gemini agent fails gracefully (expected).
   - Echos can no longer be reached (expected — Amazon-mediated).
5. **Proactive automation fires**: open the front door for >5 min. Echo should announce a unique LLM-composed sentence (not a hard-coded one).
6. **Latency check**: first cold call to `orieg/gemma3-tools:4b-ft` ~10-15s; warm call <2s. If consistently >5s warm, either reduce context window via Ollama options or swap to `qwen2.5:7b`.
7. **Misfire-rate check** (run after a week of real use): grep HA logs for `conversation.process` calls and tally tool-call vs free-text responses against intent. If misfires >15%, execute the documented contingency (swap *Integration B* model field to `qwen2.5:7b`).

## Out of scope (call out, don't build)

- **Custom Alexa skill for LLM-by-voice** — see Phase 6 caveat. Documented; not built.
- **Local Wyoming voice satellite (HA Voice PE / ESP32-S3 BOX)** — user opted to use Echos; revisit if Echo limitations bite.
- **Local STT/TTS (Whisper, Piper, openWakeWord)** — only useful with a Wyoming satellite. Defer.
- **Mac model cleanup (35 GB across 5 models)** — surface as a separate decision after this plan lands.
- **AI Task scheduled prompts** — user opted for event-triggered only. Easy to add later if desired.
- **Pi disk pressure (96% full)** — flagged for follow-up. Probably HA database / Docker images. Don't conflate with this work.

## Files modified

- Pi: `/etc/systemd/system/ollama.service.d/override.conf` (new) — `OLLAMA_HOST=0.0.0.0:11434`
- Pi (HA container): `/config/automations.yaml` — three proactive automations
- Pi (HA UI, persisted to `.storage`): four conversation integrations (Ollama×2, Gemini, OpenAI/OpenRouter), updated Assist pipelines, exposed-entities list

No files in this repo (`ShiftLogic_HQ`) need changes. `CLAUDE.md` may want a one-line note added under "Raspberry Pi 5" once verified — defer until working.
