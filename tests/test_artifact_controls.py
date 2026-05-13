from __future__ import annotations

import json
from pathlib import Path

from learning_agent.core.artifacts import build_manifest, sha256_file
from learning_agent.tasks.rvm.approval import create_approval_record
from learning_agent.tasks.rvm.export import export_rvm_csv
from learning_agent.tasks.rvm.proposals import create_change_proposal
from learning_agent.tasks.rvm.workflow import review_rvm


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "out" / "test_artifact_controls"


def test_hash_manifest_records_sha256() -> None:
    _clean_scratch()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    file_path = SCRATCH / "evidence.log"
    file_path.write_text("PASS", encoding="utf-8")

    manifest = build_manifest([file_path])

    assert manifest.files[0].sha256 == sha256_file(file_path)
    assert manifest.files[0].size_bytes == 4
    _clean_scratch()


def test_export_and_approval_records_are_deterministic() -> None:
    _clean_scratch()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    result = review_rvm(
        [ROOT / "examples" / "standards.csv"],
        [ROOT / "examples" / "project.txt"],
    )
    rvm_path = SCRATCH / "review.json"
    rvm_path.write_text(json.dumps(result["result"]), encoding="utf-8")
    csv_path = SCRATCH / "review.csv"
    approval_path = SCRATCH / "approval.json"

    export_rvm_csv(rvm_path, csv_path)
    record = create_approval_record(
        rvm_path,
        "reviewed",
        "jdoe",
        "verification_lead",
        "Reviewed for test fixture coverage.",
        approval_path,
    )

    assert "requirement_id,parent_ids,child_ids" in csv_path.read_text(encoding="utf-8")
    assert record.rvm_sha256 == sha256_file(rvm_path)
    assert json.loads(approval_path.read_text(encoding="utf-8"))["state"] == "reviewed"
    _clean_scratch()


def test_change_proposal_wraps_improvement_suggestions() -> None:
    _clean_scratch()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    improvements = SCRATCH / "improvements.json"
    improvements.write_text(
        json.dumps({"suggestions": [{"kind": "policy", "target": "x"}]}),
        encoding="utf-8",
    )
    proposal_path = SCRATCH / "proposal.json"

    proposal = create_change_proposal(improvements, "jdoe", "Benchmark failure triage.", proposal_path)

    assert proposal.status == "PROPOSED"
    assert proposal.proposed_changes[0]["kind"] == "policy"
    assert json.loads(proposal_path.read_text(encoding="utf-8"))["author_id"] == "jdoe"
    _clean_scratch()


def _clean_scratch() -> None:
    if not SCRATCH.exists():
        return
    for path in sorted(SCRATCH.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    SCRATCH.rmdir()

