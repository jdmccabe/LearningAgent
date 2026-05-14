from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from learning_agent.core.embeddings import Embedder, cosine_similarity


@dataclass(frozen=True)
class VectorRecord:
    id: str
    text: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchResult:
    record: VectorRecord
    score: float

    def to_dict(self, include_embedding: bool = True) -> dict[str, Any]:
        record = self.record.to_dict()
        if not include_embedding:
            record.pop("embedding", None)
        return {"score": self.score, "record": record}


class JsonlVectorStore:
    """Legacy small JSONL vector helper.

    Production memory uses ``HybridMemoryStore`` in ``learning_agent.core.memory``.
    """

    def __init__(self, path: str | Path, embedder: Embedder) -> None:
        self.path = Path(path)
        self.embedder = embedder
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add_texts(self, texts: list[str], metadatas: list[dict[str, Any]] | None = None) -> list[str]:
        metadatas = metadatas or [{} for _ in texts]
        embeddings = self.embedder.embed_texts(texts)
        existing_count = len(self.load())
        records = []
        ids = []
        for index, (text, metadata, embedding) in enumerate(zip(texts, metadatas, embeddings), start=1):
            record_id = metadata.get("id") or f"vec-{existing_count + index:08d}"
            ids.append(record_id)
            records.append(
                VectorRecord(
                    id=record_id,
                    text=text,
                    embedding=embedding,
                    metadata={**metadata, "embedder": self.embedder.name},
                )
            )
        with self.path.open("a", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record.to_dict()) + "\n")
        return ids

    def search(self, query: str, top_k: int = 5, filters: dict[str, Any] | None = None) -> list[SearchResult]:
        query_vector = self.embedder.embed_texts([query])[0]
        results: list[SearchResult] = []
        for record in self.load():
            if filters and any(record.metadata.get(key) != value for key, value in filters.items()):
                continue
            results.append(SearchResult(record, cosine_similarity(query_vector, record.embedding)))
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    def load(self) -> list[VectorRecord]:
        if not self.path.exists():
            return []
        records: list[VectorRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            records.append(
                VectorRecord(
                    id=data["id"],
                    text=data["text"],
                    embedding=list(data["embedding"]),
                    metadata=dict(data.get("metadata", {})),
                )
            )
        return records
