from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


WorkflowState = dict[str, Any]
NodeFn = Callable[[WorkflowState], WorkflowState]


@dataclass(frozen=True)
class WorkflowNode:
    name: str
    run: NodeFn


@dataclass
class WorkflowTrace:
    steps: list[dict[str, Any]] = field(default_factory=list)

    def add(self, node: str, before_keys: list[str], after_keys: list[str]) -> None:
        self.steps.append(
            {
                "node": node,
                "before_keys": before_keys,
                "after_keys": after_keys,
                "new_keys": sorted(set(after_keys) - set(before_keys)),
            }
        )


class Workflow:
    """Simple sequential workflow runner.

    The node API is intentionally small so this can later be mapped onto
    LangGraph, Prefect, Airflow, custom queues, or a plain script.
    """

    def __init__(self, nodes: list[WorkflowNode]) -> None:
        self.nodes = nodes

    def run(self, state: WorkflowState) -> WorkflowState:
        trace = WorkflowTrace()
        current = dict(state)
        for node in self.nodes:
            before = sorted(current.keys())
            current = node.run(current)
            after = sorted(current.keys())
            trace.add(node.name, before, after)
        current["trace"] = trace.steps
        return current

