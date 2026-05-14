# LearningAgent Workflow Assurance Guide

This document describes the LearningAgent RVM workflow, required inputs, generated artifacts, compliance rationale, and operational use across initial training, production use, review, and re-training.

LearningAgent is an offline, deterministic, file-backed workflow for drafting and auditing aerospace Requirements Verification Matrix (RVM) artifacts. It does not qualify itself as a certification tool. The generated RVM is a draft until reviewed, approved, and baselined under the project certification and configuration-management process.

## Compliance Posture

LearningAgent is designed to support aerospace compliance work by making evidence gaps visible and repeatable. The workflow follows these principles:

- Controlled execution: default workflow behavior uses LangGraph orchestration with deterministic parsing, heuristics, in-process GGUF embeddings, and rule checks.
- Traceable outputs: generated review artifacts contain input paths, agent definition versions, requirement counts, graph counts, compliance summary, and findings.
- Fail-closed compliance: missing evidence is reported as a failure, not as low confidence.
- No silent learning: known-good RVMs and human feedback create persistent examples and proposed changes, but approved agent definitions and policies are not mutated automatically.
- Workspace isolation: project working memory is scoped by workspace path and must not contaminate other projects.
- Service-free runtime: retrieval and memory use file-backed stores with in-process embeddings. No local network host is required.

The workflow helps prepare data for compliance with standards such as DO-178C and DO-254, but final acceptance depends on the project certification plan, tool qualification posture, and authority-approved processes.

## Workflow Overview

The production workflow has seven major stages:

1. Ingest reference requirements, standards, and project documents.
2. Normalize source documents into requirements, project context chunks, and metadata.
3. Populate persistent memory:
   - reference memory for reusable standards and common requirements documents
   - crystallized memory for known-good examples and reviewer corrections
   - workspace working memory for project-specific facts
4. Generate a draft RVM review.
5. Run deterministic aerospace compliance checks.
6. Export and review artifacts.
7. Capture approval state or create controlled proposals for improvements.

The workflow can run from PowerShell, VS Code terminals, GitHub Copilot-assisted terminal sessions, or Claude Code terminals using:

```powershell
python -m learning_agent.cli <command>
```

## Worker Agents

Worker-agent definitions are version-controlled in:

```text
src/learning_agent/tasks/rvm/agents.py
```

Export the active definitions with:

```powershell
python -m learning_agent.cli agent-definitions --out out/agent_definitions.json
```

The current agent set is:

- Document Ingestion Agent
- Traceability Builder Agent
- Applicability Analyst Agent
- Verification Planner Agent
- Impact Analyzer Agent
- Compliance Auditor Agent

Every generated review JSON records:

```json
{
  "verification_artifact": {
    "agent_set_id": "rvm-aerospace-v1",
    "agent_versions": {
      "document_ingestion": "1.0.0",
      "traceability_builder": "1.0.0",
      "applicability_analyst": "1.0.0",
      "verification_planner": "1.0.0",
      "impact_analyzer": "1.0.0",
      "compliance_auditor": "1.0.0"
    }
  }
}
```

Compliance justification: agent definitions are treated as configuration-controlled artifacts. Automated training may propose updates, but it must not silently alter approved definitions.

## Input Formats

Supported input formats:

- `.csv`
- `.tsv`
- `.xlsx`
- `.json`
- `.txt`
- `.md`
- `.xml`
- `.reqif`
- `.reqifz`

Excel ingestion requires:

```powershell
pip install -e ".[ingestion]"
```

Common RVM/requirements columns:

| Field | Accepted Column Names |
| --- | --- |
| Requirement ID | `id`, `requirement_id`, `req_id`, `identifier`, `object_identifier`, `absolute_number` |
| Requirement Text | `text`, `requirement`, `shall`, `description`, `object_text`, `primary_text`, `statement` |
| Parent ID | `parent_id`, `parent`, `parent_requirement`, `parent_identifier` |
| Standard | `standard`, `source_standard`, `source`, `module` |
| Assurance Standard | `assurance_standard`, `standard_basis`, `certification_basis` |
| DAL | `dal`, `design_assurance_level`, `software_level`, `hardware_level` |
| Lifecycle Objectives | `lifecycle_objectives`, `objectives`, `do_objectives` |

