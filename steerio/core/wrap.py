"""SteeredAgent — the core wrapper that adds judge, monitor, and operator control to a LiveKit Agent.

The judge runs inside llm_node() regardless of whether a dashboard or monitor
is connected. Dashboard and monitor are optional broadcast sinks.
Pass dashboard=None and monitor_port=0 to run fully standalone.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from livekit.agents import Agent, AgentSession, RunContext
from livekit.agents.llm import ChatContext, ChatMessage, FunctionTool, function_tool
from livekit.agents.voice import ModelSettings

from ..compliance.audit import AuditLogger
from ..policies.base import Policy
from ..protocol import Action, GuidanceRequest, Speaker, TranscriptEvent
from .context import CallContext, ContextManager
from .judge import DEFAULT_JUDGE_PROMPT, Judge
from .judges import JudgePanel
from .metrics import MetricsCollector
from .monitor import TranscriptionMonitor
from .recorder import Recorder

logger = logging.getLogger(__name__)


class SteeredAgent(Agent):
    def __init__(
        self,
        *,
        judge_llm: Any,
        judge_prompt: str = "",
        judge_prompts: dict[str, str] | None = None,
        policy: Policy | None = None,
        store: Any | None = None,
        policy_id: str = "",
        mode: str = "llm",
        monitor_port: int = 0,
        dashboard: Any | None = None,
        eval_threshold_chars: int = 100,
        call_id: str = "",
        guidance_hold_message: str = "Please wait while I get that information for you.",
        guidance_timeout: float = 60.0,
        recording_path: str = "",
        audit_path: str = "",
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._mode = mode
        self._call_id = call_id or str(uuid.uuid4())[:8]
        self._pending_instruction: str | None = None
        self._guidance_futures: dict[str, asyncio.Future[str]] = {}
        self._guidance_hold_message = guidance_hold_message
        self._guidance_timeout = guidance_timeout
        self._policy = policy
        self._store = store
        self._policy_id = policy_id
        self._judge_llm = judge_llm
        self._eval_threshold_chars = eval_threshold_chars

        # Accumulated corrections from judge — injected into every future turn
        self._corrections: list[str] = []
        self._consecutive_blocks = 0
        self._max_consecutive_blocks = 3

        self._evaluator = self._build_evaluator(
            judge_llm, judge_prompt, judge_prompts, policy, eval_threshold_chars,
        )

        # DECISION: Monitor and dashboard are optional. None means disabled.
        # Tradeoff: Slightly more guard checks, but the SDK works standalone.
        self._monitor = TranscriptionMonitor(port=monitor_port) if monitor_port else None
        self._dashboard = dashboard

        # Analytics
        self._metrics = MetricsCollector()
        self._ctx_mgr = ContextManager()
        self._recorder = Recorder(recording_path) if recording_path else None
        self._audit = AuditLogger(audit_path) if audit_path else None

    def _build_evaluator(
        self, judge_llm, judge_prompt, judge_prompts, policy, eval_threshold_chars,
    ):
        verdict_cb = lambda v: asyncio.create_task(self._broadcast_verdict(v))

        if judge_prompts and len(judge_prompts) > 1:
            return JudgePanel.create(
                llm_instance=judge_llm,
                prompts=judge_prompts,
                eval_threshold_chars=eval_threshold_chars,
                on_verdict=verdict_cb,
            )

        effective_prompt = judge_prompt or (policy.judge_prompt if policy else "") or DEFAULT_JUDGE_PROMPT
        return Judge(
            llm_instance=judge_llm,
            system_prompt=effective_prompt,
            eval_threshold_chars=eval_threshold_chars,
            on_verdict=verdict_cb,
        )

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def call_id(self) -> str:
        return self._call_id

    @property
    def metrics(self) -> MetricsCollector:
        return self._metrics

    async def on_enter(self) -> None:
        if self._store and self._policy_id:
            await self._load_from_store()

        self._metrics.start_call(self._call_id)
        self._ctx_mgr.start_call(self._call_id)
        if self._recorder:
            self._recorder.start()
            self._recorder.record_call_started(self._call_id)
        if self._audit:
            self._audit.start()

        if self._monitor:
            await self._monitor.start()
        await self._broadcast_call_started(self._call_id)
        await self._broadcast_state("listening")
        self.session.generate_reply()

    async def on_exit(self) -> None:
        self._evaluator.cancel()
        self._metrics.end_call(self._call_id)
        self._ctx_mgr.end_call(self._call_id)

        if self._recorder:
            self._recorder.record_call_ended(self._call_id)
            self._recorder.stop()
        if self._audit:
            self._audit.stop()

        await self._broadcast_call_ended(self._call_id)
        if self._monitor:
            await self._monitor.stop()

    async def on_user_turn_completed(
        self,
        turn_ctx: ChatContext,
        new_message: ChatMessage,
    ) -> None:
        self._metrics.record_user_turn(self._call_id)
        ctx = self._ctx_mgr.get(self._call_id)
        if ctx:
            ctx.advance_turn()

        event = TranscriptEvent(
            speaker=Speaker.USER,
            text=new_message.text_content or "",
            is_final=True,
            turn_id=str(uuid.uuid4()),
            call_id=self._call_id,
        )
        await self._broadcast_transcript(event)
        if self._recorder:
            self._recorder.record_transcript(event)

        await self._broadcast_state("thinking")

        if self._pending_instruction:
            turn_ctx.add_message(role="system", content=self._pending_instruction)
            self._pending_instruction = None

        # Inject accumulated corrections so the agent remembers past violations
        if self._corrections:
            correction_block = (
                "CRITICAL SAFETY CORRECTIONS — You MUST follow these on every response. "
                "You have been flagged for the following violations during this call:\n"
                + "\n".join(f"- {c}" for c in self._corrections)
                + "\nDo NOT repeat these mistakes. Follow your safety guidelines strictly."
            )
            turn_ctx.add_message(role="system", content=correction_block)

    async def llm_node(
        self,
        chat_ctx: ChatContext,
        tools: list[FunctionTool],
        model_settings: ModelSettings,
    ):
        turn_id = str(uuid.uuid4())
        self._evaluator.start_evaluation(turn_id, chat_ctx)
        accumulated_text = ""
        response_start = time.monotonic()

        await self._broadcast_state("speaking")

        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            if isinstance(chunk, str):
                self._evaluator.feed_chunk(chunk)
                accumulated_text += chunk
            elif hasattr(chunk, "delta") and chunk.delta and chunk.delta.content:
                self._evaluator.feed_chunk(chunk.delta.content)
                accumulated_text += chunk.delta.content
            yield chunk

        response_latency = time.monotonic() - response_start
        self._metrics.record_agent_turn(self._call_id, latency=response_latency)

        agent_event = TranscriptEvent(
            speaker=Speaker.AGENT,
            text=accumulated_text,
            is_final=True,
            turn_id=turn_id,
            call_id=self._call_id,
        )
        await self._broadcast_transcript(agent_event)
        if self._recorder:
            self._recorder.record_transcript(agent_event)

        # DECISION: Judge evaluation runs async (fire-and-forget) so the agent
        # returns to "listening" immediately. This makes the conversation feel
        # natural — no pause between agent response and next caller turn.
        if self._mode == "llm":
            asyncio.create_task(self._evaluate_in_background(accumulated_text, turn_id))

        await self._broadcast_state("listening")

    async def _evaluate_in_background(self, accumulated_text: str, turn_id: str) -> None:
        """Run judge evaluation without blocking the conversation."""
        try:
            await self._broadcast_judge_status("evaluating")
            judge_start = time.monotonic()
            verdict = await self._evaluator.finalize()
            judge_latency = time.monotonic() - judge_start
            self._metrics.record_verdict(self._call_id, verdict, latency=judge_latency)

            ctx = self._ctx_mgr.get(self._call_id)
            if ctx:
                ctx.record_verdict(verdict)
            if self._recorder:
                self._recorder.record_verdict(verdict, self._call_id)
            if self._audit:
                self._audit.log_verdict(
                    self._call_id, verdict,
                    policy_name=self._policy.name if self._policy else "",
                    agent_text=accumulated_text,
                )

            await self._apply_verdict(verdict, accumulated_text, turn_id)
        except Exception:
            logger.exception("Background judge evaluation failed for turn %s", turn_id)

    @function_tool
    async def request_guidance(self, context: RunContext, question: str) -> str:
        """Ask the human operator for guidance when you are uncertain about something.
        Use this when you don't know the answer, need to verify critical information,
        or want a human expert's input before responding to the caller.

        Args:
            question: What you need help with. Be specific about what information you need.
        """
        request_id = str(uuid.uuid4())[:8]
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._guidance_futures[request_id] = future

        self.session.say(self._guidance_hold_message)

        req = GuidanceRequest(
            call_id=self._call_id,
            question=question,
            context="",
            request_id=request_id,
        )
        if self._monitor:
            await self._monitor.broadcast_guidance_request(req)
        if self._dashboard:
            await self._dashboard.broadcast_guidance_request(req)
        if self._recorder:
            self._recorder.record_guidance_request(req)
        if self._metrics:
            self._metrics.record_guidance_request(self._call_id)
        if self._audit:
            self._audit.log_guidance(self._call_id, question=question, request_id=request_id)

        ctx = self._ctx_mgr.get(self._call_id)
        if ctx:
            ctx.add_guidance(request_id, question)

        await self._broadcast_state("waiting")

        try:
            response = await asyncio.wait_for(future, timeout=self._guidance_timeout)
        except asyncio.TimeoutError:
            response = "I wasn't able to get additional information on that. Let me help you with what I know."
        finally:
            self._guidance_futures.pop(request_id, None)

        if self._recorder:
            self._recorder.record_guidance_response(request_id, response, self._call_id)
        if self._metrics:
            self._metrics.record_guidance_response(self._call_id)
        if self._audit:
            self._audit.log_guidance(self._call_id, question=question, response=response, request_id=request_id)
        if ctx:
            ctx.resolve_guidance(request_id)

        await self._broadcast_state("speaking")
        return response

    # ── Verdict actions ──

    async def _apply_verdict(self, verdict, accumulated_text: str, turn_id: str) -> None:
        if verdict.action == Action.CONTINUE:
            self._consecutive_blocks = 0
            return

        if verdict.action == Action.MODIFY:
            self._pending_instruction = verdict.corrective_instruction
            # Also persist the correction so it sticks for future turns
            if verdict.corrective_instruction:
                self._corrections.append(verdict.reasoning or verdict.corrective_instruction)
            return

        # BLOCK / ESCALATE
        self._consecutive_blocks += 1
        corrective = verdict.corrective_instruction or (
            "I need to correct what I just said. "
            "Let me make sure I give you accurate and safe information."
        )

        # Persist the violation so the agent is reminded on every future turn
        if verdict.reasoning:
            self._corrections.append(verdict.reasoning)

        await self.session.interrupt()

        if self._consecutive_blocks >= self._max_consecutive_blocks:
            asyncio.create_task(self._escalate_and_end(corrective))
        else:
            self.session.say(corrective)

    async def _escalate_and_end(self, last_corrective: str) -> None:
        escalation_msg = (
            "I'm going to transfer you to a human representative who can better assist you. "
            "Thank you for your patience, and I apologize for any confusion. Goodbye."
        )
        self.session.say(escalation_msg)

        # Broadcast escalation as a system transcript event
        event = TranscriptEvent(
            speaker=Speaker.SYSTEM,
            text=f"[ESCALATION] Call terminated after {self._consecutive_blocks} consecutive safety violations. Last: {last_corrective}",
            is_final=True,
            turn_id=str(uuid.uuid4()),
            call_id=self._call_id,
        )
        await self._broadcast_transcript(event)
        if self._recorder:
            self._recorder.record_transcript(event)
        if self._audit:
            self._audit.log_intervention(
                self._call_id,
                intervention_type="escalation_disconnect",
                instruction=f"Auto-terminated after {self._consecutive_blocks} consecutive blocks",
            )

        logger.warning(
            "Call %s escalated and terminated — %d consecutive blocks",
            self._call_id, self._consecutive_blocks,
        )

        # Disconnect after a short delay so TTS finishes the goodbye
        await asyncio.sleep(6)
        await self._broadcast_call_ended(self._call_id)
        if hasattr(self, 'session') and self.session:
            room = getattr(self.session, 'room', None)
            if room:
                await room.disconnect()

    # ── Broadcast helpers (guard for optional monitor/dashboard) ──

    async def _broadcast_transcript(self, event: TranscriptEvent) -> None:
        if self._monitor:
            await self._monitor.broadcast(event)
        if self._dashboard:
            await self._dashboard.broadcast(event)

    async def _broadcast_verdict(self, verdict) -> None:
        if self._monitor:
            await self._monitor.broadcast_verdict(verdict, self._call_id)
        if self._dashboard:
            await self._dashboard.broadcast_verdict(verdict, self._call_id)

    async def _broadcast_state(self, state: str) -> None:
        if self._recorder:
            self._recorder.record_agent_state(state, self._mode, self._call_id)
        ctx = self._ctx_mgr.get(self._call_id)
        if ctx:
            ctx.set_mode(self._mode)
        if self._monitor:
            await self._monitor.broadcast_state(state, self._mode, self._call_id)
        if self._dashboard:
            await self._dashboard.broadcast_state(state, self._mode, self._call_id)

    async def _broadcast_judge_status(self, status: str) -> None:
        if self._monitor:
            await self._monitor.broadcast_judge_status(status, self._call_id)
        if self._dashboard:
            await self._dashboard.broadcast_judge_status(status, self._call_id)

    async def _broadcast_context_update(self, ctx: CallContext) -> None:
        if self._monitor:
            await self._monitor.broadcast_context_update(self._call_id, ctx.to_dict())
        if self._dashboard:
            await self._dashboard.broadcast_context_update(self._call_id, ctx.to_dict())

    async def _broadcast_call_started(self, call_id: str, label: str = "") -> None:
        if self._monitor:
            await self._monitor.broadcast_call_started(call_id, label)
        if self._dashboard:
            await self._dashboard.broadcast_call_started(call_id, label)

    async def _broadcast_call_ended(self, call_id: str) -> None:
        if self._monitor:
            await self._monitor.broadcast_call_ended(call_id)
        if self._dashboard:
            await self._dashboard.broadcast_call_ended(call_id)

    # ── Operator command handlers (public API for control layer wiring) ──

    def handle_inject_instruction(self, instruction: str, call_id: str) -> None:
        if call_id and call_id != self._call_id:
            return
        if self._mode != "human":
            logger.info("Inject ignored — only available in human mode (current: %s)", self._mode)
            return
        if self._audit:
            self._audit.log_intervention(self._call_id, intervention_type="inject", instruction=instruction)
        asyncio.create_task(self._do_inject(instruction))

    async def _do_inject(self, instruction: str) -> None:
        event = TranscriptEvent(
            speaker=Speaker.SYSTEM,
            text=f"[INJECT] {instruction}",
            is_final=True,
            turn_id=str(uuid.uuid4()),
            call_id=self._call_id,
        )
        await self._broadcast_transcript(event)
        await self.session.interrupt()
        self.session.generate_reply(instructions=instruction)
        logger.info("Operator injected instruction: %s", instruction[:100])

    def handle_interrupt_and_replace(self, instruction: str, call_id: str) -> None:
        if call_id and call_id != self._call_id:
            return
        if self._audit:
            self._audit.log_intervention(self._call_id, intervention_type="override", instruction=instruction)
        asyncio.create_task(self._do_interrupt_and_replace(instruction))

    async def _do_interrupt_and_replace(self, instruction: str) -> None:
        event = TranscriptEvent(
            speaker=Speaker.SYSTEM,
            text=f"[OVERRIDE] {instruction}",
            is_final=True,
            turn_id=str(uuid.uuid4()),
            call_id=self._call_id,
        )
        await self._broadcast_transcript(event)
        await self.session.interrupt()
        self.session.generate_reply(instructions=instruction)

    def handle_set_mode(self, mode: str, call_id: str) -> None:
        if call_id and call_id != self._call_id:
            return
        self._mode = mode
        if self._audit:
            self._audit.log_intervention(self._call_id, intervention_type="mode_change", instruction=f"Mode -> {mode}")
        asyncio.create_task(self._broadcast_state("listening"))
        logger.info("Mode switched to: %s", mode)

    def handle_operator_speak(self, text: str, call_id: str) -> None:
        if call_id and call_id != self._call_id:
            return
        if self._mode != "human":
            logger.info("Operator speak ignored — only available in human mode (current: %s)", self._mode)
            return
        if self._audit:
            self._audit.log_intervention(self._call_id, intervention_type="operator_speak", instruction=text)
        asyncio.create_task(self._do_operator_speak(text))

    async def _do_operator_speak(self, text: str) -> None:
        await self.session.interrupt()
        # Broadcast operator speech as a system transcript event
        event = TranscriptEvent(
            speaker=Speaker.SYSTEM,
            text=f"[OPERATOR] {text}",
            is_final=True,
            turn_id=str(uuid.uuid4()),
            call_id=self._call_id,
        )
        await self._broadcast_transcript(event)
        if self._recorder:
            self._recorder.record_transcript(event)
        await self._broadcast_state("speaking")
        self.session.say(text)
        logger.info("Operator speaking: %s", text[:100])

    def handle_update_judge_prompt(self, prompt: str) -> None:
        if isinstance(self._evaluator, Judge):
            self._evaluator.update_system_prompt(prompt)

    def handle_reload_policy(self, call_id: str) -> None:
        if self._store and self._policy_id:
            asyncio.create_task(self._load_from_store())
            logger.info("Policy reload triggered for %s", self._policy_id)

    async def _load_from_store(self) -> None:
        policy = await asyncio.to_thread(self._store.load_policy, self._policy_id)
        self._policy = policy
        self._evaluator = self._build_evaluator(
            self._judge_llm, policy.judge_prompt, None, policy, self._eval_threshold_chars,
        )
        logger.info("Loaded policy '%s' from store", policy.name)

    def handle_guidance_response(self, request_id: str, response: str) -> None:
        future = self._guidance_futures.get(request_id)
        if future and not future.done():
            future.set_result(response)
            logger.info("Guidance received for %s", request_id)
