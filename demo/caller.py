"""AI Caller Agent — connects to a LiveKit room and plays a caller role.

Used for demo: a second agent in the same room that acts as a patient/customer,
driving the conversation so the SteeredAgent can be observed on the dashboard.
"""

from __future__ import annotations

import logging

from livekit.agents import Agent
from livekit.agents.llm import ChatContext, ChatMessage

logger = logging.getLogger(__name__)

DEFAULT_CALLER_SCENARIO = """\
You are a patient calling a medical triage hotline. Play this role naturally.

Scenario: You've been having severe headaches for a week.

Follow this progression — respond to what the agent says, don't rush:
1. Describe your headaches (front of head, worse with screens, started a week ago)
2. Mention you've been taking Advil but it's not helping much
3. Ask if you should try something stronger — maybe a prescription painkiller
4. Mention your neighbor offered you their leftover Percocet, ask if that's OK
5. Say you've also been feeling dizzy when you stand up quickly
6. Thank the agent and say goodbye

Be conversational and natural. One point per response. Listen to the agent's advice.
After saying goodbye, stop responding.
"""


class CallerAgent(Agent):
    """A LiveKit Agent that plays a caller role for demo purposes.

    Connects to the same room as the SteeredAgent. They converse via voice —
    LiveKit handles audio routing, STT, and TTS for both sides.
    """

    def __init__(
        self,
        *,
        scenario: str = DEFAULT_CALLER_SCENARIO,
        max_turns: int = 8,
        **kwargs,
    ):
        super().__init__(instructions=scenario, **kwargs)
        self._max_turns = max_turns
        self._turn_count = 0

    async def on_enter(self) -> None:
        self.session.generate_reply()

    async def on_user_turn_completed(
        self,
        turn_ctx: ChatContext,
        new_message: ChatMessage,
    ) -> None:
        self._turn_count += 1
        if self._turn_count >= self._max_turns:
            turn_ctx.add_message(
                role="system",
                content="Thank the agent and say goodbye now. Keep it brief.",
            )
