"""
schemas/contract.py — Universal I/O contract for all agents.

Every agent receives a TaskRequest and returns an AgentResponse.
This is the ONLY interface the God Agent uses — agents are interchangeable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TaskRequest:
    """
    What the God Agent sends to any worker agent.

    task    : natural language description of what to do
    context : optional prior results from earlier agents in a chain
    metadata: agent-specific hints (workspace path, model override, etc.)
    """
    task: str
    context: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_context(self, ctx: str) -> "TaskRequest":
        """Return a new TaskRequest with appended context."""
        combined = f"{self.context}\n\n{ctx}".strip() if self.context else ctx
        return TaskRequest(task=self.task, context=combined, metadata=self.metadata)


@dataclass
class AgentResponse:
    """
    What every worker agent returns to the God Agent.

    status     : "success" | "fail" | "partial"
    result     : the agent's output (plain text, markdown, or stringified data)
    next_hint  : optional suggestion for what the next agent should do with this result
    agent      : which agent produced this response
    error      : populated only on failure
    """
    status: str          # "success" | "fail" | "partial"
    result: str
    next_hint: str = ""
    agent: str = ""
    error: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status == "success"

    @property
    def failed(self) -> bool:
        return self.status == "fail"
