# Desktop UI Guide

LearningAgent includes a desktop UI intended to be the normal user-facing control surface for the RVM workflow. It is built with Python Tkinter and does not start a web server, bind a local network port, or use a loopback address.

The UI defaults to the LangGraph workflow engine and the llama-cpp GGUF embedder. The deterministic built-in workflow engine and hashing embedder remain available for troubleshooting or locked-down environments.

Launch it from the repository root:

```powershell
python -m learning_agent.ui
```

On Windows, `run_ui.bat` launches the UI and bootstraps missing project dependencies:

```powershell
.\run_ui.bat
```

The bootstrap uses only the checked-in offline wheelhouse in `vendor/wheels`. It passes `--no-index` to pip, so it does not download packages or contact a package repository. The current wheelhouse is built for Windows amd64 with CPython 3.14.

Or, after installing the package:

```powershell
learning-agent-ui
```

## What The UI Covers

The UI is organized around the human process, not just the command sequence:

- **Inputs**: standards, requirement exports, project context, and evidence files.
- **Agent Settings**: workspace path, memory root, output directory, workflow engine, embedder selection, known-good RVM selection, changed requirement IDs, learning policy, initial optimization, memory indexing, memory search, and the learning queue.
- **Run**: run the draft RVM workflow, run deterministic compliance audit, export controlled CSV, hash evidence, create release manifests, and export worker-agent definitions.
- **Results**: view compliance pass/fail state, failure counts, average confidence, low-confidence decisions, not-applicable decisions, required human actions, compliance findings, and RVM decisions.
- **Artifacts**: inspect generated JSON, CSV, hash manifests, proposals, approval records, and agent-definition exports.
- **Approvals**: review required approval context and create drafted, reviewed, rejected, approved, or baselined approval artifacts with author, role, justification, timestamp, and RVM hash.

## Normal Production Flow

1. Open **Inputs**.
2. Add standards or requirement files. Supported formats are `.csv`, `.tsv`, `.xlsx`, `.json`, `.txt`, `.md`, `.reqif`, `.reqifz`, and `.xml`.
3. Add project context files such as architecture summaries, DOORS/ReqIF exports, Excel exports, design notes, or verification planning documents.
4. Open **Agent Settings**.
5. Set the workspace path. This controls project working-memory isolation.
6. Set the memory root if you need a shared persistent memory location.
7. Add changed requirement IDs when performing impact review.
8. Index project/reference files when retrieval memory should be updated.
9. Open **Run** and select **Run Complete Draft + Audit**.
10. Open **Results** and resolve every required human action.
11. Use **Artifacts** to inspect JSON, CSV, manifests, and supporting outputs.
12. Use **Approvals** to record review or approval state only after the human disposition is complete.

## Training Flow

Initial training from known-good RVM documents is handled from **Agent Settings**:

1. Add the requirement standards on **Inputs**.
2. Select the embedder. `llama-cpp` uses the repo-contained GGUF model in process. `hashing` is the deterministic dependency-light fallback.
3. Select the known-good RVM in **Agent Settings**.
4. Select **Run Initial Optimization** to index reference documents, index workspace project memory when present, crystallize known-good examples, and write `initial_optimization_report.json`.
5. Run a draft review and compare it against the known-good RVM by selecting **Suggest Improvements**.
6. Select **Create Change Proposal** to wrap suggested changes in a governed proposal artifact.
7. Review, validate, and version any proposed rule or agent-definition changes before promotion.

Automated training does not silently mutate approved agent definitions. The UI creates memory and proposal artifacts; human review and configuration control remain explicit.

## Continued Learning From Human Feedback

When a reviewer approves, rejects, reviews, drafts, or baselines a result, the UI can automatically capture that disposition as a learning candidate:

1. Open **Agent Settings**.
2. Keep **Capture review feedback as learning candidates** enabled.
3. Keep **Require approval before applying learned candidates** enabled for controlled aerospace use.
4. Record the disposition in **Approvals** with author, role, and justification.
5. Return to **Agent Settings** and review the **Learning queue**.
6. Select **Apply Selected to Crystallized Memory** only after the candidate is suitable for future runs, or **Reject Selected** when it should not be reused.

Learning candidates persist between UI sessions under `.learning_agent/crystallized/learning_queue.jsonl`. Approved candidates are written to crystallized correction memory. This keeps normal review actions from silently mutating future behavior.

## Memory Locations

The **Agent Settings** tab shows the resolved memory paths:

- Reference memory stores reusable standards and common requirements reference documents.
- Crystallized memory stores known-good RVM rows, correction pairs, and learned improvement evidence.
- The learning queue stores pending, approved, and rejected feedback candidates awaiting controlled disposition.
- Workspace working memory stores project-specific details and is isolated by workspace path.

Workspace isolation prevents project context for one aircraft, subsystem, program, or customer from contaminating another workspace.

## Artifact Locations

Generated UI artifacts default to:

```text
out/ui/
```

Common artifacts:

- `review.json`: draft RVM review, decisions, impact reports, graph, and embedded compliance report.
- `compliance_report.json`: deterministic aerospace compliance audit.
- `review.csv`: controlled RVM CSV export.
- `evidence_manifest.json`: SHA-256 hashes for selected evidence artifacts.
- `release_manifest.json`: SHA-256 hashes for tracked release/source artifacts.
- `agent_definitions.json`: versioned worker-agent definitions used by the workflow.
- `improvements.json`: deterministic improvement suggestions from known-good RVM comparison.
- `change_proposal.json`: governed proposal wrapping improvement suggestions.
- `approval_<state>.json`: review or approval state record with RVM hash.
- `initial_optimization_report.json`: summary of indexed memory and crystallized examples from initial optimization.

The repository `.gitignore` excludes `out/` and `.learning_agent/`, so generated operational artifacts and persistent memory are not committed by default.

## Interpreting Results

The **Results** tab separates deterministic compliance state from workflow confidence:

- **Compliance** must pass before approval. Failures are objective audit findings.
- **Failures** counts deterministic compliance failures.
- **Avg Confidence** summarizes workflow confidence across RVM decisions.
- **Low Confidence** flags decisions needing reviewer disposition.
- **Not Applicable** counts decisions that require architecture or boundary evidence review.
- **Required human actions** lists the exact human work needed before sign-off.

For aerospace use, do not treat confidence as approval authority. Confidence helps triage review effort; compliance findings and human approvals control release readiness.

## No Local Hosting

The UI runs in the Python process as a desktop application. It does not create local web URLs, local network hosts, or loopback connections. The GGUF embedder is accessed in process through `llama-cpp-python`; it is not an Ollama service call.
