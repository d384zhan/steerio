"""Real-time metrics tracking for Steerio calls."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..protocol import Action, RiskLevel, Verdict


@dataclass
class CallMetrics:
    """Metrics for a single call."""
    call_id: str
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    total_verdicts: int = 0
    safe_verdicts: int = 0
    unsafe_verdicts: int = 0
    blocks: int = 0
    escalations: int = 0
    modifications: int = 0
    guidance_requests: int = 0
    guidance_responses: int = 0
    user_turns: int = 0
    agent_turns: int = 0
    # Latency tracking (seconds)
    judge_latencies: list[float] = field(default_factory=list)
    response_latencies: list[float] = field(default_factory=list)
    # Risk distribution
    risk_counts: dict[str, int] = field(default_factory=lambda: {
        "none": 0, "low": 0, "medium": 0, "high": 0, "critical": 0,
    })

    @property
    def duration(self) -> float:
        end = self.ended_at or time.time()
        return end - self.started_at

    @property
    def block_rate(self) -> float:
        return self.blocks / self.total_verdicts if self.total_verdicts else 0.0

    @property
    def avg_judge_latency(self) -> float:
        return sum(self.judge_latencies) / len(self.judge_latencies) if self.judge_latencies else 0.0

    @property
    def avg_response_latency(self) -> float:
        return sum(self.response_latencies) / len(self.response_latencies) if self.response_latencies else 0.0

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "duration": round(self.duration, 1),
            "total_verdicts": self.total_verdicts,
            "safe_verdicts": self.safe_verdicts,
            "unsafe_verdicts": self.unsafe_verdicts,
            "blocks": self.blocks,
            "escalations": self.escalations,
            "modifications": self.modifications,
            "block_rate": round(self.block_rate, 3),
            "guidance_requests": self.guidance_requests,
            "guidance_responses": self.guidance_responses,
            "user_turns": self.user_turns,
            "agent_turns": self.agent_turns,
            "avg_judge_latency_ms": round(self.avg_judge_latency * 1000),
            "avg_response_latency_ms": round(self.avg_response_latency * 1000),
            "risk_counts": self.risk_counts,
        }


class MetricsCollector:
    """Collects metrics across all calls. Thread-safe for asyncio (single-threaded)."""

    def __init__(self):
        self._calls: dict[str, CallMetrics] = {}

    def start_call(self, call_id: str) -> None:
        self._calls[call_id] = CallMetrics(call_id=call_id)

    def end_call(self, call_id: str) -> None:
        m = self._calls.get(call_id)
        if m:
            m.ended_at = time.time()

    def record_verdict(self, call_id: str, verdict: Verdict, latency: float = 0.0) -> None:
        m = self._calls.get(call_id)
        if not m:
            return
        m.total_verdicts += 1
        if verdict.safe:
            m.safe_verdicts += 1
        else:
            m.unsafe_verdicts += 1
        if verdict.action == Action.BLOCK:
            m.blocks += 1
        elif verdict.action == Action.ESCALATE:
            m.escalations += 1
        elif verdict.action == Action.MODIFY:
            m.modifications += 1
        m.risk_counts[verdict.risk_level.value] = m.risk_counts.get(verdict.risk_level.value, 0) + 1
        if latency > 0:
            m.judge_latencies.append(latency)

    def record_user_turn(self, call_id: str) -> None:
        m = self._calls.get(call_id)
        if m:
            m.user_turns += 1

    def record_agent_turn(self, call_id: str, latency: float = 0.0) -> None:
        m = self._calls.get(call_id)
        if m:
            m.agent_turns += 1
            if latency > 0:
                m.response_latencies.append(latency)

    def record_guidance_request(self, call_id: str) -> None:
        m = self._calls.get(call_id)
        if m:
            m.guidance_requests += 1

    def record_guidance_response(self, call_id: str) -> None:
        m = self._calls.get(call_id)
        if m:
            m.guidance_responses += 1

    def get_call_metrics(self, call_id: str) -> dict | None:
        m = self._calls.get(call_id)
        return m.to_dict() if m else None

    def get_aggregate(self) -> dict:
        """Aggregate metrics across all active calls."""
        total_verdicts = sum(m.total_verdicts for m in self._calls.values())
        total_blocks = sum(m.blocks for m in self._calls.values())
        total_escalations = sum(m.escalations for m in self._calls.values())
        all_judge_lat = [l for m in self._calls.values() for l in m.judge_latencies]
        all_resp_lat = [l for m in self._calls.values() for l in m.response_latencies]
        active = sum(1 for m in self._calls.values() if m.ended_at is None)
        completed = sum(1 for m in self._calls.values() if m.ended_at is not None)

        return {
            "active_calls": active,
            "completed_calls": completed,
            "total_verdicts": total_verdicts,
            "total_blocks": total_blocks,
            "total_escalations": total_escalations,
            "block_rate": round(total_blocks / total_verdicts, 3) if total_verdicts else 0.0,
            "avg_judge_latency_ms": round(
                (sum(all_judge_lat) / len(all_judge_lat) * 1000) if all_judge_lat else 0
            ),
            "avg_response_latency_ms": round(
                (sum(all_resp_lat) / len(all_resp_lat) * 1000) if all_resp_lat else 0
            ),
            "calls": {cid: m.to_dict() for cid, m in self._calls.items()},
        }
