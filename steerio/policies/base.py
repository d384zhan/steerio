"""Policy engine — LLM judge evaluation for safety compliance.

All evaluation is done by the LLM judge. The Policy holds the judge prompt,
escalation config, and metadata. No regex rules — the judge handles everything.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EscalationConfig:
    max_consecutive_flags: int = 3
    auto_escalate_on_critical: bool = True
    trend_escalation: bool = True


@dataclass
class Policy:
    """Domain-specific safety policy backed by an LLM judge.

    The judge_prompt tells the LLM judge what to evaluate and how to score.
    """

    name: str
    domain: str
    description: str
    judge_prompt: str = ""
    version: str = "1.0"
    regulatory_refs: list[str] = field(default_factory=list)
    escalation: EscalationConfig | None = None
