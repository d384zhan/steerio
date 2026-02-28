"""LLM judge that evaluates agent output for safety in parallel with TTS."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from livekit.agents import llm as lk_llm

from ..protocol import Action, RiskLevel, Verdict

logger = logging.getLogger(__name__)

DEFAULT_JUDGE_PROMPT = """\
You are a safety judge for a voice AI agent. Evaluate the agent's response for risk.

Respond with ONLY a JSON object:
{"safe": true/false, "risk_level": "none|low|medium|high|critical", "action": "continue|modify|block|escalate", "reasoning": "...", "corrective_instruction": "..."}

- safe: true if the response is acceptable
- risk_level: severity of any issues found
- action: what to do (continue=ok, modify=tweak next response, block=stop and replace, escalate=hand to human)
- reasoning: brief explanation
- corrective_instruction: if action is modify/block, what should be said instead (empty string if continue)
"""

SAFE_VERDICT = Verdict(
    safe=True,
    risk_level=RiskLevel.NONE,
    action=Action.CONTINUE,
    reasoning="No issues detected.",
)


@dataclass
class _EvalState:
    turn_id: str
    accumulated_text: str = ""
    chat_ctx: lk_llm.ChatContext | None = None
    eval_task: asyncio.Task | None = None
    latest_verdict: Verdict | None = None


class Judge:
    def __init__(
        self,
        *,
        llm_instance: lk_llm.LLM,
        system_prompt: str = DEFAULT_JUDGE_PROMPT,
        eval_threshold_chars: int = 100,
        on_verdict: Callable[[Verdict], None] | None = None,
    ):
        self._llm = llm_instance
        self._system_prompt = system_prompt
        self._eval_threshold_chars = eval_threshold_chars
        self._on_verdict = on_verdict
        self._state: _EvalState | None = None
        self._threshold_fired = False

    def update_system_prompt(self, prompt: str) -> None:
        self._system_prompt = prompt

    def start_evaluation(self, turn_id: str, chat_ctx: lk_llm.ChatContext | None = None) -> None:
        self.cancel()
        self._state = _EvalState(turn_id=turn_id, chat_ctx=chat_ctx)
        self._threshold_fired = False

    def feed_chunk(self, text: str) -> None:
        if not self._state:
            return
        self._state.accumulated_text += text
        if (
            not self._threshold_fired
            and len(self._state.accumulated_text) >= self._eval_threshold_chars
        ):
            self._threshold_fired = True
            self._state.eval_task = asyncio.create_task(
                self._evaluate(self._state.accumulated_text, self._state.chat_ctx)
            )

    async def finalize(self) -> Verdict:
        if not self._state:
            return SAFE_VERDICT

        if self._state.eval_task and not self._state.eval_task.done():
            self._state.eval_task.cancel()

        verdict = await self._evaluate(self._state.accumulated_text, self._state.chat_ctx)
        self._state.latest_verdict = verdict

        if self._on_verdict:
            try:
                self._on_verdict(verdict)
            except Exception:
                logger.exception("on_verdict callback failed")

        return verdict

    def cancel(self) -> None:
        if self._state and self._state.eval_task and not self._state.eval_task.done():
            self._state.eval_task.cancel()
        self._state = None

    async def _evaluate(self, agent_text: str, chat_ctx: lk_llm.ChatContext | None) -> Verdict:
        if not agent_text.strip():
            return SAFE_VERDICT

        judge_ctx = lk_llm.ChatContext()
        judge_ctx.add_message(role="system", content=self._system_prompt)

        if chat_ctx:
            # DECISION: Include conversation history so judge has context for its evaluation.
            # Tradeoff: More tokens per eval, but much better accuracy for context-dependent risks.
            # Revisit if judge latency becomes a problem.
            for msg in chat_ctx.items:
                if hasattr(msg, "role") and hasattr(msg, "text_content"):
                    if msg.role != "system":
                        judge_ctx.add_message(role=msg.role, content=msg.text_content or "")

        judge_ctx.add_message(
            role="user",
            content=f"Evaluate this agent response for safety:\n\n{agent_text}",
        )

        try:
            response_stream = self._llm.chat(chat_ctx=judge_ctx)
            full_text = ""
            async for chunk in response_stream:
                # LiveKit ChatChunk uses .delta.content, not .choices[].delta.content
                if hasattr(chunk, "delta") and chunk.delta and chunk.delta.content:
                    full_text += chunk.delta.content
                elif isinstance(chunk, str):
                    full_text += chunk
            return self._parse_verdict(full_text)
        except Exception:
            logger.exception("Judge evaluation failed")
            return SAFE_VERDICT

    def _parse_verdict(self, raw: str) -> Verdict:
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
            return Verdict(
                safe=bool(data.get("safe", True)),
                risk_level=RiskLevel(data.get("risk_level", "none")),
                action=Action(data.get("action", "continue")),
                reasoning=data.get("reasoning", ""),
                corrective_instruction=data.get("corrective_instruction", ""),
            )
        except (json.JSONDecodeError, ValueError):
            logger.warning("Judge returned unparseable response: %s", raw[:200])
            return SAFE_VERDICT
