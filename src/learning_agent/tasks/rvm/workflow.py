from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learning_agent.core.documents import load_document
from learning_agent.core.embeddings import Embedder, HashingEmbedder
from learning_agent.core.graph import Edge, Node, PropertyGraph
from learning_agent.core.langgraph_workflow import run_langgraph_workflow
from learning_agent.core.memory import (
    CorrectionMemory,
    GraphRelationship,
    ReferenceMemory,
    WorkspaceMemory,
    default_memory_paths,
)
from learning_agent.core.models import ModelAdapter, NoOpModel
from learning_agent.core.vector_store import SearchResult
from learning_agent.core.workflow import Workflow, WorkflowNode, WorkflowState
from learning_agent.tasks.rvm.agents import AGENT_SET_ID, agent_versions
from learning_agent.tasks.rvm.compliance import audit_compliance
from learning_agent.tasks.rvm.parsing import parse_requirements
from learning_agent.tasks.rvm.policies import RvmPolicy
from learning_agent.tasks.rvm.schema import Evidence, ImpactReport, Requirement, RvmDecision


@dataclass
class RvmMemoryContext:
    reference: ReferenceMemory
    corrections: CorrectionMemory
    workspace: WorkspaceMemory
    workspace_id: str
    root: str
    shared_store: str
    workspace_store: str
    index_inputs: bool = True


def build_rvm_workflow(
    model: ModelAdapter | None = None,
    policy: RvmPolicy | None = None,
    memory: RvmMemoryContext | None = None,
) -> Workflow:
    context = {"model": model or NoOpModel(), "policy": policy or RvmPolicy(), "memory": memory}
    return Workflow(
        [
            WorkflowNode("load_inputs", lambda s: _load_inputs(s, context)),
            WorkflowNode("build_graph", lambda s: _build_graph(s, context)),
            WorkflowNode("decide_applicability", lambda s: _decide_applicability(s, context)),
            WorkflowNode("plan_verification", lambda s: _plan_verification(s, context)),
            WorkflowNode("link_traces", lambda s: _link_traces(s, context)),
            WorkflowNode("analyze_impacts", lambda s: _analyze_impacts(s, context)),
            WorkflowNode("audit", lambda s: _audit(s, context)),
            WorkflowNode("serialize", _serialize),
        ]
    )


def review_rvm(
    standard_paths: list[str | Path],
    project_paths: list[str | Path],
    changed_requirement_ids: list[str] | None = None,
    model: ModelAdapter | None = None,
    policy: RvmPolicy | None = None,
    engine: str = "langgraph",
    workspace: str | Path | None = None,
    memory_root: str | Path | None = None,
    embedder: Embedder | None = None,
    use_memory: bool = True,
    index_memory: bool = True,
) -> dict[str, Any]:
    memory = (
        build_rvm_memory_context(
            workspace=workspace,
            memory_root=memory_root,
            embedder=embedder,
            index_inputs=index_memory,
        )
        if use_memory
        else None
    )
    workflow = build_rvm_workflow(model=model, policy=policy, memory=memory)
    initial_state = {
        "standard_paths": [str(p) for p in standard_paths],
        "project_paths": [str(p) for p in project_paths],
        "changed_requirement_ids": changed_requirement_ids or [],
    }
    if engine == "langgraph":
        return run_langgraph_workflow(workflow, initial_state)
    if engine in {"default", "built-in", "builtin"}:
        return workflow.run(initial_state)
    else:
        raise ValueError(f"Unknown workflow engine '{engine}'.")


def build_rvm_memory_context(
    workspace: str | Path | None = None,
    memory_root: str | Path | None = None,
    embedder: Embedder | None = None,
    index_inputs: bool = True,
) -> RvmMemoryContext:
    paths = default_memory_paths(workspace=workspace, root=memory_root)
    chosen_embedder = embedder or HashingEmbedder()
    workspace_memory = WorkspaceMemory(workspace, memory_root, chosen_embedder)
    return RvmMemoryContext(
        reference=ReferenceMemory(paths.reference_store, chosen_embedder),
        corrections=CorrectionMemory(paths.crystallized_store, chosen_embedder),
        workspace=workspace_memory,
        workspace_id=workspace_memory.workspace_id,
        root=str(paths.root),
        shared_store=str(paths.reference_store),
        workspace_store=str(paths.working_store),
        index_inputs=index_inputs,
    )


