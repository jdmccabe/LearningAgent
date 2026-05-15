from __future__ import annotations

import warnings
from typing import Any

from learning_agent.core.workflow import Workflow, WorkflowState


def run_langgraph_workflow(workflow: Workflow, state: WorkflowState) -> WorkflowState:
    """Run a Workflow through LangGraph."""

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"Core Pydantic V1 functionality isn't compatible with Python 3\.14 or greater\.",
                category=UserWarning,
            )
            from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph is not installed. Install the project dependencies with "
            "`pip install -e .`, or select the built-in fallback engine."
        ) from exc

    graph = StateGraph(dict)
    for node in workflow.nodes:
        graph.add_node(node.name, node.run)
    previous: Any = START
    for node in workflow.nodes:
        graph.add_edge(previous, node.name)
        previous = node.name
    graph.add_edge(previous, END)
    app = graph.compile()
    result = app.invoke(dict(state))
    return dict(result)
