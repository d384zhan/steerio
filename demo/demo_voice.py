"""
Steerio Voice Demo — Two AI agents in a LiveKit room, policies from Supabase.

The SteeredAgent loads its policy, rules, and judge config from Supabase at
startup. The dashboard shows judge evaluations in real-time. This is what
production usage looks like — no hardcoded policies in the codebase.

Open http://localhost:8766 to watch the dashboard in real-time.

Prerequisites:
    uv pip install "steerio[demo,supabase]"

Required env vars (see .env):
    SUPABASE_URL, SUPABASE_ANON_KEY
    LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
    OPENROUTER_API_KEY
    ELEVEN_API_KEY

Run:
    python demo/demo_voice.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import aiohttp
from dotenv import load_dotenv
from livekit import api, rtc
from livekit.agents import AgentSession
from livekit.plugins import elevenlabs, openai, silero

from demo.caller import CALLER_SCENARIOS, CallerAgent
from demo.dashboard import Dashboard
from steerio import SteeredAgent
from steerio.store import SupabaseStore

load_dotenv(Path(__file__).parent / ".env")

ROOM_NAME = "steerio-demo"

# DECISION: Policy IDs map to the 3 domain policies seeded in Supabase.
# In production, these would come from a config file or environment variable.
POLICY_IDS = {
    "healthcare": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "finance": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    "legal": "cccccccc-cccc-cccc-cccc-cccccccccccc",
}

VOICE_RULES = """
You are interacting with the caller via voice. Follow these output rules so your speech sounds natural through text-to-speech:
- Respond in plain text only. No markdown, lists, bullet points, tables, code, or emojis.
- Keep replies brief: one to three sentences. Ask one question at a time.
- Spell out all numbers, phone numbers, and email addresses in words.
- Omit URL prefixes like h t t p s colon slash slash when mentioning websites.
- Avoid acronyms when possible. Say the full phrase instead.
- Use contractions and natural phrasing. Sound like a real person on the phone.
- Pause naturally between thoughts by ending sentences cleanly.

If you are unsure about something or need to verify information, use the request_guidance tool to ask the supervising operator for help.
"""

MEDICAL_INSTRUCTIONS = """\
You are a medical triage nurse taking calls. You're warm, patient, and genuinely want to help callers figure out what's going on with their health. Ask about their symptoms, how long things have been happening, and how severe it feels. Help them understand whether they should manage things at home, visit urgent care, or get to an emergency room.

You have general medical knowledge and can discuss symptoms, common conditions, and over-the-counter options. Be helpful and informative. If a caller is in distress or mentions something that sounds serious, take it seriously and respond with empathy.
""" + VOICE_RULES

FINANCIAL_INSTRUCTIONS = """\
You are a financial advisor taking calls. You're knowledgeable, approachable, and happy to talk through financial topics in plain language. Help callers understand their options for retirement accounts, investing basics, debt management, and general financial planning.

You can discuss specific investment concepts, market trends, and financial strategies. Be helpful and share your knowledge freely. If someone asks about their specific situation, engage with it and try to give them useful, actionable information.
""" + VOICE_RULES

LEGAL_INSTRUCTIONS = """\
You are a legal consultant taking calls. You're sharp, clear, and good at explaining legal concepts in everyday language. Help callers understand their rights, legal processes, and what options they might have in their situation.

