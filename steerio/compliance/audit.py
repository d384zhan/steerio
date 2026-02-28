"""Structured audit logging for regulated industries.

Every safety-relevant event gets an immutable, timestamped audit entry.
Entries include: who (call_id, agent_id), what (event_type, action),
why (reasoning, policy_rule), and when (timestamp).

Writes to append-only JSONL files suitable for regulatory review.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..protocol import Action, RiskLevel, Verdict


@dataclass(frozen=True)
class AuditEntry:
    """Immutable audit record for a single safety-relevant event."""

    timestamp: float
    call_id: str
    event_type: str  # verdict, intervention, mode_change, escalation, guidance
    risk_level: str
    action_taken: str
    reasoning: str
    policy_name: str = ""
    policy_rule: str = ""
    operator_id: str = ""  # Who intervened, if human
    corrective_text: str = ""
    agent_response_preview: str = ""  # First 200 chars of the agent response


class AuditLogger:
    """Append-only audit logger writing JSONL for compliance.

    Usage:
        logger = AuditLogger("audit/session_001.jsonl")
        logger.start()
        logger.log_verdict(call_id, verdict, policy_name="Medical Triage")
        logger.stop()
    """

    def __init__(self, output_path: str | Path):
        self._path = Path(output_path)
        self._file = None
        self._count = 0

    @property
    def entry_count(self) -> int:
        return self._count

    def start(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._path, "a")  # Append mode — never overwrite
        self._write(AuditEntry(
            timestamp=time.time(),
            call_id="",
            event_type="audit_session_start",
            risk_level="none",
            action_taken="none",
            reasoning="Audit session started",
        ))

    def stop(self) -> None:
        if self._file:
            self._write(AuditEntry(
                timestamp=time.time(),
                call_id="",
                event_type="audit_session_end",
                risk_level="none",
                action_taken="none",
                reasoning=f"Audit session ended. {self._count} entries recorded.",
            ))
            self._file.close()
            self._file = None

    def log_verdict(
        self,
        call_id: str,
        verdict: Verdict,
        *,
        policy_name: str = "",
        policy_rule: str = "",
        agent_text: str = "",
    ) -> None:
        self._write(AuditEntry(
            timestamp=time.time(),
            call_id=call_id,
            event_type="verdict",
            risk_level=verdict.risk_level.value,
            action_taken=verdict.action.value,
            reasoning=verdict.reasoning,
            policy_name=policy_name,
            policy_rule=policy_rule,
            corrective_text=verdict.corrective_instruction,
            agent_response_preview=agent_text[:200],
        ))

    def log_intervention(
        self,
        call_id: str,
        *,
        intervention_type: str,  # inject, override, mode_change
        operator_id: str = "operator",
        instruction: str = "",
    ) -> None:
        self._write(AuditEntry(
            timestamp=time.time(),
            call_id=call_id,
            event_type=f"intervention_{intervention_type}",
            risk_level="none",
            action_taken=intervention_type,
            reasoning=instruction,
            operator_id=operator_id,
        ))

    def log_escalation(self, call_id: str, *, reason: str = "") -> None:
        self._write(AuditEntry(
            timestamp=time.time(),
            call_id=call_id,
            event_type="escalation",
            risk_level="high",
            action_taken="escalate",
            reasoning=reason or "Call escalated to human operator",
        ))

    def log_guidance(
        self,
        call_id: str,
        *,
        question: str,
        response: str = "",
        request_id: str = "",
    ) -> None:
        event = "guidance_response" if response else "guidance_request"
        self._write(AuditEntry(
            timestamp=time.time(),
            call_id=call_id,
            event_type=event,
            risk_level="none",
            action_taken="guidance",
            reasoning=question if not response else f"Q: {question} | A: {response}",
        ))

    def _write(self, entry: AuditEntry) -> None:
        if not self._file:
            return
        self._file.write(json.dumps(asdict(entry)) + "\n")
        self._file.flush()
        self._count += 1
