"""Test scenario framework for evaluating safety policies.

Provides TestCase and TestSuite dataclasses used by the EvaluationHarness.
Domain-specific test data lives in demo/scenarios.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..protocol import RiskLevel


@dataclass(frozen=True)
class TestCase:
    """A single test case: an agent response with expected safety label."""

    input: str
    expected_safe: bool
    expected_risk_level: RiskLevel | None = None
    category: str = ""
    description: str = ""


@dataclass
class TestSuite:
    """A collection of test cases for a domain."""

    name: str
    domain: str
    cases: list[TestCase] = field(default_factory=list)


def load_suite(path: str | Path) -> TestSuite:
    """Load a test suite from a JSON file."""
    data = json.loads(Path(path).read_text())
    cases = [
        TestCase(
            input=c["input"],
            expected_safe=c["expected_safe"],
            expected_risk_level=RiskLevel(c["expected_risk_level"]) if c.get("expected_risk_level") else None,
            category=c.get("category", ""),
            description=c.get("description", ""),
        )
        for c in data["cases"]
    ]
    return TestSuite(name=data["name"], domain=data.get("domain", ""), cases=cases)
