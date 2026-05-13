from __future__ import annotations

from pathlib import Path

from learning_agent.core.embeddings import HashingEmbedder, LlamaCppEmbedder
from learning_agent.core.memory import CorrectionMemory, CorrectionPair, ReferenceMemory, WorkspaceMemory


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "out" / "test_memory"


def test_reference_memory_indexes_and_searches() -> None:
    _clean_scratch()
    doc = SCRATCH / "reference.txt"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("REQ-1: The system shall encrypt wireless links.\n", encoding="utf-8")
    memory = ReferenceMemory(SCRATCH / "reference.jsonl", HashingEmbedder(dimensions=64))

    ids = memory.index_files([doc])
    results = memory.search("encrypt wireless communication", top_k=1)

    assert ids
    assert results[0].record.metadata["kind"] == "reference"
    assert "encrypt" in results[0].record.text
    _clean_scratch()


def test_correction_memory_indexes_and_searches() -> None:
    _clean_scratch()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    memory = CorrectionMemory(SCRATCH / "corrections.jsonl", HashingEmbedder(dimensions=64))
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

    assert results[0].record.metadata["kind"] == "correction"
    assert results[0].record.metadata["corrected_output"] == "not_applicable"
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


def test_llama_cpp_embedder_reports_missing_dependency_or_model() -> None:
    embedder = LlamaCppEmbedder(model_path=SCRATCH / "missing.gguf")

    try:
        embedder.embed_texts(["hello"])
    except (RuntimeError, FileNotFoundError) as exc:
        assert "llama-cpp-python" in str(exc) or "not found" in str(exc)


def _clean_scratch() -> None:
    if not SCRATCH.exists():
        return
    for path in sorted(SCRATCH.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    SCRATCH.rmdir()
