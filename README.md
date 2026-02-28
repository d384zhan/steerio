# Steerio

Real-time steering SDK for voice AI agents. Evaluates every response with an LLM judge, auto-corrects unsafe output mid-call, and gives human operators live control.

## Quick Start

```sh
git clone <repo>
cd steerio
uv sync --extra demo --extra supabase
```

### Supabase

Run these in the Supabase SQL editor:

1. `steerio/store/schema.sql`
2. `steerio/store/seed.sql`

### SIP Trunk

Pick a provider (Telnyx or Twilio), buy a phone number, create a SIP trunk with credential auth.

- **Option A:** Pre-configure on [LiveKit Cloud console](https://cloud.livekit.io) → set `LIVEKIT_SIP_TRUNK_ID`
- **Option B:** Let the demo auto-create from carrier credentials (see env vars below)

### Configure `demo/.env`

```sh
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key

OPENROUTER_API_KEY=your-openrouter-key
ELEVEN_API_KEY=your-elevenlabs-key

LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-api-secret

# SIP — Option A
LIVEKIT_SIP_TRUNK_ID=ST_xxxxxxxxxxxx

# SIP — Option B
SIP_HOSTNAME=sip.telnyx.com
SIP_USERNAME=
SIP_PASSWORD=
SIP_PHONE_NUMBER=+15105550100
```

### Run

```sh
uv run python -m demo.demo
```

Open http://localhost:8766, enter a phone number, select a domain, click Dial.

## How It Works

Wrap any LiveKit voice agent with `SteeredAgent`:

1. **Agent speaks** — response streams to caller via TTS
2. **Judge evaluates** — a separate LLM evaluates the response in parallel against the domain policy
3. **Verdict** — `CONTINUE` (safe), `MODIFY` (tweak next turn), `BLOCK` (interrupt + speak correction), `ESCALATE` (block + escalate)
4. **Auto-correct** — on BLOCK, the agent is interrupted mid-speech and the judge's correction is spoken directly to the caller
5. **Escalation** — 3 consecutive blocks auto-terminates the call with a transfer message

## Two Modes

| | LLM Mode | Human Mode |
|---|---|---|
| **Who corrects** | Judge LLM (automatic) | Human operator (manual) |
| **How** | Judge evaluates every turn, blocks and corrects unsafe responses | Agent calls `request_guidance`, operator responds via mic |
| **Operator controls** | Disabled — judge handles everything | Inject (instruct agent) + Speak (mic to caller) |

## Architecture

```
Operator Dashboard (browser)
        │ WebSocket
        ▼
  demo/demo.py (orchestrator, SIP dialing)
        │
  steerio SDK
  ├── SteeredAgent ──► Voice AI (OpenRouter)
  │   └── Judge ──► Safety LLM (Gemini)
  │       └── Verdict → CONTINUE / MODIFY / BLOCK / ESCALATE
  └── Policy Store ──► Supabase (policies, judge prompts, audit)
        │
  LiveKit Cloud (WebRTC room)
        │ SIP
  Phone (PSTN) — real caller
```

The SDK is domain-agnostic. The demo ships with three domains (healthcare, finance, e-commerce) but any policy can be loaded from Supabase.
