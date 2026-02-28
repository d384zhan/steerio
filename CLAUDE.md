# CLAUDE.md — Project Guide for AI-Assisted Development

## Core Principles

### 1. Do Not Over-Engineer
- Solve the problem in front of you, not hypothetical future ones.
- Three similar lines > a premature abstraction.
- No feature flags, config layers, or plugin systems until proven necessary.
- If you're adding a util/helper for one call site, inline it instead.

### 2. DRY — Apply Aggressively
- Before writing new code, search the codebase for existing solutions.
- Extract shared logic only when duplication is real (3+ occurrences), not speculative.
- Shared code lives in clearly named, single-purpose modules.
- When extracting, prefer colocation (near usage) over centralized `utils/` dumps.

### 3. Explicit Over Clever
- Name things for what they do, not how they do it.
- Avoid magic strings, implicit conventions, and hidden control flow.
- Prefer verbose clarity over terse cleverness — future readers include AI agents.
- If a decision involves a tradeoff, leave a comment explaining your reasoning.

### 4. Tradeoff Comments
When architecture requires choosing between competing concerns, document it:
```
// DECISION: Chose X over Y because [reason].
// Tradeoff: We lose [downside] but gain [upside].
// Revisit if [condition changes].
```
Do this at the point of decision, not in a separate doc.

## QA Discipline

- Run `/qa` after every meaningful change — not just at the end.
- Run `/qa` after finishing a feature, fixing a bug, or refactoring.
- Run `/qa` before any commit.
- If `/qa` surfaces issues, fix them before moving on.

## Development Commands

```sh
# Install
uv sync --extra demo --extra supabase

# Import check
uv run python -c "from steerio import SteeredAgent, Policy, SupabaseStore"

# Run policy evaluation (needs SUPABASE_URL + SUPABASE_ANON_KEY)
uv run python demo/demo_eval.py

# Run voice demo (needs all keys in demo/.env)
uv run python demo/demo_voice.py
```

## Code Style

- No comments on self-evident code. Comment *why*, never *what*.
- No docstrings on internal functions unless the contract is non-obvious.
- No type annotations on variables where inference is clear.
- Error handling only at system boundaries (user input, external APIs, I/O).
- Trust internal code — don't defensively check what you control.

## File & Project Structure

```
steerio/                 # SDK — pip install steerio
├── __init__.py          # Public API (28 exports)
├── protocol.py          # Shared dataclasses and enums
│
├── core/                # Steering engine
│   ├── wrap.py          # SteeredAgent(Agent) — the core wrapper
│   ├── judge.py         # LLM judge: evaluate agent output for safety
│   ├── judges.py        # JudgePanel — multi-judge parallel evaluation
│   ├── monitor.py       # WebSocket broadcast (port 8765)
│   ├── metrics.py       # Real-time call metrics and latency tracking
│   ├── context.py       # Per-call conversation state and risk trends
│   └── recorder.py      # JSONL event recording for replay/analysis
│
├── policies/            # Policy framework (base classes only)
│   └── base.py          # Policy, PolicyRule, EscalationConfig
│
├── compliance/          # Audit, evaluation, reporting
│   ├── audit.py         # Append-only JSONL audit logger
│   ├── report.py        # Compliance report generation
│   ├── harness.py       # Run test suites, report accuracy/F1/precision/recall
│   └── scenarios.py     # TestCase + TestSuite dataclasses
│
└── store/               # Supabase-backed policy store (optional)
    ├── supabase.py      # SupabaseStore — sync client for policies/rules/judges
    ├── schema.sql       # Database schema (3 tables)
    └── seed.sql         # Seed data for demo

demo/                    # Demo application (shows production usage)
├── demo_eval.py         # Policy evaluation — loads from Supabase
├── demo_voice.py        # Voice demo — two agents in LiveKit Cloud room
├── dashboard.py         # Bidirectional WebSocket server (port 8766)
├── dashboard.html       # Frontend (single HTML, modern light theme)
├── caller.py            # AI caller agent for voice demo
├── scenarios.py         # Test scenarios for all 3 domains
└── .env                 # API keys (gitignored)
```

- Keep files small and focused. One concept per file.
- Colocate tests next to source (`foo.py` / `foo_test.py`).
- Colocate types with their consumers, not in global `types/` files.
- Flat over nested. Add depth only when a directory exceeds ~10 files.

## Git Practices

- Commit messages: imperative mood, concise, explain *why* not *what*.
- Small, atomic commits. One logical change per commit.
- Do not amend published commits.
- Do not force push without explicit approval.
- Do not commit `.env`, credentials, or secrets.

## What NOT to Do

- Do not add dependencies without justification. Prefer stdlib/builtins first.
- Do not refactor code adjacent to your change "while you're in there."
- Do not add backwards-compatibility shims, re-exports, or `_unused` renames.
- Do not create README, docs, or markdown files unless explicitly asked.
- Do not guess URLs or API endpoints — use what exists or ask.
- Do not retry failing commands in a loop — diagnose the root cause.

## AI Agent Instructions

- Read files before editing them. Always.
- Use dedicated tools (Read, Edit, Grep, Glob) over shell equivalents.
- Parallelize independent operations.
- When blocked, reason about alternatives before escalating.
- When a task is done, it's done. Don't gold-plate.
