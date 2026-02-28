"""Multi-judge pipeline — run multiple safety evaluators in parallel."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from livekit.agents import llm as lk_llm

from .judge import Judge
from ..protocol import Action, RiskLevel, Verdict

logger = logging.getLogger(__name__)

# Risk and action severity for worst-case merging
_RISK_ORDER = {RiskLevel.NONE: 0, RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3, RiskLevel.CRITICAL: 4}
_ACTION_ORDER = {Action.CONTINUE: 0, Action.MODIFY: 1, Action.BLOCK: 2, Action.ESCALATE: 3}


def merge_verdicts(verdicts: list[Verdict]) -> Verdict:
    """Merge multiple verdicts using worst-case logic.

    If any judge says block, the merged verdict is block.
    Risk level is the maximum across all judges.
    Reasoning is concatenated from all judges that flagged issues.
    """
    if not verdicts:
        return Verdict(safe=True, risk_level=RiskLevel.NONE, action=Action.CONTINUE, reasoning="No judges ran.")

    if len(verdicts) == 1:
        return verdicts[0]

    worst_risk = max(verdicts, key=lambda v: _RISK_ORDER.get(v.risk_level, 0))
    worst_action = max(verdicts, key=lambda v: _ACTION_ORDER.get(v.action, 0))
    safe = all(v.safe for v in verdicts)

    # Collect reasoning from any judge that flagged issues
    reasons = [f"[{v.risk_level.value}] {v.reasoning}" for v in verdicts if not v.safe]
    if not reasons:
        reasons = [verdicts[0].reasoning]

    # Use corrective instruction from the most severe judge
    corrective = worst_action.corrective_instruction

    return Verdict(
        safe=safe,
        risk_level=worst_risk.risk_level,
        action=worst_action.action,
        reasoning=" | ".join(reasons),
        corrective_instruction=corrective,
    )


class JudgePanel:
    """Runs multiple judges in parallel and merges their verdicts.

    Each judge can focus on a different aspect: safety, compliance, tone, etc.
    Verdicts are merged using worst-case logic — if any judge flags, the response is flagged.
    """

    def __init__(
        self,
        judges: list[Judge],
        *,
        on_verdict: Callable[[Verdict], None] | None = None,
    ):
        self._judges = judges
        self._on_verdict = on_verdict

    @staticmethod
    def create(
        *,
        llm_instance: lk_llm.LLM,
        prompts: dict[str, str],
        eval_threshold_chars: int = 100,
        on_verdict: Callable[[Verdict], None] | None = None,
    ) -> JudgePanel:
        """Create a panel from a dict of {name: prompt} pairs, all sharing one LLM."""
        judges = []
        for name, prompt in prompts.items():
            judge = Judge(
                llm_instance=llm_instance,
                system_prompt=prompt,
                eval_threshold_chars=eval_threshold_chars,
            )
            judges.append(judge)
        return JudgePanel(judges, on_verdict=on_verdict)

    def start_evaluation(self, turn_id: str, chat_ctx: lk_llm.ChatContext | None = None) -> None:
        for judge in self._judges:
            judge.start_evaluation(turn_id, chat_ctx)

    def feed_chunk(self, text: str) -> None:
        for judge in self._judges:
            judge.feed_chunk(text)

    async def finalize(self) -> Verdict:
        """Run all judges in parallel and merge their verdicts."""
        results = await asyncio.gather(
            *[judge.finalize() for judge in self._judges],
            return_exceptions=True,
        )

        verdicts = []
        for r in results:
            if isinstance(r, Verdict):
                verdicts.append(r)
            elif isinstance(r, Exception):
                logger.exception("Judge failed during finalize: %s", r)

        merged = merge_verdicts(verdicts)

        if self._on_verdict:
            try:
                self._on_verdict(merged)
            except Exception:
                logger.exception("on_verdict callback failed")

        return merged

    def cancel(self) -> None:
        for judge in self._judges:
            judge.cancel()

    def update_prompt(self, index: int, prompt: str) -> None:
        """Update a specific judge's prompt by index."""
        if 0 <= index < len(self._judges):
            self._judges[index].update_system_prompt(prompt)
