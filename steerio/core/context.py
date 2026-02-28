"""Per-call conversation context tracking."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from ..policies.base import EscalationConfig
from ..protocol import Action, RiskLevel, Speaker, TranscriptEvent, Verdict


class CallPhase(str, Enum):
    GREETING = "greeting"
    ASSESSMENT = "assessment"
    GUIDANCE = "guidance"
    RESOLUTION = "resolution"
    CLOSING = "closing"


@dataclass
class RiskWindow:
    """Sliding window of recent risk assessments."""
    verdicts: list[Verdict] = field(default_factory=list)
    window_size: int = 10

    def add(self, verdict: Verdict) -> None:
        self.verdicts.append(verdict)
        if len(self.verdicts) > self.window_size:
            self.verdicts.pop(0)

    @property
    def trend(self) -> str:
        """Returns 'escalating', 'stable', or 'improving'."""
        if len(self.verdicts) < 2:
            return "stable"
        levels = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        recent = [levels.get(v.risk_level.value, 0) for v in self.verdicts[-5:]]
        earlier = [levels.get(v.risk_level.value, 0) for v in self.verdicts[:-5]] or [0]
        avg_recent = sum(recent) / len(recent)
        avg_earlier = sum(earlier) / len(earlier)
        if avg_recent > avg_earlier + 0.5:
            return "escalating"
        if avg_recent < avg_earlier - 0.5:
            return "improving"
        return "stable"

    @property
    def max_risk(self) -> str:
        if not self.verdicts:
            return "none"
        levels = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        worst = max(self.verdicts, key=lambda v: levels.get(v.risk_level.value, 0))
        return worst.risk_level.value


@dataclass
class CallContext:
    """Tracks conversation state for a single call."""
    call_id: str
    phase: CallPhase = CallPhase.GREETING
    mode: str = "llm"
    risk_window: RiskWindow = field(default_factory=RiskWindow)
    topics: list[str] = field(default_factory=list)
    turn_count: int = 0
    mode_transitions: list[tuple[str, float]] = field(default_factory=list)
    pending_guidance: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def advance_turn(self) -> None:
        self.turn_count += 1
        # Auto-advance phase based on turn count
        if self.turn_count == 1:
            self.phase = CallPhase.GREETING
        elif self.turn_count <= 3:
            self.phase = CallPhase.ASSESSMENT
        elif self.pending_guidance:
            self.phase = CallPhase.GUIDANCE

    def record_verdict(self, verdict: Verdict) -> None:
        self.risk_window.add(verdict)

    def set_mode(self, mode: str) -> None:
        if mode != self.mode:
            self.mode_transitions.append((mode, time.time()))
            self.mode = mode

    def add_guidance(self, request_id: str, question: str) -> None:
        self.pending_guidance[request_id] = question
        self.phase = CallPhase.GUIDANCE

    def resolve_guidance(self, request_id: str) -> None:
        self.pending_guidance.pop(request_id, None)
        if not self.pending_guidance:
            self.phase = CallPhase.RESOLUTION

    def should_escalate(self, verdict: Verdict, config: EscalationConfig | None) -> bool:
        if not config:
            return False
        if config.auto_escalate_on_critical and verdict.risk_level == RiskLevel.CRITICAL:
            return True
        if config.max_consecutive_flags > 0:
            recent = self.risk_window.verdicts[-config.max_consecutive_flags:]
            if len(recent) >= config.max_consecutive_flags and all(not v.safe for v in recent):
                return True
        if config.trend_escalation and self.risk_window.trend == "escalating":
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "phase": self.phase.value,
            "mode": self.mode,
            "turn_count": self.turn_count,
            "risk_trend": self.risk_window.trend,
            "max_risk": self.risk_window.max_risk,
            "pending_guidance": len(self.pending_guidance),
            "mode_transitions": len(self.mode_transitions),
            "duration": round(time.time() - self.created_at, 1),
        }


class ContextManager:
    """Manages call contexts across multiple calls."""

    def __init__(self):
        self._calls: dict[str, CallContext] = {}

    def start_call(self, call_id: str) -> CallContext:
        ctx = CallContext(call_id=call_id)
        self._calls[call_id] = ctx
        return ctx

    def get(self, call_id: str) -> CallContext | None:
        return self._calls.get(call_id)

    def end_call(self, call_id: str) -> None:
        ctx = self._calls.get(call_id)
        if ctx:
            ctx.phase = CallPhase.CLOSING

    def get_all(self) -> dict[str, dict]:
        return {cid: ctx.to_dict() for cid, ctx in self._calls.items()}
