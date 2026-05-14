from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from learning_agent.core.documents import chunk_document, load_document
from learning_agent.core.embeddings import Embedder, HashingEmbedder, cosine_similarity
from learning_agent.core.vector_store import SearchResult, VectorRecord


@dataclass(frozen=True)
class CorrectionPair:
    task: str
    input_text: str
    bad_output: str
    corrected_output: str
    rationale: str = ""
    tags: list[str] = field(default_factory=list)
    metrics_delta: dict[str, float] = field(default_factory=dict)

    def to_text(self) -> str:
        return "\n".join(
            [
                f"Task: {self.task}",
                f"Input: {self.input_text}",
                f"Bad output: {self.bad_output}",
                f"Corrected output: {self.corrected_output}",
                f"Rationale: {self.rationale}",
            ]
        )

    def to_metadata(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GraphRelationship:
    source_id: str
    target_id: str
    kind: str
    status: str = "candidate"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryPaths:
    root: Path
    reference_store: Path
    crystallized_store: Path
    workspace_root: Path
    working_store: Path
    workspace_manifest: Path


def default_memory_paths(
    workspace: str | Path | None = None, root: str | Path | None = None
) -> MemoryPaths:
    """Return persistent memory paths for the hybrid SQLite memory stores."""

    workspace_path = Path(workspace or Path.cwd()).resolve()
    memory_root = Path(root or ".learning_agent").resolve()
    workspace_id = _workspace_id(workspace_path)
    workspace_root = memory_root / "workspaces" / workspace_id
    shared_store = memory_root / "memory.sqlite"
    return MemoryPaths(
        root=memory_root,
        reference_store=shared_store,
        crystallized_store=shared_store,
        workspace_root=workspace_root,
        working_store=workspace_root / "memory.sqlite",
        workspace_manifest=workspace_root / "manifest.json",
    )


class HybridMemoryStore:
    """SQLite-backed canonical, full-text, vector, and graph memory store."""

    def __init__(
        self,
        path: str | Path,
        embedder: Embedder | None = None,
        workspace_id: str = "",
    ) -> None:
        self.path = Path(path)
        self.embedder = embedder or HashingEmbedder()
        self.workspace_id = workspace_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def add_files(
        self,
        paths: list[str | Path],
        *,
        kind: str,
        max_lines: int = 40,
        overlap: int = 5,
        metadata: dict[str, Any] | None = None,
    ) -> list[str]:
        texts: list[str] = []
        records: list[dict[str, Any]] = []
        for path in paths:
            file_path = Path(path)
            document = load_document(file_path)
            source_hash = _sha256_file(file_path)
            document_id = _stable_id("doc", str(file_path.resolve()), source_hash, self.workspace_id)
            self._upsert_document(
                document_id=document_id,
                path=str(file_path),
                kind=kind,
                source_hash=source_hash,
                metadata={**document.metadata, **(metadata or {})},
            )
            for chunk in chunk_document(document, max_lines=max_lines, overlap=overlap):
                record_id = _stable_id(
                    "chunk",
                    document_id,
                    str(chunk.start_line),
                    str(chunk.end_line),
                    chunk.text,
                )
                texts.append(chunk.text)
                records.append(
                    {
                        "id": record_id,
                        "document_id": document_id,
                        "kind": kind,
                        "source": chunk.document_path,
                        "source_hash": source_hash,
                        "text": chunk.text,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "metadata": {
                            **chunk.metadata,
                            **(metadata or {}),
                            "source": chunk.document_path,
                            "source_hash": source_hash,
                            "start_line": chunk.start_line,
                            "end_line": chunk.end_line,
                            "workspace_id": self.workspace_id,
                        },
                    }
                )
        embeddings = self.embedder.embed_texts(texts) if texts else []
        with self._connect() as conn:
            for record, embedding in zip(records, embeddings):
                self._upsert_record(conn, record, embedding)
        return [record["id"] for record in records]

    def add_corrections(self, pairs: list[CorrectionPair]) -> list[str]:
        texts = [pair.to_text() for pair in pairs]
        embeddings = self.embedder.embed_texts(texts) if texts else []
        ids: list[str] = []
        with self._connect() as conn:
            for pair, text, embedding in zip(pairs, texts, embeddings):
                record_id = _stable_id("correction", pair.task, pair.input_text, pair.corrected_output)
                ids.append(record_id)
                self._upsert_record(
                    conn,
                    {
                        "id": record_id,
                        "document_id": "",
                        "kind": "correction",
                        "source": "crystallized",
                        "source_hash": "",
                        "text": text,
                        "start_line": 0,
                        "end_line": 0,
                        "metadata": {
                            **pair.to_metadata(),
                            "kind": "correction",
                            "workspace_id": self.workspace_id,
                        },
                    },
                    embedding,
                )
        return ids

    def add_text_records(
        self,
        records: list[dict[str, Any]],
        *,
        kind: str,
        source: str,
        source_hash: str,
    ) -> list[str]:
        texts = [str(record["text"]) for record in records]
        embeddings = self.embedder.embed_texts(texts) if texts else []
        ids: list[str] = []
        with self._connect() as conn:
            for record, embedding in zip(records, embeddings):
                record_id = record.get("id") or _stable_id(kind, source, str(record.get("text", "")))
                ids.append(record_id)
                self._upsert_record(
                    conn,
                    {
                        "id": record_id,
                        "document_id": str(record.get("document_id", "")),
                        "kind": kind,
                        "source": source,
                        "source_hash": source_hash,
                        "text": str(record["text"]),
                        "start_line": int(record.get("start_line", 0)),
                        "end_line": int(record.get("end_line", 0)),
                        "metadata": {
                            **dict(record.get("metadata", {})),
                            "source": source,
                            "source_hash": source_hash,
                            "workspace_id": self.workspace_id,
                        },
                    },
                    embedding,
                )
        return ids

    def search(
        self,
        query: str,
        *,
        kinds: Iterable[str],
        top_k: int = 5,
        workspace_id: str | None = None,
    ) -> list[SearchResult]:
        query_vector = self.embedder.embed_texts([query])[0]
        allowed = set(kinds)
        results: list[SearchResult] = []
        for record in self.load_records(allowed, workspace_id=workspace_id):
            results.append(SearchResult(record, cosine_similarity(query_vector, record.embedding)))
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    def search_text(
        self,
        query: str,
        *,
        kinds: Iterable[str],
        top_k: int = 5,
        workspace_id: str | None = None,
    ) -> list[SearchResult]:
        allowed = tuple(kinds)
        if not allowed:
            return []
        params: list[Any] = [_fts_query(query), *allowed]
        kind_marks = ",".join("?" for _ in allowed)
        workspace_clause = ""
        if workspace_id is not None:
            workspace_clause = " AND json_extract(c.metadata_json, '$.workspace_id') = ?"
            params.append(workspace_id)
        sql = f"""
            SELECT c.id, c.text, c.metadata_json, v.embedding_json, bm25(chunk_fts) AS score
            FROM chunk_fts
            JOIN canonical_records c ON c.id = chunk_fts.record_id
            JOIN vector_embeddings v ON v.record_id = c.id
            WHERE chunk_fts MATCH ? AND c.kind IN ({kind_marks}){workspace_clause}
            ORDER BY score
            LIMIT ?
        """
        params.append(top_k)
        try:
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return self._like_search(query, allowed, top_k, workspace_id)
        return [
            SearchResult(
                VectorRecord(
                    id=row["id"],
                    text=row["text"],
                    embedding=json.loads(row["embedding_json"]),
                    metadata=json.loads(row["metadata_json"]),
                ),
                score=1.0 / (1.0 + abs(float(row["score"]))),
            )
            for row in rows
        ]

    def get_record(self, record_id: str) -> VectorRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT c.id, c.text, c.metadata_json, v.embedding_json
                FROM canonical_records c
                LEFT JOIN vector_embeddings v ON v.record_id = c.id
                WHERE c.id = ?
                """,
                (record_id,),
            ).fetchone()
        if row is None:
            return None
        return VectorRecord(
            id=row["id"],
            text=row["text"],
            embedding=json.loads(row["embedding_json"] or "[]"),
            metadata=json.loads(row["metadata_json"]),
        )

    def find_by_metadata(self, *, kind: str, key: str, value: str) -> VectorRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT c.id, c.text, c.metadata_json, v.embedding_json
                FROM canonical_records c
                LEFT JOIN vector_embeddings v ON v.record_id = c.id
                WHERE c.kind = ? AND json_extract(c.metadata_json, ?) = ?
                ORDER BY c.id
                LIMIT 1
                """,
                (kind, f"$.{key}", value),
            ).fetchone()
        if row is None:
            return None
        return VectorRecord(
            id=row["id"],
            text=row["text"],
            embedding=json.loads(row["embedding_json"] or "[]"),
            metadata=json.loads(row["metadata_json"]),
        )

    def load_records(
        self,
        kinds: Iterable[str] | None = None,
        *,
        workspace_id: str | None = None,
    ) -> list[VectorRecord]:
        params: list[Any] = []
        clauses: list[str] = []
        if kinds is not None:
            allowed = tuple(kinds)
            if not allowed:
                return []
            clauses.append(f"c.kind IN ({','.join('?' for _ in allowed)})")
            params.extend(allowed)
        if workspace_id is not None:
            clauses.append("json_extract(c.metadata_json, '$.workspace_id') = ?")
            params.append(workspace_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.id, c.text, c.metadata_json, v.embedding_json
                FROM canonical_records c
                JOIN vector_embeddings v ON v.record_id = c.id
                {where}
                """,
                params,
            ).fetchall()
        return [
            VectorRecord(
                id=row["id"],
                text=row["text"],
                embedding=json.loads(row["embedding_json"]),
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def add_relationships(self, relationships: list[GraphRelationship]) -> int:
        with self._connect() as conn:
            for relationship in relationships:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO relationships
                        (id, source_id, target_id, kind, status, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _stable_id(
                            "rel",
                            relationship.source_id,
                            relationship.target_id,
                            relationship.kind,
                            relationship.status,
                        ),
                        relationship.source_id,
                        relationship.target_id,
                        relationship.kind,
                        relationship.status,
                        json.dumps(relationship.metadata, sort_keys=True),
                    ),
                )
        return len(relationships)

    def relationships(
        self,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
        kind: str | None = None,
        status: str | None = None,
    ) -> list[GraphRelationship]:
        clauses: list[str] = []
        params: list[str] = []
        for column, value in (
            ("source_id", source_id),
            ("target_id", target_id),
            ("kind", kind),
            ("status", status),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT source_id, target_id, kind, status, metadata_json
                FROM relationships
                {where}
                ORDER BY source_id, kind, target_id
                """,
                params,
            ).fetchall()
        return [
            GraphRelationship(
                source_id=row["source_id"],
                target_id=row["target_id"],
                kind=row["kind"],
                status=row["status"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def count_records(self, kind: str | None = None) -> int:
        with self._connect() as conn:
            if kind is None:
                row = conn.execute("SELECT COUNT(*) AS count FROM canonical_records").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS count FROM canonical_records WHERE kind = ?",
                    (kind,),
                ).fetchone()
        return int(row["count"])

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode = DELETE;
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    indexed_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS canonical_records (
                    id TEXT PRIMARY KEY,
                    document_id TEXT,
                    kind TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vector_embeddings (
                    record_id TEXT PRIMARY KEY,
                    embedder TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    FOREIGN KEY(record_id) REFERENCES canonical_records(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS relationships (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_records_kind ON canonical_records(kind);
                CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_id, kind, status);
                CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_id, kind, status);
                """
            )
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts
                    USING fts5(record_id UNINDEXED, kind UNINDEXED, source UNINDEXED, text)
                    """
                )
            except sqlite3.OperationalError:
                pass

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _upsert_document(
        self,
        *,
        document_id: str,
        path: str,
        kind: str,
        source_hash: str,
        metadata: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO documents
                    (id, path, kind, source_hash, metadata_json, indexed_utc)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    path,
                    kind,
                    source_hash,
                    json.dumps(metadata, sort_keys=True),
                    datetime.now(UTC).replace(microsecond=0).isoformat(),
                ),
            )

    def _upsert_record(
        self,
        conn: sqlite3.Connection,
        record: dict[str, Any],
        embedding: list[float],
    ) -> None:
        metadata = {**record["metadata"], "kind": record["kind"], "embedder": self.embedder.name}
        conn.execute(
            """
            INSERT OR REPLACE INTO canonical_records
                (id, document_id, kind, source, source_hash, text, start_line, end_line, metadata_json, updated_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["document_id"],
                record["kind"],
                record["source"],
                record["source_hash"],
                record["text"],
                record["start_line"],
                record["end_line"],
                json.dumps(metadata, sort_keys=True),
                datetime.now(UTC).replace(microsecond=0).isoformat(),
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO vector_embeddings
                (record_id, embedder, embedding_json)
            VALUES (?, ?, ?)
            """,
            (record["id"], self.embedder.name, json.dumps(embedding)),
        )
        try:
            conn.execute("DELETE FROM chunk_fts WHERE record_id = ?", (record["id"],))
            conn.execute(
                "INSERT INTO chunk_fts (record_id, kind, source, text) VALUES (?, ?, ?, ?)",
                (record["id"], record["kind"], record["source"], record["text"]),
            )
        except sqlite3.OperationalError:
            pass

    def _like_search(
        self,
        query: str,
        kinds: tuple[str, ...],
        top_k: int,
        workspace_id: str | None,
    ) -> list[SearchResult]:
        terms = _terms(query)
        results: list[SearchResult] = []
        for record in self.load_records(kinds, workspace_id=workspace_id):
            text = record.text.lower()
            score = sum(1 for term in terms if term in text)
            if score:
                results.append(SearchResult(record, float(score)))
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]


class ReferenceMemory:
    def __init__(self, path: str | Path, embedder: Embedder | None = None) -> None:
        self.store = HybridMemoryStore(path, embedder or HashingEmbedder())

    def index_files(self, paths: list[str | Path], max_lines: int = 40, overlap: int = 5) -> list[str]:
        ids = self.store.add_files(paths, kind="reference", max_lines=max_lines, overlap=overlap)
        ids.extend(self._index_requirements(paths))
        return ids

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.store.search(query, kinds=["reference", "requirement"], top_k=top_k)

    def search_text(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.store.search_text(query, kinds=["reference", "requirement"], top_k=top_k)

    def get_requirement(self, requirement_id: str) -> VectorRecord | None:
        return self.store.find_by_metadata(
            kind="requirement",
            key="requirement_id",
            value=requirement_id,
        )

    def _index_requirements(self, paths: list[str | Path]) -> list[str]:
        from learning_agent.tasks.rvm.parsing import parse_requirements

        ids: list[str] = []
        for path in paths:
            file_path = Path(path)
            try:
                requirements = parse_requirements(file_path)
            except Exception:
                continue
            if not requirements:
                continue
            source_hash = _sha256_file(file_path)
            records = [
                {
                    "id": _stable_id("requirement", str(file_path.resolve()), requirement.id),
                    "text": requirement.text,
                    "metadata": {
                        "requirement_id": requirement.id,
                        "parent_id": requirement.parent_id or "",
                        "standard": requirement.standard or "",
                        "assurance_standard": requirement.assurance_standard,
                        "dal": requirement.dal,
                        "lifecycle_objectives": requirement.lifecycle_objectives,
                        "source_document": requirement.source_document,
                        **requirement.metadata,
                    },
                }
                for requirement in requirements
            ]
            ids.extend(
                self.store.add_text_records(
                    records,
                    kind="requirement",
                    source=str(file_path),
                    source_hash=source_hash,
                )
            )
        return ids


class CorrectionMemory:
    def __init__(self, path: str | Path, embedder: Embedder | None = None) -> None:
        self.store = HybridMemoryStore(path, embedder or HashingEmbedder())

    def add_pairs(self, pairs: list[CorrectionPair]) -> list[str]:
        return self.store.add_corrections(pairs)

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.store.search(query, kinds=["correction"], top_k=top_k)

    def search_text(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.store.search_text(query, kinds=["correction"], top_k=top_k)


class WorkspaceMemory:
    """Project-level working memory isolated to a single workspace database."""

    def __init__(
        self,
        workspace: str | Path | None = None,
        root: str | Path | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.paths = default_memory_paths(workspace=workspace, root=root)
        self.embedder = embedder or HashingEmbedder()
        self.workspace_id = self.paths.workspace_root.name
        self.store = HybridMemoryStore(
            self.paths.working_store,
            self.embedder,
            workspace_id=self.workspace_id,
        )
        self.paths.workspace_root.mkdir(parents=True, exist_ok=True)
        if not self.paths.workspace_manifest.exists():
            self.paths.workspace_manifest.write_text(
                json.dumps(
                    {
                        "workspace": str(Path(workspace or Path.cwd()).resolve()),
                        "workspace_id": self.workspace_id,
                        "purpose": "Project-scoped working memory. Do not share across workspaces.",
                        "store": str(self.paths.working_store),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

    def index_project_files(self, paths: list[str | Path], max_lines: int = 40, overlap: int = 5) -> list[str]:
        return self.store.add_files(
            paths,
            kind="working",
            max_lines=max_lines,
            overlap=overlap,
            metadata={"workspace_id": self.workspace_id},
        )

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.store.search(
            query,
            kinds=["working"],
            top_k=top_k,
            workspace_id=self.workspace_id,
        )

    def search_text(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.store.search_text(
            query,
            kinds=["working"],
            top_k=top_k,
            workspace_id=self.workspace_id,
        )


def _workspace_id(path: Path) -> str:
    digest = hashlib.sha256(str(path).lower().encode("utf-8")).hexdigest()[:16]
    return f"{path.name}-{digest}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _fts_query(query: str) -> str:
    terms = _terms(query)
    if not terms:
        return '""'
    return " AND ".join(f'"{term}"' for term in terms)


def _terms(query: str) -> list[str]:
    return [term for term in re.findall(r"[A-Za-z0-9_.:-]+", query.lower()) if term]
