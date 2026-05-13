from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileArtifact:
    path: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArtifactManifest:
    generated_at: str
    git_commit: str
    files: list[FileArtifact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "git_commit": self.git_commit,
            "files": [item.to_dict() for item in self.files],
        }


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(paths: list[str | Path]) -> ArtifactManifest:
    files = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists() or path.is_dir():
            continue
        files.append(
            FileArtifact(
                path=str(path),
                sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
            )
        )
    return ArtifactManifest(
        generated_at=datetime.now(timezone.utc).isoformat(),
        git_commit=_git_commit(),
        files=files,
    )


def write_manifest(paths: list[str | Path], out: str | Path) -> ArtifactManifest:
    manifest = build_manifest(paths)
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    return manifest


def tracked_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"

