from __future__ import annotations

from typing import Any

from learning_agent.core.workflow import Workflow, WorkflowState


def run_langgraph_workflow(workflow: Workflow, state: WorkflowState) -> WorkflowState:
    """Run a Workflow through LangGraph when the optional package is installed."""

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph is not installed. Install the optional graph dependencies "
            "or run the default workflow engine."
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

