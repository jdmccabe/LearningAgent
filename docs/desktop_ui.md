# Desktop UI Guide

LearningAgent includes a desktop UI intended to be the normal user-facing control surface for the RVM workflow. It is built with Python Tkinter and does not start a web server, bind a local network port, or use a loopback address.

Launch it from the repository root:

```powershell
python -m learning_agent.ui
```

Or, after installing the package:

```powershell
learning-agent-ui
```

## What The UI Covers

The UI is organized around the human process, not just the command sequence:

- **Inputs**: standards, requirement exports, project context, evidence files, known-good RVMs, workspace path, memory root, output directory, workflow engine, and embedder selection.
- **Training & Memory**: crystallize known-good RVM rows, index reusable reference documents, index workspace-scoped project memory, save reviewer correction pairs, search memory, suggest improvements, and create governed change proposals.
- **Run**: run the draft RVM workflow, run deterministic compliance audit, export controlled CSV, hash evidence, create release manifests, and export worker-agent definitions.
- **Results**: view compliance pass/fail state, failure counts, average confidence, low-confidence decisions, not-applicable decisions, required human actions, compliance findings, and RVM decisions.
- **Artifacts**: inspect generated JSON, CSV, hash manifests, proposals, approval records, and agent-definition exports.
- **Approvals**: review required approval context and create drafted, reviewed, rejected, approved, or baselined approval artifacts with author, role, justification, timestamp, and RVM hash.

## Normal Production Flow

1. Open **Inputs**.
2. Add standards or requirement files. Supported formats are `.csv`, `.tsv`, `.xlsx`, `.json`, `.txt`, `.md`, `.reqif`, `.reqifz`, and `.xml`.
3. Add project context files such as architecture summaries, DOORS/ReqIF exports, Excel exports, design notes, or verification planning documents.
4. Set the workspace path. This controls project working-memory isolation.
5. Set the memory root if you need a shared persistent memory location.
6. Add changed requirement IDs when performing impact review.
7. Open **Training & Memory** and index project/reference files when retrieval memory should be updated.
8. Open **Run** and select **Run Complete Draft + Audit**.
9. Open **Results** and resolve every required human action.
10. Use **Artifacts** to inspect JSON, CSV, manifests, and supporting outputs.
11. Use **Approvals** to record review or approval state only after the human disposition is complete.

## Training Flow

Initial training from known-good RVM documents is handled from **Training & Memory**:

1. Add the requirement standards and known-good RVM on **Inputs**.
2. Select the embedder. `hashing` is deterministic and dependency-free. `llama-cpp` uses the repo-contained GGUF model in process when `llama-cpp-python` is installed.
3. Select **Crystallize Good RVM**. This writes correction-pair memory to the crystallized memory store.
4. Run a draft review and compare it against the known-good RVM by selecting **Suggest Improvements**.
5. Select **Create Change Proposal** to wrap suggested changes in a governed proposal artifact.
6. Review, validate, and version any proposed rule or agent-definition changes before promotion.

Automated training does not silently mutate approved agent definitions. The UI creates memory and proposal artifacts; human review and configuration control remain explicit.

## Continued Learning From Human Feedback

When a reviewer corrects an applicability decision, verification method, trace link, or rationale:

1. Open **Training & Memory**.
2. Fill in the correction-pair fields with the input context, bad output, corrected output, rationale, and tags.
3. Select **Save Correction Pair**.
4. Search crystallized corrections later to reuse that feedback during policy review or future model-adapter work.

Correction pairs persist between UI sessions under the configured memory root.

## Memory Locations

The **Inputs** tab shows the resolved memory paths:

- Reference memory stores reusable standards and common requirements reference documents.
- Crystallized memory stores known-good RVM rows, correction pairs, and learned improvement evidence.
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

The UI runs in the Python process as a desktop application. It does not create local web URLs, local network hosts, or loopback connections. The optional GGUF embedder is accessed in process through `llama-cpp-python`; it is not an Ollama service call.
