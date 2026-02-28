# Protocol — shared types
from .protocol import Action, RiskLevel, Speaker, TranscriptEvent, Verdict

# Core — steering engine
from .core import (
    CallContext,
    CallMetrics,
    CallPhase,
    ContextManager,
    Judge,
    JudgePanel,
    MetricsCollector,
    Recorder,
    SteeredAgent,
    TranscriptionMonitor,
    load_recording,
    merge_verdicts,
)

# Policies — base classes for building safety policies
from .policies import EscalationConfig, Policy, PolicyRule

# Store — Supabase-backed policy store (optional dependency)
try:
    from .store import SupabaseStore
except ImportError:
    SupabaseStore = None  # type: ignore[assignment,misc]

# Compliance — audit, evaluation, reporting
from .compliance import (
    AuditLogger,
    ComplianceReport,
    EvalReport,
    EvaluationHarness,
    TestCase,
    TestSuite,
    generate_report,
)

__all__ = [
    # Core
    "SteeredAgent",
    "Judge",
    "JudgePanel",
    "merge_verdicts",
    "TranscriptionMonitor",
    "MetricsCollector",
    "CallMetrics",
    "ContextManager",
    "CallContext",
    "CallPhase",
    "Recorder",
    "load_recording",
    # Policies (base classes only — domain policies live in demo/)
    "EscalationConfig",
    "Policy",
    "PolicyRule",
    # Compliance & Evaluation
    "AuditLogger",
    "ComplianceReport",
    "generate_report",
    "EvaluationHarness",
    "EvalReport",
    "TestCase",
    "TestSuite",
    # Store (optional)
    "SupabaseStore",
    # Protocol
    "Verdict",
    "RiskLevel",
    "Action",
    "TranscriptEvent",
    "Speaker",
]
