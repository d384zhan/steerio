"""
Steerio Policy Evaluation Demo — Pulls policies from Supabase.

Loads all active policies from the database and evaluates them against
the matching test suites. This is what production usage looks like:
policies are managed in Supabase, not hardcoded.

Run:
    python demo/demo_eval.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from steerio.compliance import EvaluationHarness
from steerio.store import SupabaseStore

from demo.scenarios import financial_suite, legal_suite, medical_suite

load_dotenv(Path(__file__).parent / ".env")

store = SupabaseStore(
    url=os.environ["SUPABASE_URL"],
    key=os.environ["SUPABASE_ANON_KEY"],
)

# Map domain → test suite
SUITES = {
    "healthcare": medical_suite,
    "finance": financial_suite,
    "legal": legal_suite,
}

harness = EvaluationHarness()
reports = []

print("Loading policies from Supabase...\n")

for entry in store.list_policies():
    policy = store.load_policy(entry["id"])
    print(f"  Loaded: {policy.name} ({policy.domain}) — {len(policy.rules)} rules")

    suite_fn = SUITES.get(policy.domain)
    if not suite_fn:
        print(f"  (no test suite for domain '{policy.domain}', skipping eval)")
        continue

    report = harness.run_rules(policy, suite_fn())
    report.print_summary()
    reports.append(report)

print("="*60)
print("  AGGREGATE RESULTS")
print("="*60)
for report in reports:
    status = "PASS" if report.false_negatives == 0 else "FAIL"
    print(f"  [{status}] {report.policy_name}: {report.accuracy:.0%} accuracy, "
          f"F1={report.f1:.2f}, "
          f"missed={report.false_negatives}, "
          f"false_alarms={report.false_positives}")
print("="*60)