Compliance justification: preserving source identifiers and source locations is required for deterministic traceability. Missing fields must be blank or flagged; the workflow must not invent compliance evidence.

## Persistent Memory

Default memory root:

```text
.learning_agent/
```

Show actual paths:

```powershell
python -m learning_agent.cli memory-paths --workspace .
```

### Memory Architecture

LearningAgent uses hybrid memory. No single retrieval mechanism is treated as sufficient for every workflow stage.

Default canonical database:

```text
.learning_agent/memory.sqlite
```

Workspace-scoped canonical database:

```text
.learning_agent/workspaces/<workspace-name>-<hash>/memory.sqlite
```

The memory system has four retrieval layers:

| Layer | Purpose | Used for | Compliance status |
| --- | --- | --- | --- |
| Canonical records | Exact source-of-truth text, IDs, document anchors, hashes, revisions, and structured metadata | Requirement lookup, exact evidence citation, audit reconstruction | May support evidence when cited by exact source anchor and hash |
| Full-text index | Deterministic phrase, identifier, acronym, and quoted-text lookup | Word-perfect requirement and procedure retrieval | Retrieval support; selected records must still be cited exactly |
| Vector index | Semantic discovery over canonical chunks and correction examples | Finding related context, similar prior corrections, possible procedures, and candidate evidence | Not evidence by itself |
| Relationship graph | Directed relationships between requirements, procedures, artifacts, waivers, corrections, and generated decisions | Traceability, impact analysis, coverage review, approved-vs-candidate separation | Approved graph edges may support trace/impact evidence |

Design intent:

- Exact text is stored once in canonical tables. Vector records store embeddings and pointers back to canonical records.
- A vector search result is only a candidate. Agents must resolve candidates to canonical IDs before quoting or citing them.
- Requirement text must be retrievable word-for-word by requirement ID, source anchor, or full-text phrase search.
- Traceability and impact analysis use graph relationships, not vector similarity. Semantic similarity can create candidate links, but approved trace links must be explicit graph edges.
- Workspace working memory is physically isolated in a workspace database. Shared reference and crystallized memory remain in the root database.
- Compliance audit reads persisted structured RVM records and canonical citations. It must not depend on vector scores, learned examples, or model confidence.

### Reference Memory

Purpose: persistent reusable standards, common requirements documents, procedure references, architecture references, and other user-uploaded reference documents.

Default location:

```text
.learning_agent/memory.sqlite
```

Create/update:

```powershell
python -m learning_agent.cli index-reference --docs standards.csv architecture.reqif
```

Search:

```powershell
python -m learning_agent.cli search-reference --query "wireless telemetry encryption"
python -m learning_agent.cli search-reference --query "The system shall encrypt wireless links" --mode text
python -m learning_agent.cli get-requirement --id STD-002
```

Format: canonical document and chunk records with exact text, source path, source hash, line/table anchors, optional revision metadata, FTS index rows, and vector embeddings that point back to canonical chunk IDs.

Interpretation: reference memory supports discovery and citation lookup. It is not compliance evidence unless a selected RVM entry cites the exact canonical document, revision, section, paragraph, row, artifact, or hash.

### Crystallized Memory

Purpose: persistent learned examples from known-good RVMs and human corrections.

Default location:

```text
.learning_agent/memory.sqlite
```

Seed from known-good RVMs:

```powershell
python -m learning_agent.cli learn-good-rvm `
  --gold good_rvm.xlsx `
  --standards standard_requirements.reqif
```

Add human correction:

```powershell
python -m learning_agent.cli add-correction `
  --task applicability `
  --input "REQ-123 wireless telemetry encryption" `
  --bad-output applicable `
  --corrected-output not_applicable `
  --rationale "No wireless telemetry hardware per SYS-ARCH-01 Rev B Sec 2.1."
