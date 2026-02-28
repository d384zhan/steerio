"""Event recording and replay for Steerio sessions."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

from ..protocol import (
    GuidanceRequest,
    Speaker,
    TranscriptEvent,
    Verdict,
    WsMessage,
    WsMsgType,
)

logger = logging.getLogger(__name__)


class Recorder:
    """Records all Steerio events to a JSONL file for replay and analysis."""

    def __init__(self, output_path: str | Path):
        self._path = Path(output_path)
        self._file = None
        self._start_time: float | None = None

    def start(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._path, "w")
        self._start_time = time.time()
        self._write_event("session_start", {})
        logger.info("Recording to %s", self._path)

    def stop(self) -> None:
        if self._file:
            self._write_event("session_end", {})
            self._file.close()
            self._file = None
            logger.info("Recording saved to %s", self._path)

    def record_transcript(self, event: TranscriptEvent) -> None:
        self._write_event("transcript", asdict(event))

    def record_verdict(self, verdict: Verdict, call_id: str) -> None:
        payload = asdict(verdict)
        payload["call_id"] = call_id
        self._write_event("verdict", payload)

    def record_call_started(self, call_id: str, label: str = "") -> None:
        self._write_event("call_started", {"call_id": call_id, "label": label})

    def record_call_ended(self, call_id: str) -> None:
        self._write_event("call_ended", {"call_id": call_id})

    def record_agent_state(self, state: str, mode: str, call_id: str) -> None:
        self._write_event("agent_state", {"state": state, "mode": mode, "call_id": call_id})

    def record_guidance_request(self, req: GuidanceRequest) -> None:
        self._write_event("guidance_request", asdict(req))

    def record_guidance_response(self, request_id: str, response: str, call_id: str) -> None:
        self._write_event("guidance_response", {
            "request_id": request_id, "response": response, "call_id": call_id,
        })

    def record_operator_command(self, command: str, payload: dict) -> None:
        self._write_event(f"operator_{command}", payload)

    def _write_event(self, event_type: str, payload: dict) -> None:
        if not self._file:
            return
        offset = time.time() - (self._start_time or time.time())
        record = {
            "t": round(offset, 3),
            "ts": time.time(),
            "type": event_type,
            "payload": payload,
        }
        self._file.write(json.dumps(record) + "\n")
        self._file.flush()


def load_recording(path: str | Path) -> list[dict]:
    """Load a recording file and return events as a list of dicts."""
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def print_recording_summary(path: str | Path) -> None:
    """Print a human-readable summary of a recording."""
    events = load_recording(path)
    if not events:
        print("Empty recording.")
        return

    calls = {}
    verdicts = {"safe": 0, "unsafe": 0}
    blocks = 0

    for e in events:
        t = e["type"]
        p = e.get("payload", {})
        if t == "call_started":
            calls[p["call_id"]] = p.get("label", p["call_id"])
        elif t == "verdict":
            if p.get("safe"):
                verdicts["safe"] += 1
            else:
                verdicts["unsafe"] += 1
            if p.get("action") == "block":
                blocks += 1

    duration = events[-1]["t"] if events else 0
    print(f"Recording: {path}")
    print(f"  Duration: {duration:.1f}s")
    print(f"  Events: {len(events)}")
    print(f"  Calls: {len(calls)}")
    for cid, label in calls.items():
        print(f"    - {label} ({cid})")
    print(f"  Verdicts: {verdicts['safe']} safe, {verdicts['unsafe']} unsafe")
    print(f"  Blocks: {blocks}")
