from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from learning_agent.core.documents import load_document
from learning_agent.core.graph import Edge, Node, PropertyGraph
from learning_agent.core.langgraph_workflow import run_langgraph_workflow
from learning_agent.core.models import ModelAdapter, NoOpModel
from learning_agent.core.workflow import Workflow, WorkflowNode, WorkflowState
from learning_agent.tasks.rvm.parsing import parse_requirements
from learning_agent.tasks.rvm.policies import RvmPolicy
from learning_agent.tasks.rvm.schema import Evidence, ImpactReport, Requirement, RvmDecision


def build_rvm_workflow(
    model: ModelAdapter | None = None, policy: RvmPolicy | None = None
) -> Workflow:
    context = {"model": model or NoOpModel(), "policy": policy or RvmPolicy()}
    return Workflow(
        [
            WorkflowNode("load_inputs", lambda s: _load_inputs(s, context)),
            WorkflowNode("build_graph", _build_graph),
            WorkflowNode("decide_applicability", lambda s: _decide_applicability(s, context)),
            WorkflowNode("plan_verification", lambda s: _plan_verification(s, context)),
            WorkflowNode("link_traces", _link_traces),
            WorkflowNode("analyze_impacts", _analyze_impacts),
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
    engine: str = "default",
) -> dict[str, Any]:
    workflow = build_rvm_workflow(model=model, policy=policy)
    initial_state = {
        "standard_paths": [str(p) for p in standard_paths],
        "project_paths": [str(p) for p in project_paths],
        "changed_requirement_ids": changed_requirement_ids or [],
    }
    if engine == "langgraph":
        return run_langgraph_workflow(workflow, initial_state)
    if engine != "default":
        raise ValueError(f"Unknown workflow engine '{engine}'.")
    return workflow.run(initial_state)


def _load_inputs(state: WorkflowState, context: dict[str, Any]) -> WorkflowState:
    standards: list[Requirement] = []
    project_texts: list[dict[str, str]] = []
    for path in state["standard_paths"]:
        standards.extend(parse_requirements(path))
    for path in state["project_paths"]:
        document = load_document(path)
        project_texts.append({"path": document.path, "text": document.text})
    state.update({"requirements": standards, "project_texts": project_texts})
    return state


def _build_graph(state: WorkflowState) -> WorkflowState:
    graph = PropertyGraph()
    for req in state["requirements"]:
        graph.add_node(Node(req.id, "requirement", req.to_dict()))
        if req.parent_id:
            graph.add_edge(Edge(req.parent_id, req.id, "decomposes_to"))
    state["graph"] = graph
    return state


def _decide_applicability(state: WorkflowState, context: dict[str, Any]) -> WorkflowState:
    policy: RvmPolicy = context["policy"]
    project_corpus = "\n".join(item["text"] for item in state["project_texts"])
    project_lower = project_corpus.lower()
    decisions: dict[str, RvmDecision] = {}
    for req in state["requirements"]:
        req_lower = req.text.lower()
        evidence: list[Evidence] = []
        applicability = "unknown"
        confidence = 0.25
        rationale = "No strong applicability signal found in the project context."

        matched_na, na_evidence = _matched_exclusion(req.text, state["project_texts"], policy)
        if matched_na:
            applicability = "not_applicable"
            confidence = 0.65
            rationale = f"Matched not-applicable signal(s): {', '.join(matched_na)}."
            evidence.append(na_evidence)
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

        decisions[req.id] = RvmDecision(
            requirement_id=req.id,
            applicability=applicability,  # type: ignore[arg-type]
            verification_method="unknown",
            rationale=rationale,
            evidence=evidence,
            confidence=confidence,
        )
    state["decisions"] = decisions
    return state


def _plan_verification(state: WorkflowState, context: dict[str, Any]) -> WorkflowState:
    policy: RvmPolicy = context["policy"]
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
    return state


def _link_traces(state: WorkflowState) -> WorkflowState:
    graph: PropertyGraph = state["graph"]
    decisions: dict[str, RvmDecision] = state["decisions"]
    requirements: list[Requirement] = state["requirements"]
    by_id = {req.id: req for req in requirements}
    for req in requirements:
        decision = decisions[req.id]
        if req.parent_id and req.parent_id in by_id:
            decision.trace_links.append(req.parent_id)
        for other in requirements:
            if other.id == req.id:
                continue
            if _jaccard(_tokens(req.text), _tokens(other.text)) >= 0.35:
                graph.add_edge(Edge(req.id, other.id, "related_to", {"reason": "lexical_similarity"}))
                decision.trace_links.append(other.id)
    return state


def _analyze_impacts(state: WorkflowState) -> WorkflowState:
    graph: PropertyGraph = state["graph"]
    impacts: list[ImpactReport] = []
    for req_id in state.get("changed_requirement_ids", []):
        impacted = graph.descendants(req_id, kinds=["decomposes_to", "related_to"])
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
    return state


def _serialize(state: WorkflowState) -> WorkflowState:
    graph: PropertyGraph = state["graph"]
    state["result"] = {
        "decisions": [d.to_dict() for d in state["decisions"].values()],
        "impacts": [i.to_dict() for i in state["impacts"]],
        "audit_findings": state["audit_findings"],
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