```

Interpretation: crystallized memory improves future drafting and triage. Corrections are stored as canonical learning records, indexed by full text and vector similarity, and linked to source requirements when available. It does not change approved worker-agent definitions or compliance rules automatically.

### Learning Queue

Purpose: controlled staging area for feedback captured from normal human review actions. The desktop UI records reviewer approvals, rejections, reviewed states, drafted states, and baselining decisions as pending learning candidates when learning capture is enabled.

Default location:

```text
.learning_agent/crystallized/learning_queue.jsonl
```

Format: JSONL records with fields:

- `id`
- `created_utc`
- `updated_utc`
- `status` (`pending`, `approved`, or `rejected`)
- `source`
- `task`
- `input_text`
- `bad_output`
- `corrected_output`
- `rationale`
- `tags`
- `applied_ids`

Interpretation: pending candidates are not used as crystallized examples until an authorized user applies them from the UI learning queue. Rejected candidates remain visible for audit history. This supports continued learning without silent mutation of future workflow behavior.

### Workspace Working Memory

Purpose: project-specific facts and context.

Default location:

```text
.learning_agent/workspaces/<workspace-name>-<hash>/memory.sqlite
```

Workspace manifest:

```text
.learning_agent/workspaces/<workspace-name>-<hash>/manifest.json
```

Index project documents:

```powershell
python -m learning_agent.cli index-project `
  --docs project_architecture.md system_boundary.xlsx `
  --workspace .
```

Search project memory:

```powershell
python -m learning_agent.cli search-project `
  --query "system boundary wireless telemetry" `
  --workspace .

python -m learning_agent.cli search-project `
  --query "No wireless telemetry hardware" `
  --workspace . `
  --mode text
```

Compliance justification: working memory is isolated by workspace path to avoid contaminating one project with another project's architecture, assumptions, waivers, or evidence. Project facts, exclusions, waivers, and evidence anchors should be retrieved from the workspace canonical database by exact ID/phrase when possible, with vector search used only to find candidates.

### Retrieval Responsibilities By Workflow Stage

| Stage | Primary retrieval | Secondary retrieval | Notes |
| --- | --- | --- | --- |
| Document ingestion | Canonical source records | None | Preserve exact IDs, text, line/table anchors, and hashes. Do not infer engineering meaning. |
| Requirement lookup | Requirement ID and FTS | Vector search for discovery | Word-perfect requirement text must come from canonical records. |
| Applicability analysis | Workspace canonical records and FTS | Vector search over workspace/reference chunks | Not-applicable decisions require exact architecture, boundary, allocation, contract, or waiver anchors. |
| Verification planning | Procedure/evidence canonical records and FTS | Vector search over reference procedures | Final procedure references must identify exact document anchors. |
| Traceability | Relationship graph | FTS/ID lookup to resolve endpoints | Parent/child/verification links must be explicit or human-approved graph edges. |
| Impact analysis | Relationship graph traversal | None for approved impact; vector only for candidate review links | Approved and candidate impacts must remain separate. |
| Compliance audit | Persisted RVM fields and canonical citations | None | Audit must fail closed and must not depend on retrieval confidence. |
| Continuous improvement | Crystallized correction records | Vector search for similar examples | Learning creates examples and proposals, not automatic policy changes. |

## Initial Training Stage

Goal: seed persistent memory and benchmark performance using historical good RVMs.

Required inputs:

- known-good RVM file: CSV, TSV, or XLSX
- source standard requirements used by that RVM
- optional architecture and procedure references for reference memory
- optional project documents for workspace memory

Commands:

```powershell
python -m learning_agent.cli learn-good-rvm `
  --gold historical_good_rvm.xlsx `
  --standards standard_requirements.xlsx

python -m learning_agent.cli index-reference `
  --docs standard_requirements.xlsx common_procedures.reqif
```

Desktop UI: use **Agent Settings** > **Run Initial Optimization** to index reference memory, index project memory when inputs are present, crystallize known-good RVM rows, and write `out/ui/initial_optimization_report.json`.

Generated artifacts:

| Artifact | Default Location | Meaning |
| --- | --- | --- |
| Learned examples | `.learning_agent/memory.sqlite` | Persistent known-good decisions and rationale |
| Learning queue | `.learning_agent/crystallized/learning_queue.jsonl` | Pending, approved, and rejected feedback candidates |
| Reference memory | `.learning_agent/memory.sqlite` | Searchable reusable source material |
| UI optimization report | `out/ui/initial_optimization_report.json` | Counts of indexed reference records, project records, crystallized examples, and memory store locations |
| Optional evaluation output | User-provided `--out` path | Performance metrics against good RVMs |

Compliance justification: training data is not trusted blindly. It becomes retrievable examples and benchmark evidence. Any policy or agent-definition change must be promoted through a proposal and review process.

## Production Drafting Stage

Goal: generate a draft RVM and impact analysis for a project.

Required inputs:

- standard requirements file
- project context documents
- optional changed requirement IDs
- optional pre-indexed reference memory
- optional workspace working memory

Command:

```powershell
python -m learning_agent.cli review-rvm `
  --standards standard_requirements.xlsx `
  --project project_architecture.md system_boundary.reqif `
  --changed HL-SYS-REQ-402 `
  --workspace . `
  --memory-root .learning_agent `
  --out out/review.json
