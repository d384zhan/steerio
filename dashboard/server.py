"""Bidirectional WebSocket server for human operator control."""

from __future__ import annotations

import asyncio
import logging
import pathlib
from collections.abc import Callable
from dataclasses import asdict

import websockets
from websockets.asyncio.server import Server, ServerConnection
from websockets.http11 import Request, Response

from steerio.protocol import GuidanceRequest, TranscriptEvent, Verdict, WsMessage, WsMsgType

logger = logging.getLogger(__name__)

DASHBOARD_HTML = pathlib.Path(__file__).parent / "index.html"


class Dashboard:
    def __init__(
        self,
        *,
        port: int = 8766,
        on_inject_instruction: Callable[[str, str], None] | None = None,
        on_interrupt_and_replace: Callable[[str, str], None] | None = None,
        on_set_mode: Callable[[str, str], None] | None = None,
        on_update_judge_prompt: Callable[[str], None] | None = None,
        on_guidance_response: Callable[[str, str], None] | None = None,
        on_reload_policy: Callable[[str], None] | None = None,
        on_operator_speak: Callable[[str, str], None] | None = None,
    ):
        self._port = port
        self._clients: set[ServerConnection] = set()
        self._server: Server | None = None
        self._on_inject_instruction = on_inject_instruction
        self._on_interrupt_and_replace = on_interrupt_and_replace
        self._on_set_mode = on_set_mode
        self._on_update_judge_prompt = on_update_judge_prompt
        self._on_guidance_response = on_guidance_response
        self._on_reload_policy = on_reload_policy
        self._on_operator_speak = on_operator_speak

    def register_handlers(
        self,
        *,
        on_inject_instruction: Callable[[str, str], None] | None = None,
        on_interrupt_and_replace: Callable[[str, str], None] | None = None,
        on_set_mode: Callable[[str, str], None] | None = None,
        on_update_judge_prompt: Callable[[str], None] | None = None,
        on_guidance_response: Callable[[str, str], None] | None = None,
        on_reload_policy: Callable[[str], None] | None = None,
        on_operator_speak: Callable[[str, str], None] | None = None,
    ):
        """Register operator command handlers after construction.

        Called by SteeredAgent to wire its callbacks into the dashboard.
        """
        if on_inject_instruction:
            self._on_inject_instruction = on_inject_instruction
        if on_interrupt_and_replace:
            self._on_interrupt_and_replace = on_interrupt_and_replace
        if on_set_mode:
            self._on_set_mode = on_set_mode
        if on_update_judge_prompt:
            self._on_update_judge_prompt = on_update_judge_prompt
        if on_guidance_response:
            self._on_guidance_response = on_guidance_response
        if on_reload_policy:
            self._on_reload_policy = on_reload_policy
        if on_operator_speak:
            self._on_operator_speak = on_operator_speak

    async def start(self) -> None:
        self._server = await websockets.serve(
            self._handle_connection,
            "0.0.0.0",
            self._port,
            process_request=self._serve_html,
        )
        logger.info("Dashboard WebSocket listening on ws://0.0.0.0:%d", self._port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._clients.clear()

    def _serve_html(self, connection: ServerConnection, request: Request) -> Response | None:
        if request.path == "/" or request.path == "/index.html":
            try:
                html = DASHBOARD_HTML.read_text()
                return Response(200, "OK", websockets.Headers({"Content-Type": "text/html"}), html.encode())
            except FileNotFoundError:
                return Response(404, "Not Found", websockets.Headers(), b"Dashboard HTML not found")
        return None

    async def _handle_connection(self, ws: ServerConnection) -> None:
        self._clients.add(ws)
        logger.info("Dashboard client connected (%d total)", len(self._clients))
        try:
            async for raw in ws:
                await self._handle_command(ws, str(raw))
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)

    async def _handle_command(self, ws: ServerConnection, raw: str) -> None:
        try:
            msg = WsMessage.from_json(raw)
        except (ValueError, KeyError):
            await self._send_ack(ws, "unknown", ok=False)
            return

        command = msg.type.value
        payload = msg.payload

        if command == WsMsgType.INJECT_INSTRUCTION.value:
            if self._on_inject_instruction:
                try:
                    self._on_inject_instruction(payload["instruction"], payload.get("call_id", ""))
                    await self._send_ack(ws, command, ok=True)
                except Exception:
                    logger.exception("inject_instruction handler failed")
                    await self._send_ack(ws, command, ok=False)
            else:
                await self._send_ack(ws, command, ok=False)

        elif command == WsMsgType.INTERRUPT_AND_REPLACE.value:
            if self._on_interrupt_and_replace:
                try:
                    self._on_interrupt_and_replace(payload["instruction"], payload.get("call_id", ""))
                    await self._send_ack(ws, command, ok=True)
                except Exception:
                    logger.exception("interrupt_and_replace handler failed")
                    await self._send_ack(ws, command, ok=False)
            else:
                await self._send_ack(ws, command, ok=False)

        elif command == WsMsgType.SET_MODE.value:
            if self._on_set_mode:
                try:
                    self._on_set_mode(payload["mode"], payload.get("call_id", ""))
                    await self._send_ack(ws, command, ok=True)
                except Exception:
                    logger.exception("set_mode handler failed")
                    await self._send_ack(ws, command, ok=False)
            else:
                await self._send_ack(ws, command, ok=False)

        elif command == WsMsgType.UPDATE_JUDGE_PROMPT.value:
            if self._on_update_judge_prompt:
                try:
                    self._on_update_judge_prompt(payload["prompt"])
                    await self._send_ack(ws, command, ok=True)
                except Exception:
                    logger.exception("update_judge_prompt handler failed")
                    await self._send_ack(ws, command, ok=False)
            else:
                await self._send_ack(ws, command, ok=False)

        elif command == WsMsgType.RELOAD_POLICY.value:
            if self._on_reload_policy:
                try:
                    self._on_reload_policy(payload.get("call_id", ""))
                    await self._send_ack(ws, command, ok=True)
                except Exception:
                    logger.exception("reload_policy handler failed")
                    await self._send_ack(ws, command, ok=False)
            else:
                await self._send_ack(ws, command, ok=False)

        elif command == WsMsgType.OPERATOR_SPEAK.value:
            if self._on_operator_speak:
                try:
                    self._on_operator_speak(payload["text"], payload.get("call_id", ""))
                    await self._send_ack(ws, command, ok=True)
                except Exception:
                    logger.exception("operator_speak handler failed")
                    await self._send_ack(ws, command, ok=False)
            else:
                await self._send_ack(ws, command, ok=False)

        elif command == WsMsgType.GUIDANCE_RESPONSE.value:
            if self._on_guidance_response:
                try:
                    self._on_guidance_response(payload["request_id"], payload["response"])
                    await self._send_ack(ws, command, ok=True)
                except Exception:
                    logger.exception("guidance_response handler failed")
                    await self._send_ack(ws, command, ok=False)
            else:
                await self._send_ack(ws, command, ok=False)

        else:
            await self._send_ack(ws, command, ok=False)

    async def _send_ack(self, ws: ServerConnection, command: str, *, ok: bool) -> None:
        msg = WsMessage(type=WsMsgType.ACK, payload={"command": command, "ok": ok})
        try:
            await ws.send(msg.to_json())
        except websockets.ConnectionClosed:
            pass

    async def broadcast(self, event: TranscriptEvent) -> None:
        msg = WsMessage(type=WsMsgType.TRANSCRIPT, payload=asdict(event))
        await self._broadcast_raw(msg.to_json())

    async def broadcast_verdict(self, verdict: Verdict, call_id: str = "") -> None:
        payload = asdict(verdict)
        payload["call_id"] = call_id
        msg = WsMessage(type=WsMsgType.VERDICT, payload=payload)
        await self._broadcast_raw(msg.to_json())

    async def broadcast_state(self, state: str, mode: str, call_id: str = "") -> None:
        msg = WsMessage(type=WsMsgType.AGENT_STATE, payload={"state": state, "mode": mode, "call_id": call_id})
        await self._broadcast_raw(msg.to_json())

    async def broadcast_guidance_request(self, req: GuidanceRequest) -> None:
        msg = WsMessage(type=WsMsgType.GUIDANCE_REQUEST, payload=asdict(req))
        await self._broadcast_raw(msg.to_json())

    async def broadcast_call_started(self, call_id: str, label: str = "") -> None:
        msg = WsMessage(type=WsMsgType.CALL_STARTED, payload={"call_id": call_id, "label": label})
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