def _load_inputs(state: WorkflowState, context: dict[str, Any]) -> WorkflowState:
    standards: list[Requirement] = []
    project_texts: list[dict[str, str]] = []
    for path in state["standard_paths"]:
        standards.extend(parse_requirements(path))
    for path in state["project_paths"]:
        document = load_document(path)
        project_texts.append({"path": document.path, "text": document.text})
    memory: RvmMemoryContext | None = context.get("memory")
    memory_summary: dict[str, Any] = {"enabled": bool(memory)}
    if memory is not None:
        reference_ids: list[str] = []
        project_ids: list[str] = []
        if memory.index_inputs:
            reference_ids = memory.reference.index_files(state["standard_paths"])
            project_ids = memory.workspace.index_project_files(state["project_paths"])
        canonical_hits = 0
        for req in standards:
            canonical = memory.reference.get_requirement(req.id)
            if canonical is None:
                continue
            canonical_hits += 1
            req.text = canonical.text
            req.metadata.update(
                {
                    "canonical_record_id": canonical.id,
                    "canonical_source_hash": canonical.metadata.get("source_hash", ""),
                    "canonical_source": canonical.metadata.get("source", ""),
                }
            )
        memory_summary.update(
            {
                "root": memory.root,
                "shared_store": memory.shared_store,
                "workspace_store": memory.workspace_store,
                "workspace_id": memory.workspace_id,
                "reference_records_indexed": len(reference_ids),
                "project_records_indexed": len(project_ids),
                "canonical_requirement_hits": canonical_hits,
            }
        )
    state.update({"requirements": standards, "project_texts": project_texts})
    state["memory_summary"] = memory_summary
    return state


def _build_graph(state: WorkflowState, context: dict[str, Any]) -> WorkflowState:
    graph = PropertyGraph()
    memory: RvmMemoryContext | None = context.get("memory")
    for req in state["requirements"]:
        graph.add_node(Node(req.id, "requirement", req.to_dict()))
        if req.parent_id:
            graph.add_edge(Edge(req.parent_id, req.id, "decomposes_to"))
    if memory is not None:
        memory.corrections.store.add_relationships(
            [
                GraphRelationship(
                    source_id=edge.source,
                    target_id=edge.target,
                    kind=edge.kind,
                    status="approved" if edge.kind == "decomposes_to" else "candidate",
                    metadata=edge.properties,
                )
                for edge in graph.edges
            ]
        )
    state["graph"] = graph
    return state


def _decide_applicability(state: WorkflowState, context: dict[str, Any]) -> WorkflowState:
    policy: RvmPolicy = context["policy"]
    memory: RvmMemoryContext | None = context.get("memory")
    project_corpus = "\n".join(item["text"] for item in state["project_texts"])
    decisions: dict[str, RvmDecision] = {}
    for req in state["requirements"]:
        req_lower = req.text.lower()
        evidence: list[Evidence] = []
        applicability = "unknown"
        confidence = 0.25
        rationale = "No strong applicability signal found in the project context."

        memory_match = _memory_exclusion(req, memory, policy) if memory else None
        matched_na, na_evidence = (
            memory_match if memory_match else _matched_exclusion(req.text, state["project_texts"], policy)
        )
        if matched_na:
            applicability = "not_applicable"
            confidence = 0.72 if memory_match else 0.65
            rationale = f"Matched not-applicable signal(s): {', '.join(matched_na)}."
            evidence.append(na_evidence)
        elif memory and (positive_evidence := _memory_positive_evidence(req, memory)):
            applicability = "applicable"
            confidence = 0.62
            rationale = "Requirement terminology overlaps with canonical workspace memory and no exclusion was found."
            evidence.append(positive_evidence)
        elif _has_positive_overlap(req.text, project_corpus):
            applicability = "applicable"
            confidence = 0.55
            rationale = "Requirement terminology overlaps with project scope and no exclusion was found."
            evidence.append(
                Evidence(
                    source="project_corpus",
                    quote=_best_overlap_sentence(req.text, project_corpus),
                    reason="Best lexical overlap with requirement text.",
                )
            )

        if applicability != "not_applicable":
            conditional_terms = _matched_terms(req_lower, policy.conditional_terms)
            if conditional_terms and confidence < 0.75:
                applicability = "conditional"
                confidence = max(confidence, 0.45)
                rationale = f"Requirement contains conditional scope term(s): {', '.join(conditional_terms)}."

        decision = RvmDecision(
            requirement_id=req.id,
            applicability=applicability,  # type: ignore[arg-type]
            verification_method="unknown",
            rationale=rationale,
            assurance_standard=req.assurance_standard,
            dal=req.dal,
            lifecycle_objectives=list(req.lifecycle_objectives),
            evidence=evidence,
            confidence=confidence,
        )
        if memory:
            _apply_correction_hint(req, decision, memory)
        decisions[req.id] = decision
    state["decisions"] = decisions
    return state


