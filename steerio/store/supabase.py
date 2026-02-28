"""Supabase-backed policy store — loads policies, rules, and judge config at startup/reload."""

from __future__ import annotations

import logging
from typing import Any

from ..policies.base import EscalationConfig, Policy

logger = logging.getLogger(__name__)


class SupabaseStore:
    """Sync Supabase client for loading policies and judge config.

    Called at startup and on operator reload — not per-chunk.
    The `supabase` package is imported lazily so it stays an optional dependency.
    """

    def __init__(self, url: str, key: str):
        try:
            from supabase import create_client
        except ImportError as e:
            raise ImportError(
                "supabase package required: pip install 'steerio[supabase]'"
            ) from e
        self._client = create_client(url, key)

    def load_policy(self, policy_id: str) -> Policy:
        row = (
            self._client.table("policies")
            .select("*, judges(*)")
            .eq("id", policy_id)
            .single()
            .execute()
        ).data

        judge = row.get("judges") or {}
        judge_prompt = self._build_effective_prompt(
            judge.get("system_prompt", ""),
            judge.get("knowledge_base", ""),
        )

        esc_raw = row.get("escalation_config")
        escalation = EscalationConfig(**esc_raw) if esc_raw else None

        return Policy(
            name=row["name"],
            domain=row["domain"],
            description=row.get("description", ""),
            judge_prompt=judge_prompt,
            version=row.get("version", "1.0"),
            escalation=escalation,
        )

    def load_judge_config(self, judge_id: str) -> dict[str, Any]:
        row = (
            self._client.table("judges")
            .select("*")
            .eq("id", judge_id)
            .single()
            .execute()
        ).data
        return {
            "name": row["name"],
            "effective_prompt": self._build_effective_prompt(
                row.get("system_prompt", ""),
                row.get("knowledge_base", ""),
            ),
            "eval_threshold_chars": row.get("eval_threshold_chars", 100),
        }

    def list_policies(self, domain: str = "") -> list[dict[str, Any]]:
        query = self._client.table("policies").select("id, name, domain, version, active")
        if domain:
            query = query.eq("domain", domain)
        return query.eq("active", True).execute().data

    def save_policy(self, policy: Policy) -> str:
        row = {
            "name": policy.name,
            "domain": policy.domain,
            "description": policy.description,
            "version": policy.version,
        }
        if policy.escalation:
            row["escalation_config"] = {
                "max_consecutive_flags": policy.escalation.max_consecutive_flags,
                "auto_escalate_on_critical": policy.escalation.auto_escalate_on_critical,
                "trend_escalation": policy.escalation.trend_escalation,
            }
        result = self._client.table("policies").insert(row).execute()
        return result.data[0]["id"]

    @staticmethod
    def _build_effective_prompt(system_prompt: str, knowledge_base: str) -> str:
        if not knowledge_base:
            return system_prompt
        return f"{system_prompt}\n\n--- KNOWLEDGE BASE ---\n{knowledge_base}"
