from __future__ import annotations

import json
from pathlib import Path

from learning_agent.core.embeddings import HashingEmbedder
from learning_agent.core.memory import CorrectionMemory, CorrectionPair, HybridMemoryStore, default_memory_paths
from learning_agent.tasks.rvm.evaluation import evaluate_rvm
from learning_agent.tasks.rvm.workflow import review_rvm


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "out" / "test_rvm_workflow"


def test_review_rvm_runs_offline() -> None:
    result = review_rvm(
        [ROOT / "examples" / "standards.csv"],
        [ROOT / "examples" / "project.txt"],
        ["STD-001"],
    )
    decisions = {
        item["requirement_id"]: item
        for item in result["result"]["decisions"]
    }
    assert decisions["STD-002"]["applicability"] == "not_applicable"
    assert decisions["STD-004"]["verification_method"] == "test"
    assert result["result"]["impacts"][0]["changed_requirement_id"] == "STD-001"
    assert "STD-001.1" in result["result"]["impacts"][0]["impacted_requirement_ids"]


def test_review_rvm_uses_hybrid_memory_for_canonical_evidence_and_graph() -> None:
    _clean_scratch()
    workspace = SCRATCH / "workspace"
    memory_root = SCRATCH / "memory"
    embedder = HashingEmbedder(dimensions=64)
    paths = default_memory_paths(workspace=workspace, root=memory_root)
    CorrectionMemory(paths.crystallized_store, embedder).add_pairs(
        [
            CorrectionPair(
                task="rvm_decision",
                input_text="The system shall encrypt all wireless communication links.",
                bad_output="applicable",
                corrected_output="applicability=not_applicable; verification_method=other; trace_links=",
                rationale="Known project family excludes wireless communication.",
            )
        ]
    )

    result = review_rvm(
        [ROOT / "examples" / "standards.csv"],
        [ROOT / "examples" / "project.txt"],
        ["STD-001"],
        workspace=workspace,
        memory_root=memory_root,
        embedder=embedder,
    )
    artifact = result["result"]["verification_artifact"]
    decisions = {item["requirement_id"]: item for item in result["result"]["decisions"]}
    relationships = HybridMemoryStore(paths.crystallized_store, embedder).relationships(
        source_id="STD-001",
        status="approved",
    )

    assert artifact["memory"]["enabled"] is True
    assert artifact["memory"]["canonical_requirement_hits"] == 5
    assert decisions["STD-002"]["evidence"][0]["source"].endswith("project.txt")
    assert "Workspace memory" in decisions["STD-002"]["evidence"][0]["reason"]
    assert any(item.target_id == "STD-001.1" for item in relationships)
    _clean_scratch()


def test_review_rvm_default_engine_is_langgraph() -> None:
    default_result = review_rvm(
        [ROOT / "examples" / "standards.csv"],
        [ROOT / "examples" / "project.txt"],
    )
    explicit_result = review_rvm(
        [ROOT / "examples" / "standards.csv"],
        [ROOT / "examples" / "project.txt"],
        engine="langgraph",
    )

    assert default_result["result"]["verification_artifact"]["decision_count"] == 5
    assert default_result["result"]["decisions"] == explicit_result["result"]["decisions"]


def test_rvm_evaluation_scores_predictions() -> None:
    result = review_rvm(
        [ROOT / "examples" / "standards.csv"],
        [ROOT / "examples" / "project.txt"],
    )
    pred = ROOT / "out" / "test_pred.json"
    pred.parent.mkdir(exist_ok=True)
    pred.write_text(json.dumps(result["result"]), encoding="utf-8")

    report = evaluate_rvm(ROOT / "examples" / "gold_rvm.csv", pred)

    assert "applicability" in report.metrics
    assert report.metrics["applicability"]["count"] == 5
    pred.unlink()


def _clean_scratch() -> None:
    if not SCRATCH.exists():
        return
    for path in sorted(SCRATCH.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    SCRATCH.rmdir()
