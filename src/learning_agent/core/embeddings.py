from __future__ import annotations

import hashlib
import ipaddress
import math
import os
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse


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
class OllamaEmbedder:
    """Ollama embedding adapter for a local Ollama service."""

    model: str = "embeddinggemma"
    host: str | None = "http://127.0.0.1:11434"
    name: str = "ollama"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        resolved_host = _validated_host(self.host or os.environ.get("OLLAMA_HOST"))
        try:
            import ollama
        except ImportError as exc:
            raise RuntimeError(
                "The 'ollama' package is required for Ollama embeddings. "
                "Install the optional retrieval dependencies first."
            ) from exc
        client = ollama.Client(host=resolved_host)
        response = client.embed(model=self.model, input=texts)
        return [list(vector) for vector in response["embeddings"]]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _validated_host(host: str | None) -> str:
    if not host:
        raise ValueError(
            "Ollama host is required. Set OLLAMA_HOST or pass --ollama-host "
            "with a local Ollama service URL."
        )
    parsed = urlparse(host)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Ollama host must be an http(s) URL with a hostname.")
    hostname = parsed.hostname.lower()
    if hostname == "localhost":
        return host
    try:
        if not ipaddress.ip_address(hostname).is_loopback:
            raise ValueError("Ollama must be served locally for this project.")
    except ValueError as exc:
        if "Ollama must" in str(exc):
            raise
        raise ValueError("Ollama host must be local: use localhost or a loopback IP.") from exc
    return host


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
