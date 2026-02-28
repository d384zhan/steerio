"""
Steerio Policy Evaluation Demo — Pulls policies from Supabase.

Loads all active policies from the database and verifies they load correctly.
Evaluation is now fully LLM-judge based (no regex rules).

Run:
    python demo/demo_eval.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from steerio.store import SupabaseStore

load_dotenv(Path(__file__).parent / ".env")

store = SupabaseStore(
    url=os.environ["SUPABASE_URL"],
    key=os.environ["SUPABASE_ANON_KEY"],
)

print("Loading policies from Supabase...\n")

for entry in store.list_policies():
    policy = store.load_policy(entry["id"])
    has_judge = bool(policy.judge_prompt)
    has_escalation = policy.escalation is not None
    print(f"  {policy.name} ({policy.domain})")
    print(f"    Judge prompt: {'yes' if has_judge else 'MISSING'} ({len(policy.judge_prompt)} chars)")
    print(f"    Escalation: {'configured' if has_escalation else 'none'}")
    print()

print("All policies loaded successfully.")
