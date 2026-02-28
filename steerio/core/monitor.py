"""WebSocket broadcast server for live transcription streaming."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict

import websockets
from websockets.asyncio.server import Server, ServerConnection

from ..protocol import GuidanceRequest, TranscriptEvent, Verdict, WsMessage, WsMsgType

logger = logging.getLogger(__name__)


class TranscriptionMonitor:
    def __init__(self, *, port: int = 8765):
        self._port = port
        self._clients: set[ServerConnection] = set()
        self._server: Server | None = None

    async def start(self) -> None:
        self._server = await websockets.serve(
            self._handle_connection,
            "0.0.0.0",
            self._port,
        )
        logger.info("Monitor WebSocket listening on ws://0.0.0.0:%d", self._port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._clients.clear()

    async def _handle_connection(self, ws: ServerConnection) -> None:
        self._clients.add(ws)
        logger.info("Monitor client connected (%d total)", len(self._clients))
        try:
            async for _ in ws:
                pass
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)

    async def broadcast(self, event: TranscriptEvent) -> None:
        msg = WsMessage(type=WsMsgType.TRANSCRIPT, payload=asdict(event))
        await self._broadcast_raw(msg.to_json())

    async def broadcast_verdict(self, verdict: Verdict, call_id: str = "") -> None:
        payload = asdict(verdict)
        payload["call_id"] = call_id
        msg = WsMessage(type=WsMsgType.VERDICT, payload=payload)
        await self._broadcast_raw(msg.to_json())

    async def broadcast_state(self, state: str, mode: str, call_id: str = "") -> None:
        msg = WsMessage(
            type=WsMsgType.AGENT_STATE,
            payload={"state": state, "mode": mode, "call_id": call_id},
        )
        await self._broadcast_raw(msg.to_json())

    async def broadcast_guidance_request(self, req: GuidanceRequest) -> None:
        msg = WsMessage(type=WsMsgType.GUIDANCE_REQUEST, payload=asdict(req))
        await self._broadcast_raw(msg.to_json())

    async def broadcast_call_started(self, call_id: str, label: str = "") -> None:
        msg = WsMessage(
            type=WsMsgType.CALL_STARTED,
            payload={"call_id": call_id, "label": label},
        )
        await self._broadcast_raw(msg.to_json())

    async def broadcast_judge_status(self, status: str, call_id: str = "", **extra) -> None:
        payload = {"status": status, "call_id": call_id, **extra}
        msg = WsMessage(type=WsMsgType.JUDGE_STATUS, payload=payload)
        await self._broadcast_raw(msg.to_json())

    async def broadcast_context_update(self, call_id: str, context_dict: dict) -> None:
        payload = {"call_id": call_id, **context_dict}
        msg = WsMessage(type=WsMsgType.CONTEXT_UPDATE, payload=payload)
        await self._broadcast_raw(msg.to_json())

    async def broadcast_call_ended(self, call_id: str) -> None:
        msg = WsMessage(type=WsMsgType.CALL_ENDED, payload={"call_id": call_id})
        await self._broadcast_raw(msg.to_json())

    async def _broadcast_raw(self, data: str) -> None:
        if not self._clients:
            return
        dead: list[ServerConnection] = []
        await asyncio.gather(
            *[self._send_or_drop(ws, data, dead) for ws in self._clients]
        )
        for ws in dead:
            self._clients.discard(ws)

    async def _send_or_drop(
        self, ws: ServerConnection, data: str, dead: list[ServerConnection]
    ) -> None:
        try:
            await ws.send(data)
        except websockets.ConnectionClosed:
            dead.append(ws)