```

By default, production drafting indexes the supplied standards into shared canonical/reference memory, indexes project documents into workspace memory, resolves parsed requirements back to canonical requirement records, searches workspace memory for applicability evidence, searches crystallized correction memory for similar reviewed decisions, and persists approved/candidate graph relationships. Use `--no-memory` only for an intentionally stateless diagnostic run. Use `--no-index-memory` when the memory stores have already been curated and the run should retrieve from them without adding current inputs.

Primary artifact:

```text
out/review.json
```

Important top-level fields:

- `verification_artifact`: run metadata, agent definitions, input paths, counts, compliance summary
- `verification_artifact.memory`: memory paths, workspace ID, indexed record counts, and canonical requirement hit counts
- `decisions`: generated RVM decisions
- `impacts`: downstream impact reports for changed requirements
- `audit_findings`: workflow-level warnings
- `compliance_report`: deterministic aerospace compliance findings
- `graph`: requirement nodes and edges

Interpretation:

- `compliance_report.passed = false`: the RVM is not production-compliant.
- `compliance_report.failure_count > 0`: missing evidence or trace data must be fixed before approval.
- `audit_findings`: human review items that may not be strict compliance failures.
- `impacts`: candidate downstream effects based on graph traversal.

Compliance justification: production drafting is intentionally separated from approval. The system may draft incomplete records, but it must clearly mark compliance gaps.

## Compliance Audit Stage

Goal: independently check an RVM JSON artifact without regenerating it.

Command:

```powershell
python -m learning_agent.cli audit-rvm-compliance `
  --rvm out/review.json `
  --out out/compliance_report.json
```

Artifact:

```text
out/compliance_report.json
```

Format:

```json
{
  "passed": false,
  "finding_count": 3,
  "failure_count": 3,
  "warning_count": 0,
  "findings": [
    {
      "requirement_id": "REQ-123",
      "rule_id": "EVIDENCE_PROCEDURE",
      "severity": "failure",
      "message": "Procedure reference does not identify an exact document anchor.",
      "fix": "Use a concrete reference such as ATP-102 Rev B Sec 4.2."
    }
  ]
}
```

Critical rule IDs include:

- `TRACE_PARENT`
- `TRACE_CHILD`
- `METHOD_PRIMARY`
- `METHOD_COMBO`
- `EVIDENCE_PROCEDURE`
- `EVIDENCE_EXECUTION`
- `CRITERIA_SUBJECTIVE`
- `CRITERIA_OBJECTIVE`
- `CHANGE_LOG`
- `CHANGE_RATIONALE`
- `APPLICABILITY_EVIDENCE`
- `ASSURANCE_STANDARD`
- `ASSURANCE_LEVEL`
- `LIFECYCLE_OBJECTIVES`

Compliance justification: this is the cold audit path. It checks persisted JSON only and does not rely on retrieval, learned memory, or generation.

## Evidence Hashing Stage

Goal: bind external evidence artifacts to immutable SHA-256 identifiers.

Inputs:

- ATPs
- ATRs
- log files
- signed reports
- source files
- code or design artifacts
- screenshots or generated test outputs

Command:

```powershell
python -m learning_agent.cli hash-evidence `
  --files evidence/ATP-102.pdf evidence/ATR-102_Run4.log `
  --out out/evidence_manifest.json
```

Artifact:

```text
out/evidence_manifest.json
```

Format:

```json
{
  "generated_at": "2026-05-13T00:00:00+00:00",
  "git_commit": "abc123",
  "files": [
    {
      "path": "evidence/ATR-102_Run4.log",
      "sha256": "...",
      "size_bytes": 12345
    }
  ]
}
```

Interpretation: each listed artifact can be referenced in an RVM decision's `execution_artifacts` field. Use hashes to prove that evidence did not change after review.

## RVM Export Stage

Goal: produce controlled CSV columns for external review or import into another system.

Command:

```powershell
python -m learning_agent.cli export-rvm-csv `
  --rvm out/review.json `
  --out out/review.csv
