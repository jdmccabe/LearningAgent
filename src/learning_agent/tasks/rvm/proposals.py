from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learning_agent.core.artifacts import sha256_file


@dataclass(frozen=True)
class ChangeProposal:
    status: str
    author_id: str
    source_path: str
    source_sha256: str
    created_at: str
    rationale: str
    proposed_changes: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_change_proposal(
    improvements_path: str | Path,
    author_id: str,
    rationale: str,
    out: str | Path,
) -> ChangeProposal:
    data = json.loads(Path(improvements_path).read_text(encoding="utf-8"))
    proposal = ChangeProposal(
        status="PROPOSED",
        author_id=author_id,
        source_path=str(improvements_path),
        source_sha256=sha256_file(improvements_path),
        created_at=datetime.now(timezone.utc).isoformat(),
        rationale=rationale,
        proposed_changes=list(data.get("suggestions", [])),
    )
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(proposal.to_dict(), indent=2), encoding="utf-8")
    return proposal