def _plan_verification(state: WorkflowState, context: dict[str, Any]) -> WorkflowState:
    policy: RvmPolicy = context["policy"]
    memory: RvmMemoryContext | None = context.get("memory")
    decisions: dict[str, RvmDecision] = state["decisions"]
    requirements: list[Requirement] = state["requirements"]
    for req in requirements:
        decision = decisions[req.id]
        if decision.applicability == "not_applicable":
            decision.verification_method = "other"
            decision.assumptions.append("No verification required if non-applicability is accepted.")
            continue
        scores: dict[str, int] = {}
        text = req.text.lower()
        for method, terms in policy.verification_keywords.items():
            scores[method] = sum(1 for term in terms if term in text)
        method, score = max(scores.items(), key=lambda item: item[1])
        if score == 0:
            method = "inspection" if len(req.text.split()) < 18 else "analysis"
            decision.confidence = min(decision.confidence, 0.45)
            decision.assumptions.append("Verification method inferred from wording, not explicit keywords.")
        else:
            decision.confidence = min(0.9, decision.confidence + 0.2)
        decision.verification_method = method  # type: ignore[assignment]
        if memory:
            _attach_verification_memory_hint(req, decision, memory)
    return state


def _link_traces(state: WorkflowState, context: dict[str, Any]) -> WorkflowState:
    graph: PropertyGraph = state["graph"]
    memory: RvmMemoryContext | None = context.get("memory")
    decisions: dict[str, RvmDecision] = state["decisions"]
    requirements: list[Requirement] = state["requirements"]
    by_id = {req.id: req for req in requirements}
    children_by_parent: dict[str, list[str]] = {}
    for req in requirements:
        if req.parent_id:
            children_by_parent.setdefault(req.parent_id, []).append(req.id)
    for req in requirements:
        decision = decisions[req.id]
        if req.parent_id and req.parent_id in by_id:
            decision.parent_ids.append(req.parent_id)
            decision.trace_links.append(req.parent_id)
        decision.child_ids.extend(children_by_parent.get(req.id, []))
        if memory is not None:
            for relationship in memory.corrections.store.relationships(
                target_id=req.id,
                kind="decomposes_to",
                status="approved",
            ):
                if relationship.source_id not in decision.parent_ids:
                    decision.parent_ids.append(relationship.source_id)
                    decision.trace_links.append(relationship.source_id)
            for relationship in memory.corrections.store.relationships(
                source_id=req.id,
                kind="decomposes_to",
                status="approved",
            ):
                if relationship.target_id not in decision.child_ids:
                    decision.child_ids.append(relationship.target_id)
        for other in requirements:
            if other.id == req.id:
                continue
            if _jaccard(_tokens(req.text), _tokens(other.text)) >= 0.35:
                graph.add_edge(Edge(req.id, other.id, "related_to", {"reason": "lexical_similarity"}))
                decision.trace_links.append(other.id)
    if memory is not None:
        memory.corrections.store.add_relationships(
            [
                GraphRelationship(
                    source_id=edge.source,
                    target_id=edge.target,
                    kind=edge.kind,
                    status="approved" if edge.kind == "decomposes_to" else "candidate",
                    metadata=edge.properties,
                )
                for edge in graph.edges
            ]
        )
    return state


def _analyze_impacts(state: WorkflowState, context: dict[str, Any]) -> WorkflowState:
    graph: PropertyGraph = state["graph"]
    memory: RvmMemoryContext | None = context.get("memory")
    impacts: list[ImpactReport] = []
    for req_id in state.get("changed_requirement_ids", []):
        impacted = graph.descendants(req_id, kinds=["decomposes_to", "related_to"])
        if memory is not None:
            persisted = _memory_descendants(memory, req_id)
            impacted = sorted(set(impacted) | set(persisted))
        impacts.append(
            ImpactReport(
                changed_requirement_id=req_id,
                impacted_requirement_ids=impacted,
                impacted_verification_ids=[f"VER-{item}" for item in impacted],
                explanation=(
                    "Impact includes nested child requirements and lexically related "
                    "requirements discovered in the trace graph."
                ),
            )
        )
    state["impacts"] = impacts
    return state


def _audit(state: WorkflowState, context: dict[str, Any]) -> WorkflowState:
    policy: RvmPolicy = context["policy"]
    findings: list[dict[str, Any]] = []
    for decision in state["decisions"].values():
        if decision.confidence < policy.low_confidence_threshold:
            findings.append(
                {
                    "requirement_id": decision.requirement_id,
                    "severity": "review",
                    "message": "Low-confidence decision should be reviewed by a human.",
                }
            )
        if decision.applicability == "not_applicable" and not decision.evidence:
            findings.append(
                {
                    "requirement_id": decision.requirement_id,
                    "severity": "review",
                    "message": "Not-applicable decision is missing supporting evidence.",
                }
            )
    state["audit_findings"] = findings
    state["compliance_report"] = audit_compliance(
        list(state["decisions"].values()),
        state["requirements"],
    )
    return state


def _serialize(state: WorkflowState) -> WorkflowState:
    graph: PropertyGraph = state["graph"]
    decisions = list(state["decisions"].values())
    state["result"] = {
        "verification_artifact": {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "agent_set_id": AGENT_SET_ID,
            "agent_versions": agent_versions(),
            "standard_paths": state.get("standard_paths", []),
            "project_paths": state.get("project_paths", []),
            "requirement_count": len(state.get("requirements", [])),
            "decision_count": len(decisions),
            "graph_node_count": len(graph.nodes),
            "graph_edge_count": len(graph.edges),
            "audit_finding_count": len(state.get("audit_findings", [])),
            "compliance_passed": state["compliance_report"].passed,
            "compliance_failure_count": state["compliance_report"].failure_count,
            "changed_requirement_ids": state.get("changed_requirement_ids", []),
            "memory": state.get("memory_summary", {"enabled": False}),
        },
        "decisions": [d.to_dict() for d in decisions],
        "impacts": [i.to_dict() for i in state["impacts"]],
        "audit_findings": state["audit_findings"],
        "compliance_report": state["compliance_report"].to_dict(),
        "graph": graph.to_dict(),
    }
    return state


def _matched_terms(text: str, terms: set[str]) -> list[str]:
    matches: list[str] = []
    for term in terms:
        pattern = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])"
        if re.search(pattern, text):
            matches.append(term)
    return sorted(matches)


def _matched_exclusion(
    requirement_text: str, project_texts: list[dict[str, str]], policy: RvmPolicy
) -> tuple[list[str], Evidence]:
    req_tokens = _tokens(requirement_text)
    for item in project_texts:
        for line in item["text"].splitlines():
            line_lower = line.lower()
            terms = [
                term
                for term in _matched_terms(line_lower, policy.not_applicable_terms)
                if _tokens(term) & req_tokens
            ]
            if not terms:
                continue
            if _jaccard(req_tokens, _tokens(line)) >= 0.08:
                reason = f"Project context has scoped exclusion signal(s): {', '.join(terms)}."
                return terms, Evidence(source=item["path"], quote=line.strip(), reason=reason)
    return [], Evidence(source="project_corpus", quote="", reason="No scoped exclusion found.")


def _memory_exclusion(
    requirement: Requirement,
    memory: RvmMemoryContext | None,
    policy: RvmPolicy,
) -> tuple[list[str], Evidence] | None:
    if memory is None:
        return None
    req_tokens = _tokens(requirement.text)
    candidates = _dedupe_results(
        memory.workspace.search_text(requirement.text, top_k=5)
        + memory.workspace.search(requirement.text, top_k=5)
    )
    for result in candidates:
        for line in result.record.text.splitlines():
            line_lower = line.lower()
            terms = [
                term
                for term in _matched_terms(line_lower, policy.not_applicable_terms)
                if _tokens(term) & req_tokens
            ]
            if terms and _jaccard(req_tokens, _tokens(line)) >= 0.08:
                return (
                    terms,
                    Evidence(
                        source=str(result.record.metadata.get("source", result.record.id)),
                        quote=line.strip(),
                        reason=(
                            "Workspace memory has exact scoped exclusion signal(s): "
                            f"{', '.join(terms)}; record={result.record.id}."
                        ),
                    ),
                )
    return None


