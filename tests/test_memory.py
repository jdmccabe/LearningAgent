from __future__ import annotations

from pathlib import Path

from learning_agent.core.embeddings import HashingEmbedder, LlamaCppEmbedder
from learning_agent.core.memory import (
    CorrectionMemory,
    CorrectionPair,
    GraphRelationship,
    HybridMemoryStore,
    ReferenceMemory,
    WorkspaceMemory,
)


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "out" / "test_memory"


def test_reference_memory_indexes_and_searches() -> None:
    _clean_scratch()
    doc = SCRATCH / "reference.txt"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("REQ-1: The system shall encrypt wireless links.\n", encoding="utf-8")
    memory = ReferenceMemory(SCRATCH / "memory.sqlite", HashingEmbedder(dimensions=64))

    ids = memory.index_files([doc])
    results = memory.search("encrypt wireless communication", top_k=1)
    exact = memory.search_text("system shall encrypt wireless", top_k=1)
    by_id = memory.get_requirement("REQ-1")

    assert ids
    assert results[0].record.metadata["kind"] in {"reference", "requirement"}
    assert "encrypt" in results[0].record.text
    assert exact[0].record.text == "The system shall encrypt wireless links."
    assert exact[0].record.metadata["requirement_id"] == "REQ-1"
    assert exact[0].record.metadata["source_hash"]
    assert by_id is not None
    assert by_id.text == "The system shall encrypt wireless links."
    _clean_scratch()


def test_correction_memory_indexes_and_searches() -> None:
    _clean_scratch()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    memory = CorrectionMemory(SCRATCH / "memory.sqlite", HashingEmbedder(dimensions=64))
    memory.add_pairs(
        [
            CorrectionPair(
                task="applicability",
                input_text="wireless requirement",
                bad_output="applicable",
                corrected_output="not_applicable",
                rationale="Project has no wireless communication.",
            )
        ]
    )

    results = memory.search("wireless not applicable", top_k=1)
    exact = memory.search_text("Project has no wireless", top_k=1)

    assert results[0].record.metadata["kind"] == "correction"
    assert results[0].record.metadata["corrected_output"] == "not_applicable"
    assert exact[0].record.metadata["task"] == "applicability"
    _clean_scratch()


def test_workspace_memory_is_scoped_by_workspace() -> None:
    _clean_scratch()
    project_a = SCRATCH / "project-a"
    project_b = SCRATCH / "project-b"
    doc_a = project_a / "project.txt"
    doc_b = project_b / "project.txt"
    doc_a.parent.mkdir(parents=True, exist_ok=True)
    doc_b.parent.mkdir(parents=True, exist_ok=True)
    doc_a.write_text("Alpha uses a battery-powered radio.", encoding="utf-8")
    doc_b.write_text("Beta is a software-only batch service.", encoding="utf-8")

    memory_a = WorkspaceMemory(project_a, SCRATCH / "memory", HashingEmbedder(dimensions=64))
    memory_b = WorkspaceMemory(project_b, SCRATCH / "memory", HashingEmbedder(dimensions=64))
    memory_a.index_project_files([doc_a])
    memory_b.index_project_files([doc_b])

    assert memory_a.paths.working_store != memory_b.paths.working_store
    assert "battery" in memory_a.search("battery radio", top_k=1)[0].record.text
    assert "software-only" in memory_b.search("software batch", top_k=1)[0].record.text
    _clean_scratch()


def test_hybrid_memory_stores_graph_relationships() -> None:
    _clean_scratch()
    store = HybridMemoryStore(SCRATCH / "memory.sqlite", HashingEmbedder(dimensions=64))

    added = store.add_relationships(
        [
            GraphRelationship(
                source_id="REQ-1",
                target_id="REQ-1.1",
                kind="decomposes_to",
                status="approved",
                metadata={"reason": "explicit parent field"},
            ),
            GraphRelationship(
                source_id="REQ-1",
                target_id="REQ-2",
                kind="related_to",
                status="candidate",
            ),
        ]
    )
    approved = store.relationships(source_id="REQ-1", status="approved")

    assert added == 2
    assert approved == [
        GraphRelationship(
            source_id="REQ-1",
            target_id="REQ-1.1",
            kind="decomposes_to",
            status="approved",
            metadata={"reason": "explicit parent field"},
        )
    ]
    _clean_scratch()


def test_llama_cpp_embedder_reports_missing_dependency_or_model() -> None:
    embedder = LlamaCppEmbedder(model_path=SCRATCH / "missing.gguf")

    try:
        embedder.embed_texts(["hello"])
    except (RuntimeError, FileNotFoundError) as exc:
        assert "llama-cpp-python" in str(exc) or "not found" in str(exc)


def test_default_llama_cpp_model_is_repo_contained() -> None:
    embedder = LlamaCppEmbedder()

    assert (ROOT / embedder.model_path).exists()
    assert Path(embedder.model_path).parts[-3:] == ("models", "llama-cpp", "bge-small-en-v1.5-q4_k_m.gguf")


def _clean_scratch() -> None:
    if not SCRATCH.exists():
        return
    for path in sorted(SCRATCH.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    SCRATCH.rmdir()