```

Artifact:

```text
out/review.csv
```

Columns:

- `requirement_id`
- `parent_ids`
- `child_ids`
- `applicability`
- `verification_method`
- `procedure_reference`
- `execution_artifacts`
- `success_criteria`
- `assurance_standard`
- `dal`
- `lifecycle_objectives`
- `rationale`
- `change_log`

Interpretation: blank fields indicate missing evidence or missing trace information. Blank compliance-critical fields should block approval.

## Review and Approval Stage

Goal: capture human review state without modifying the reviewed RVM.

Command:

```powershell
python -m learning_agent.cli record-approval `
  --rvm out/review.json `
  --state reviewed `
  --author-id jdoe `
  --role verification_lead `
  --justification "Reviewed against ATP-102 Rev B." `
  --out out/review_approval.json
```

Artifact:

```text
out/review_approval.json
```

Format:

```json
{
  "rvm_path": "out/review.json",
  "rvm_sha256": "...",
  "state": "reviewed",
  "author_id": "jdoe",
  "role": "verification_lead",
  "justification": "Reviewed against ATP-102 Rev B.",
  "timestamp": "2026-05-13T00:00:00+00:00"
}
```

Allowed states:

- `drafted`
- `reviewed`
- `rejected`
- `approved`
- `baselined`

Compliance justification: approvals are separate immutable records tied to the exact RVM hash. This avoids silently changing a reviewed artifact.

## Re-Training and Continuous Improvement Stage

Goal: improve drafting behavior while preserving configuration control.

Inputs:

- known-good RVM
- generated prediction RVM
- standards
- project documents
- reviewer feedback

Generate improvement suggestions:

```powershell
python -m learning_agent.cli suggest-rvm-improvements `
  --gold good_rvm.xlsx `
  --pred out/review.json `
  --standards standard_requirements.xlsx `
  --project project_architecture.md `
  --out out/improvements.json
```

Wrap suggestions in a controlled proposal:

```powershell
python -m learning_agent.cli create-proposal `
  --improvements out/improvements.json `
  --author-id jdoe `
  --rationale "Holdout benchmark failure triage." `
  --out proposals/proposal-001.json
```

Artifacts:

| Artifact | Location | Meaning |
| --- | --- | --- |
| Improvement plan | User-provided `--out`, often `out/improvements.json` | Candidate policy, memory, or definition updates |
| Proposal | `proposals/*.json` | Reviewed package for controlled change |
| Updated memory | `.learning_agent/crystallized/*.jsonl` | Persistent examples or corrections |

Interpretation: proposals are not active until reviewed and implemented through a committed change. Agent definitions are never changed automatically.

## Release and Configuration Management Stage

Goal: create a deterministic manifest of source and model artifacts.

Command:

```powershell
python -m learning_agent.cli release-manifest `
  --out out/release_manifest.json
```

Artifact:

```text
out/release_manifest.json
```

The command defaults to Git-tracked files. It includes:

- timestamp
- Git commit
- path
- SHA-256 hash
- file size

Compliance justification: release manifests support configuration management, repeatability, and independent reconstruction of the reviewed tool baseline.

## Deployment Checklist

Before production use:

- Confirm `python -m pytest -q` passes.
- Confirm no local network host references are present in runtime configuration.
- Run `agent-definitions` and archive the output.
- Run `release-manifest` and archive the output.
- Load project reference documents with `index-reference`.
- Load project context with `index-project`.
- Seed known-good examples with `learn-good-rvm` if approved by the project process.
- Generate draft RVM with `review-rvm`.
- Run `audit-rvm-compliance`.
- Hash all evidence artifacts with `hash-evidence`.
- Export controlled CSV with `export-rvm-csv`.
- Capture approval state with `record-approval`.
- Store any proposed learning changes with `create-proposal`.

## What Not To Treat As Compliance Evidence

Do not treat these as final compliance evidence by themselves:

- retrieval scores
- agent confidence values
- learned examples
- heuristic applicability matches
- lexical trace candidates
- generated rationale without source anchors

Only exact cited source anchors, approved trace identifiers, objective success criteria, hashed evidence artifacts, and signed review/approval records should be used as compliance evidence.
