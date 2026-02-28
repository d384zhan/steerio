"""Compliance report generation from audit logs.

Generates structured reports suitable for regulatory review,
internal compliance teams, or incident post-mortems.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ComplianceReport:
    """Structured compliance report generated from audit entries."""

    session_start: float = 0.0
    session_end: float = 0.0
    total_entries: int = 0
    total_calls: int = 0
    call_ids: list[str] = field(default_factory=list)
    # Verdict breakdown
    total_verdicts: int = 0
    safe_verdicts: int = 0
    unsafe_verdicts: int = 0
    blocks: int = 0
    escalations: int = 0
    modifications: int = 0
    # Interventions
    operator_interventions: int = 0
    guidance_requests: int = 0
    guidance_responses: int = 0
    # Risk distribution
    risk_counts: dict[str, int] = field(default_factory=lambda: {
        "none": 0, "low": 0, "medium": 0, "high": 0, "critical": 0,
    })
    # Policy rules that fired
    rule_triggers: dict[str, int] = field(default_factory=dict)
    # Flagged entries (for detailed review)
    flagged_entries: list[dict] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        if not self.session_start or not self.session_end:
            return 0.0
        return self.session_end - self.session_start

    @property
    def block_rate(self) -> float:
        return self.blocks / self.total_verdicts if self.total_verdicts else 0.0

    @property
    def intervention_rate(self) -> float:
        return self.operator_interventions / self.total_calls if self.total_calls else 0.0

    def print_summary(self) -> None:
        mins = self.duration_seconds / 60
        print(f"\n{'='*60}")
        print(f"  COMPLIANCE REPORT")
        print(f"{'='*60}")
        print(f"  Duration:             {mins:.1f} minutes")
        print(f"  Total calls:          {self.total_calls}")
        print(f"  Total verdicts:       {self.total_verdicts}")
        print(f"  Safe verdicts:        {self.safe_verdicts}")
        print(f"  Unsafe verdicts:      {self.unsafe_verdicts}")
        print(f"  Block rate:           {self.block_rate:.1%}")
        print(f"  Blocks:               {self.blocks}")
        print(f"  Escalations:          {self.escalations}")
        print(f"  Operator actions:     {self.operator_interventions}")
        print(f"  Guidance exchanges:   {self.guidance_responses}/{self.guidance_requests}")

        if self.risk_counts:
            print(f"\n  Risk Distribution:")
            for level, count in self.risk_counts.items():
                bar = "#" * min(count, 40)
                if count > 0:
                    print(f"    {level:>10}: {count:3d} {bar}")

        if self.rule_triggers:
            print(f"\n  Top Policy Rules Triggered:")
            for rule, count in sorted(self.rule_triggers.items(), key=lambda x: -x[1])[:10]:
                print(f"    {count:3d}x  {rule}")

        if self.flagged_entries:
            print(f"\n  Flagged Entries ({len(self.flagged_entries)}):")
            for entry in self.flagged_entries[:5]:
                print(f"    [{entry.get('risk_level', '?')}] {entry.get('event_type', '?')}: {entry.get('reasoning', '')[:80]}")

        print(f"{'='*60}\n")

    def to_dict(self) -> dict:
        return {
            "duration_seconds": round(self.duration_seconds, 1),
            "total_calls": self.total_calls,
            "total_verdicts": self.total_verdicts,
            "safe_verdicts": self.safe_verdicts,
            "unsafe_verdicts": self.unsafe_verdicts,
            "block_rate": round(self.block_rate, 4),
            "blocks": self.blocks,
            "escalations": self.escalations,
            "operator_interventions": self.operator_interventions,
            "guidance_requests": self.guidance_requests,
            "guidance_responses": self.guidance_responses,
            "risk_counts": self.risk_counts,
            "rule_triggers": self.rule_triggers,
        }


def generate_report(audit_path: str | Path) -> ComplianceReport:
    """Generate a compliance report from an audit log file."""
    report = ComplianceReport()
    seen_calls = set()

    with open(audit_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            report.total_entries += 1

            ts = entry.get("timestamp", 0)
            event = entry.get("event_type", "")
            call_id = entry.get("call_id", "")

            if event == "audit_session_start":
                report.session_start = ts
            elif event == "audit_session_end":
                report.session_end = ts

            if call_id and call_id not in seen_calls:
                seen_calls.add(call_id)
                report.call_ids.append(call_id)

            if event == "verdict":
                report.total_verdicts += 1
                risk = entry.get("risk_level", "none")
                action = entry.get("action_taken", "continue")

                report.risk_counts[risk] = report.risk_counts.get(risk, 0) + 1

                if action == "block":
                    report.blocks += 1
                    report.unsafe_verdicts += 1
                elif action == "escalate":
                    report.escalations += 1
                    report.unsafe_verdicts += 1
                elif action == "modify":
                    report.modifications += 1
                    report.unsafe_verdicts += 1
                else:
                    report.safe_verdicts += 1

                rule = entry.get("policy_rule", "")
                if rule:
                    report.rule_triggers[rule] = report.rule_triggers.get(rule, 0) + 1

                # Flag high/critical entries for review
                if risk in ("high", "critical"):
                    report.flagged_entries.append(entry)

            elif event == "escalation":
                report.escalations += 1
                report.flagged_entries.append(entry)

            elif event.startswith("intervention_"):
                report.operator_interventions += 1

            elif event == "guidance_request":
                report.guidance_requests += 1

            elif event == "guidance_response":
                report.guidance_responses += 1

    report.total_calls = len(seen_calls)
    return report
