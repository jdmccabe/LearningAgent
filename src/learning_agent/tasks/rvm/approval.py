from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from learning_agent.core.artifacts import sha256_file


ApprovalState = Literal["drafted", "reviewed", "rejected", "approved", "baselined"]


@dataclass(frozen=True)
class ApprovalRecord:
    rvm_path: str
    rvm_sha256: str
    state: ApprovalState
    author_id: str
    role: str
    justification: str
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_approval_record(
    rvm_path: str | Path,
    state: ApprovalState,
    author_id: str,
    role: str,
    justification: str,
    out: str | Path,
) -> ApprovalRecord:
    record = ApprovalRecord(
        rvm_path=str(rvm_path),
        rvm_sha256=sha256_file(rvm_path),
        state=state,
        author_id=author_id,
        role=role,
        justification=justification,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
    return record

