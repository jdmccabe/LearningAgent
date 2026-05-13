from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class Embedder(Protocol):
    name: str

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""


@dataclass(frozen=True)
class HashingEmbedder:
    """Deterministic offline embedder for tests and credential-free operation."""

    dimensions: int = 256
    name: str = "hashing"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_normalize(_hash_vector(text, self.dimensions)) for text in texts]


@dataclass(frozen=True)
class LlamaCppEmbedder:
    """In-process GGUF embedder. No local network service is used."""

    model_path: str | Path = Path("models/ollama/embeddinggemma/embeddinggemma.gguf")
    name: str = "llama-cpp"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise RuntimeError(
                "The 'llama-cpp-python' package is required for in-process GGUF "
                "embeddings. Install the optional local-gguf dependencies first."
            ) from exc
        path = Path(self.model_path)
        if not path.exists():
            raise FileNotFoundError(f"Embedding model was not found: {path}")
        model = Llama(model_path=str(path), embedding=True, verbose=False)
        vectors: list[list[float]] = []
        for text in texts:
            response = model.create_embedding(text)
            vectors.append(list(response["data"][0]["embedding"]))
        return [_normalize(vector) for vector in vectors]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _hash_vector(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for raw_token in text.lower().split():
        token = raw_token.strip(".,;:!?()[]{}\"'")
        if not token:
            continue
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    return vector


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector
