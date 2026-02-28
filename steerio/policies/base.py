"""Policy engine — layered defense combining fast rule checks with LLM evaluation.

Architecture: Two-pass evaluation.
  Pass 1 (microseconds): Regex/keyword rules catch obvious violations instantly.
  Pass 2 (hundreds of ms): LLM judge evaluates context-dependent risks.

Pass 1 runs synchronously before TTS starts. If it catches something, we block
immediately without waiting for the LLM. Pass 2 runs in parallel with TTS
(same as the existing judge path).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..protocol import Action, RiskLevel, Verdict


@dataclass(frozen=True)
class EscalationConfig:
    max_consecutive_flags: int = 3
    auto_escalate_on_critical: bool = True
    trend_escalation: bool = True


@dataclass(frozen=True)
class PolicyRule:
    """A single fast-check rule within a policy.

    `pattern` is a regex applied case-insensitively to the agent's response.
    If it matches, the rule fires and produces a verdict with the given
    risk_level, action, and corrective_template.
    """

    name: str
    description: str
    pattern: str
    risk_level: RiskLevel
    action: Action
    corrective_template: str = ""

    def check(self, text: str) -> bool:
        return bool(re.search(self.pattern, text, re.IGNORECASE))


@dataclass
class Policy:
    """Domain-specific safety policy combining rules + LLM prompt.

    Usage:
        verdict = policy.quick_check(agent_text)
        if verdict:
            # Rule-based catch — instant, no LLM needed
            apply_verdict(verdict)
        else:
            # Pass to LLM judge with policy.judge_prompt
            verdict = await judge.evaluate(agent_text)
    """

    name: str
    domain: str
    description: str
    rules: list[PolicyRule] = field(default_factory=list)
    judge_prompt: str = ""
    # Metadata for compliance
    version: str = "1.0"
    regulatory_refs: list[str] = field(default_factory=list)
    escalation: EscalationConfig | None = None

    def quick_check(self, text: str) -> Verdict | None:
        """Run all rules against text. Returns first violation, or None if clean.

        Rules are ordered by severity — most dangerous patterns checked first.
        """
        for rule in self.rules:
            if rule.check(text):
                return Verdict(
                    safe=False,
                    risk_level=rule.risk_level,
                    action=rule.action,
                    reasoning=f"Policy rule [{rule.name}]: {rule.description}",
                    corrective_instruction=rule.corrective_template,
                )
        return None

    def check_all(self, text: str) -> list[Verdict]:
        """Run all rules and return every violation (for audit/reporting)."""
        violations = []
        for rule in self.rules:
            if rule.check(text):
                violations.append(
                    Verdict(
                        safe=False,
                        risk_level=rule.risk_level,
                        action=rule.action,
                        reasoning=f"Policy rule [{rule.name}]: {rule.description}",
                        corrective_instruction=rule.corrective_template,
                    )
                )
        return violations
