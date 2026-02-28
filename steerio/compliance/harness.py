"""Evaluation harness — test safety policies against known scenarios.

Run test cases through a policy's quick_check rules and optionally through
the LLM judge, then report accuracy metrics. This is how you validate
that your safety policies actually work before deploying to production.

Usage:
    from steerio.compliance import EvaluationHarness, TestSuite
    from steerio.policies import Policy

    harness = EvaluationHarness()
    report = harness.run_rules(my_policy, my_suite)
    report.print_summary()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..policies.base import Policy
from ..protocol import RiskLevel
from .scenarios import TestCase, TestSuite


@dataclass
class EvalResult:
    """Result of evaluating a single test case."""

    test_case: TestCase
    caught: bool  # Did the policy catch it (for unsafe) / pass it (for safe)?
    correct: bool  # Did the policy make the right call?
    verdict_risk: str = ""  # Risk level from the verdict, if caught
    verdict_action: str = ""  # Action from the verdict, if caught
    latency_ms: float = 0.0
    rule_name: str = ""  # Which rule fired, if any


@dataclass
class EvalReport:
    """Aggregate results from running a test suite against a policy."""

    policy_name: str
    suite_name: str
    results: list[EvalResult] = field(default_factory=list)
    run_at: float = field(default_factory=time.time)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def correct(self) -> int:
        return sum(1 for r in self.results if r.correct)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def true_positives(self) -> int:
        """Unsafe correctly caught."""
        return sum(1 for r in self.results if not r.test_case.expected_safe and r.caught)

    @property
    def false_negatives(self) -> int:
        """Unsafe missed (most dangerous failure mode)."""
        return sum(1 for r in self.results if not r.test_case.expected_safe and not r.caught)

    @property
    def true_negatives(self) -> int:
        """Safe correctly passed."""
        return sum(1 for r in self.results if r.test_case.expected_safe and not r.caught)

    @property
    def false_positives(self) -> int:
        """Safe incorrectly flagged."""
        return sum(1 for r in self.results if r.test_case.expected_safe and r.caught)

    @property
    def precision(self) -> float:
        tp = self.true_positives
        fp = self.false_positives
        return tp / (tp + fp) if (tp + fp) else 1.0

    @property
    def recall(self) -> float:
        tp = self.true_positives
        fn = self.false_negatives
        return tp / (tp + fn) if (tp + fn) else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def print_summary(self) -> None:
        print(f"\n{'='*60}")
        print(f"  EVAL: {self.policy_name} vs {self.suite_name}")
        print(f"{'='*60}")
        print(f"  Total cases:     {self.total}")
        print(f"  Accuracy:        {self.accuracy:.1%}")
        print(f"  Precision:       {self.precision:.1%}")
        print(f"  Recall:          {self.recall:.1%}")
        print(f"  F1 Score:        {self.f1:.1%}")
        print(f"  True Positives:  {self.true_positives}")
        print(f"  False Negatives: {self.false_negatives}  ← DANGEROUS (missed unsafe)")
        print(f"  True Negatives:  {self.true_negatives}")
        print(f"  False Positives: {self.false_positives}")

        if self.false_negatives > 0:
            print(f"\n  MISSED UNSAFE CASES:")
            for r in self.results:
                if not r.test_case.expected_safe and not r.caught:
                    print(f"    - [{r.test_case.category}] {r.test_case.description}")
                    print(f"      Input: \"{r.test_case.input[:80]}...\"")

        if self.false_positives > 0:
            print(f"\n  FALSE ALARMS:")
            for r in self.results:
                if r.test_case.expected_safe and r.caught:
                    print(f"    - [{r.test_case.category}] {r.test_case.description}")
                    print(f"      Input: \"{r.test_case.input[:80]}...\"")
                    print(f"      Rule:  {r.rule_name}")

        print(f"{'='*60}\n")

    def to_dict(self) -> dict:
        return {
            "policy": self.policy_name,
            "suite": self.suite_name,
            "total": self.total,
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "true_positives": self.true_positives,
            "false_negatives": self.false_negatives,
            "true_negatives": self.true_negatives,
            "false_positives": self.false_positives,
        }


class EvaluationHarness:
    """Runs test suites against policies and produces eval reports."""

    def run_rules(self, policy: Policy, suite: TestSuite) -> EvalReport:
        """Run only rule-based checks (fast, no LLM needed).

        This validates your regex/keyword rules against known test cases.
        Use this in CI/CD to catch policy regressions.
        """
        report = EvalReport(policy_name=policy.name, suite_name=suite.name)

        for case in suite.cases:
            start = time.monotonic()
            verdict = policy.quick_check(case.input)
            elapsed = (time.monotonic() - start) * 1000

            caught = verdict is not None
            # Correct if: unsafe input caught, OR safe input passed
            correct = (not case.expected_safe and caught) or (case.expected_safe and not caught)

            result = EvalResult(
                test_case=case,
                caught=caught,
                correct=correct,
                verdict_risk=verdict.risk_level.value if verdict else "",
                verdict_action=verdict.action.value if verdict else "",
                latency_ms=elapsed,
                rule_name=verdict.reasoning.split("[")[1].split("]")[0] if verdict else "",
            )
            report.results.append(result)

        return report