def _memory_positive_evidence(
    requirement: Requirement,
    memory: RvmMemoryContext,
) -> Evidence | None:
    req_tokens = _tokens(requirement.text)
    candidates = _dedupe_results(
        memory.workspace.search_text(requirement.text, top_k=3)
        + memory.workspace.search(requirement.text, top_k=3)
    )
    for result in candidates:
        for line in result.record.text.splitlines():
            if _jaccard(req_tokens, _tokens(line)) >= 0.08:
                return Evidence(
                    source=str(result.record.metadata.get("source", result.record.id)),
                    quote=line.strip(),
                    reason=f"Workspace memory overlap from canonical record {result.record.id}.",
                )
    return None


def _apply_correction_hint(
    requirement: Requirement,
    decision: RvmDecision,
    memory: RvmMemoryContext,
) -> None:
    results = memory.corrections.search(requirement.text, top_k=1)
    if not results or results[0].score <= 0:
        return
    corrected = str(results[0].record.metadata.get("corrected_output", ""))
    hinted_app = _field_value(corrected, "applicability")
    if hinted_app and hinted_app != decision.applicability:
        decision.assumptions.append(
            "Crystallized memory contains a similar approved correction "
            f"with applicability={hinted_app}; record={results[0].record.id}."
        )
        decision.confidence = max(decision.confidence, 0.35)


def _attach_verification_memory_hint(
    requirement: Requirement,
    decision: RvmDecision,
    memory: RvmMemoryContext,
) -> None:
    queries = [
        requirement.text,
        f"{decision.verification_method} procedure {requirement.text}",
    ]
    for query in queries:
        results = memory.reference.search_text(query, top_k=1)
        if not results:
            continue
        result = results[0]
        if result.record.metadata.get("kind") == "requirement":
            continue
        decision.assumptions.append(
            "Reference memory has a candidate verification/procedure context "
            f"at {result.record.metadata.get('source', result.record.id)} "
            f"lines {result.record.metadata.get('start_line', '')}-"
            f"{result.record.metadata.get('end_line', '')}; record={result.record.id}."
        )
        return


def _dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for result in results:
        if result.record.id in seen:
            continue
        seen.add(result.record.id)
        deduped.append(result)
    return deduped


def _memory_descendants(memory: RvmMemoryContext, node_id: str) -> list[str]:
    approved_kinds = {
        "decomposes_to",
        "verifies",
        "implements",
        "allocates_to",
        "satisfies",
        "cites",
    }
    seen: set[str] = set()
    queue = [node_id]
    while queue:
        current = queue.pop(0)
        for relationship in memory.corrections.store.relationships(source_id=current, status="approved"):
            if relationship.kind not in approved_kinds or relationship.target_id in seen:
                continue
            seen.add(relationship.target_id)
            queue.append(relationship.target_id)
    seen.discard(node_id)
    return sorted(seen)


def _field_value(text: str, field: str) -> str:
    match = re.search(rf"(?<![a-z0-9_]){re.escape(field)}=([^;\n]+)", text, re.I)
    return match.group(1).strip() if match else ""


def _tokens(text: str) -> set[str]:
    stop = {"the", "a", "an", "and", "or", "to", "of", "for", "with", "shall", "must"}
    return {
        _normalize_token(token)
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in stop
    }


def _normalize_token(token: str) -> str:
    replacements = {
        "documentation": "document",
        "documented": "document",
        "documents": "document",
        "externally": "external",
        "interfaces": "interface",
        "drawings": "drawing",
        "workflows": "workflow",
    }
    if token in replacements:
        return replacements[token]
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s"):
        return token[:-1]
    return token


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left or right else 0.0


def _has_positive_overlap(requirement: str, corpus: str) -> bool:
    req_tokens = _tokens(requirement)
    sentences = re.split(r"(?<=[.!?])\s+|\n+", corpus)
    return any(_jaccard(req_tokens, _tokens(sentence)) >= 0.08 for sentence in sentences)


def _best_overlap_sentence(requirement: str, corpus: str) -> str:
    req_tokens = _tokens(requirement)
    sentences = re.split(r"(?<=[.!?])\s+|\n+", corpus)
    if not sentences:
        return ""
    return max(sentences, key=lambda sentence: _jaccard(req_tokens, _tokens(sentence))).strip()
