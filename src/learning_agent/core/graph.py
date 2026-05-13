from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class Node:
    id: str
    kind: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str
    properties: dict[str, Any] = field(default_factory=dict)


class PropertyGraph:
    """Tiny directed property graph for traceability and impact analysis."""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self._out: dict[str, list[Edge]] = defaultdict(list)
        self._in: dict[str, list[Edge]] = defaultdict(list)

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)
        self._out[edge.source].append(edge)
        self._in[edge.target].append(edge)

    def outgoing(self, node_id: str, kinds: Iterable[str] | None = None) -> list[Edge]:
        allowed = set(kinds) if kinds is not None else None
        return [e for e in self._out.get(node_id, []) if allowed is None or e.kind in allowed]

    def incoming(self, node_id: str, kinds: Iterable[str] | None = None) -> list[Edge]:
        allowed = set(kinds) if kinds is not None else None
        return [e for e in self._in.get(node_id, []) if allowed is None or e.kind in allowed]

    def descendants(self, node_id: str, kinds: Iterable[str] | None = None) -> list[str]:
        seen: set[str] = set()
        queue: deque[str] = deque([node_id])
        while queue:
            current = queue.popleft()
            for edge in self.outgoing(current, kinds):
                if edge.target not in seen:
                    seen.add(edge.target)
                    queue.append(edge.target)
        seen.discard(node_id)
        return list(seen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {"id": n.id, "kind": n.kind, "properties": n.properties}
                for n in self.nodes.values()
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "kind": e.kind,
                    "properties": e.properties,
                }
                for e in self.edges
            ],
        }