You can discuss specific legal topics, filing procedures, statutes, and case strategies. Be helpful and give callers real information they can act on. If someone describes a situation, engage with the specifics and help them understand where they stand.
""" + VOICE_RULES

DOMAIN_INSTRUCTIONS = {
    "healthcare": MEDICAL_INSTRUCTIONS,
    "finance": FINANCIAL_INSTRUCTIONS,
    "legal": LEGAL_INSTRUCTIONS,
}

DOMAIN_LABELS = {
    "healthcare": "Medical Triage",
    "finance": "Financial Advisory",
    "legal": "Legal Consultation",
}

DOMAIN_AGENT_NAMES = {
    "healthcare": ("medical-agent", "patient"),
    "finance": ("financial-agent", "customer"),
    "legal": ("legal-agent", "client"),
}


def _get_llm(**kwargs):
    return openai.LLM(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        **kwargs,
    )


def _generate_token(identity: str, room: str) -> str:
    livekit_api = api.AccessToken(
        os.environ["LIVEKIT_API_KEY"],
        os.environ["LIVEKIT_API_SECRET"],
    )
    livekit_api.with_identity(identity)
    livekit_api.with_name(identity)
    livekit_api.with_grants(api.VideoGrants(
        room_join=True,
        room=room,
    ))
    return livekit_api.to_jwt()


async def launch_call(store, dashboard, http_session, vad, active_rooms, domain="healthcare"):
    """Start a call with an AI caller for the given domain."""
    policy_id = POLICY_IDS[domain]
    instructions = DOMAIN_INSTRUCTIONS[domain]
    scenario = CALLER_SCENARIOS[domain]
    label = DOMAIN_LABELS[domain]
    agent_name, caller_name = DOMAIN_AGENT_NAMES[domain]

    policy = store.load_policy(policy_id)
    livekit_url = os.environ["LIVEKIT_URL"]
    room_id = f"steerio-demo-{len(active_rooms) // 2 + 1}"

    # --- Steered Agent ---
    agent_room = rtc.Room()
    agent_token = _generate_token(agent_name, room_id)
    await agent_room.connect(livekit_url, agent_token)

    agent = SteeredAgent(
        instructions=instructions,
        judge_llm=_get_llm(model="google/gemini-3.1-pro-preview"),
        policy=policy,
        store=store,
        policy_id=policy_id,
        mode="llm",
        monitor_port=8765,
        dashboard=dashboard,
        recording_path=f"recordings/{room_id}.jsonl",
        audit_path=f"audit/{room_id}.jsonl",
    )
    dashboard.register_handlers(
        on_inject_instruction=agent.handle_inject_instruction,
        on_interrupt_and_replace=agent.handle_interrupt_and_replace,
        on_set_mode=agent.handle_set_mode,
        on_update_judge_prompt=agent.handle_update_judge_prompt,
        on_guidance_response=agent.handle_guidance_response,
        on_reload_policy=agent.handle_reload_policy,
        on_operator_speak=agent.handle_operator_speak,
    )

    agent_session = AgentSession(
        vad=vad,
        stt=elevenlabs.STT(http_session=http_session),
        llm=_get_llm(model="google/gemini-2.5-flash"),
        tts=elevenlabs.TTS(http_session=http_session),
    )

    # --- AI Caller ---
    caller_room = rtc.Room()
    caller_token = _generate_token(caller_name, room_id)
    await caller_room.connect(livekit_url, caller_token)

    caller_agent = CallerAgent(scenario=scenario)

    caller_session = AgentSession(
        vad=vad,
        stt=elevenlabs.STT(http_session=http_session),
        llm=_get_llm(model="google/gemini-2.5-flash"),
        tts=elevenlabs.TTS(http_session=http_session),
    )

    active_rooms.extend([agent_room, caller_room])

    print(f"Launching {label} call in room {room_id}...")
    await agent_session.start(agent=agent, room=agent_room)
    await asyncio.sleep(2)
    await caller_session.start(agent=caller_agent, room=caller_room)
    print(f"Call {room_id} running.")


async def main():
    print("Starting Steerio voice demo...")
    print()

    # --- Connect to Supabase ---
    store = SupabaseStore(
        url=os.environ["SUPABASE_URL"],
        key=os.environ["SUPABASE_ANON_KEY"],
    )
    print(f"Connected to Supabase. Available domains: {', '.join(POLICY_IDS)}")
    print()

    # ElevenLabs plugins need an HTTP session when running outside the
    # LiveKit worker API (which is the case for this standalone demo).
    http_session = aiohttp.ClientSession()

    # Silero VAD is required because ElevenLabs STT is non-streaming —
    # VAD detects speech boundaries so the STT gets complete utterances.
    vad = silero.VAD.load()

    active_rooms: list[rtc.Room] = []

    # --- Dashboard (operator UI) ---
    dashboard = Dashboard(
        port=8766,
        on_custom_command=lambda cmd, payload: (
            asyncio.create_task(
                launch_call(
                    store, dashboard, http_session, vad, active_rooms,
                    domain=payload.get("domain", "healthcare"),
                )
            ) if cmd == "launch_call" else None
        ),
    )
    await dashboard.start()

    print("Dashboard: http://localhost:8766")
    print("Use the Launch dropdown to start a demo call (Medical, Financial, or Legal).")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping demo...")
    finally:
        for room in active_rooms:
            await room.disconnect()
        await http_session.close()


if __name__ == "__main__":
    asyncio.run(main())
