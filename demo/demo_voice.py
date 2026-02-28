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

from dotenv import load_dotenv
from livekit import api, rtc
from livekit.agents import AgentSession
from livekit.plugins import elevenlabs, openai

from dashboard import Dashboard
from demo.caller import CallerAgent
from steerio import SteeredAgent
from steerio.store import SupabaseStore

load_dotenv(Path(__file__).parent / ".env")

ROOM_NAME = "steerio-demo"

# DECISION: Policy ID for the medical triage policy seeded in Supabase.
# In production, this would come from a config file or environment variable.
POLICY_ID = os.environ.get("STEERIO_POLICY_ID", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

AGENT_INSTRUCTIONS = """\
You are a medical triage assistant. Help callers assess their symptoms and
determine the appropriate level of care: self-care at home, urgent care visit,
or emergency room / call 911.

Rules:
- Ask clarifying questions about symptoms, duration, and severity.
- Never diagnose specific conditions.
- Never prescribe medications or dosages.
- Never recommend specific treatments or procedures.
- Always recommend professional medical consultation for anything beyond mild symptoms.
- If symptoms suggest a life-threatening emergency, immediately tell them to call 911.

If you are unsure about something or need to verify critical medical information,
use the request_guidance tool to ask the supervising operator for help.
"""


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


async def main():
    print("Starting Steerio voice demo...")
    print()

    # --- Load policy from Supabase ---
    store = SupabaseStore(
        url=os.environ["SUPABASE_URL"],
        key=os.environ["SUPABASE_ANON_KEY"],
    )
    policy = store.load_policy(POLICY_ID)
    print(f"Policy loaded from Supabase: {policy.name}")
    print(f"  Domain: {policy.domain}")
    print(f"  Rules: {len(policy.rules)}")
    print(f"  Escalation: {policy.escalation}")
    print()

    livekit_url = os.environ["LIVEKIT_URL"]

    # --- Dashboard (operator UI) ---
    dashboard = Dashboard(port=8766)

    # --- Medical Agent (SteeredAgent) ---
    medical_room = rtc.Room()
    medical_token = _generate_token("medical-agent", ROOM_NAME)
    await medical_room.connect(livekit_url, medical_token)

    medical_agent = SteeredAgent(
        instructions=AGENT_INSTRUCTIONS,
        judge_llm=_get_llm(model="google/gemini-3.1-pro-preview"),
        policy=policy,
        store=store,
        policy_id=POLICY_ID,
        mode="llm",
        monitor_port=8765,
        dashboard=dashboard,
        recording_path="recordings/voice_session.jsonl",
        audit_path="audit/voice_session.jsonl",
    )

    medical_session = AgentSession(
        stt=elevenlabs.STT(),
        llm=_get_llm(model="google/gemini-2.5-flash"),
        tts=elevenlabs.TTS(),
    )

    # --- AI Caller (Patient) ---
    caller_room = rtc.Room()
    caller_token = _generate_token("patient", ROOM_NAME)
    await caller_room.connect(livekit_url, caller_token)

    caller_agent = CallerAgent(max_turns=8)

    caller_session = AgentSession(
        stt=elevenlabs.STT(),
        llm=_get_llm(model="google/gemini-2.5-flash"),
        tts=elevenlabs.TTS(),
    )

    # Start both agents in the same room
    print("Dashboard: http://localhost:8766")
    print("Monitor:   ws://localhost:8765")
    print()
    print("Starting medical agent...")
    await medical_session.start(agent=medical_agent, room=medical_room)

    await asyncio.sleep(2)

    print("Starting AI caller (patient)...")
    await caller_session.start(agent=caller_agent, room=caller_room)

    print("Demo running! Watch the dashboard at http://localhost:8766")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping demo...")
    finally:
        await medical_room.disconnect()
        await caller_room.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
