from __future__ import annotations

import pytest
from pathlib import Path

from learning_agent.core.embeddings import HashingEmbedder, OllamaEmbedder
from learning_agent.core.memory import CorrectionMemory, CorrectionPair, ReferenceMemory


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


def test_ollama_embedder_rejects_nonlocal_host() -> None:
    embedder = OllamaEmbedder(host="https://ollama.example.test")

    with pytest.raises(ValueError, match="locally|local"):
        embedder.embed_texts(["hello"])


def _clean_scratch() -> None:
    if not SCRATCH.exists():
        return
    for path in sorted(SCRATCH.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    SCRATCH.rmdir()
