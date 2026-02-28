from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Action(str, Enum):
    CONTINUE = "continue"
    MODIFY = "modify"
    BLOCK = "block"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class Verdict:
    safe: bool
    risk_level: RiskLevel
    action: Action
    reasoning: str
    corrective_instruction: str = ""


class Speaker(str, Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


@dataclass(frozen=True)
class TranscriptEvent:
    speaker: Speaker
    text: str
    is_final: bool
    turn_id: str
    call_id: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class GuidanceRequest:
    call_id: str
    question: str
    context: str
    request_id: str
    timestamp: float = field(default_factory=time.time)


class WsMsgType(str, Enum):
    TRANSCRIPT = "transcript"
    VERDICT = "verdict"
    AGENT_STATE = "agent_state"
    ERROR = "error"
    ACK = "ack"
    # Call lifecycle
    CALL_STARTED = "call_started"
    CALL_ENDED = "call_ended"
    # Guidance flow
    GUIDANCE_REQUEST = "guidance_request"
    GUIDANCE_RESPONSE = "guidance_response"
    # Judge + context streaming
    JUDGE_STATUS = "judge_status"
    CONTEXT_UPDATE = "context_update"
    # Operator commands (client→server)
    INJECT_INSTRUCTION = "inject_instruction"
    INTERRUPT_AND_REPLACE = "interrupt_and_replace"
    SET_MODE = "set_mode"
    UPDATE_JUDGE_PROMPT = "update_judge_prompt"
    RELOAD_POLICY = "reload_policy"
    OPERATOR_SPEAK = "operator_speak"
    # SIP dialing (client↔server)
    DIAL_CALL = "dial_call"
    HANG_UP = "hang_up"
    CALL_STATUS = "call_status"
    # Voice input (operator mic → STT)
    VOICE_INPUT = "voice_input"
    VOICE_TRANSCRIPTION = "voice_transcription"
    # Operator speak via mic (operator mic → STT → say to caller)
    SPEAK_VOICE = "speak_voice"
    SPEAK_TRANSCRIPTION = "speak_transcription"


@dataclass
class WsMessage:
    type: WsMsgType
    payload: dict[str, Any]
    ts: float = field(default_factory=time.time)

    def to_json(self) -> str:
        import json
        return json.dumps({"type": self.type.value, "payload": self.payload, "ts": self.ts})

    @staticmethod
    def from_json(raw: str) -> WsMessage:
        import json
        data = json.loads(raw)
        return WsMessage(
            type=WsMsgType(data["type"]),
            payload=data["payload"],
            ts=data.get("ts", time.time()),
        )
