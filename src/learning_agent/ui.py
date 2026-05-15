from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from tkinter import END, BOTH, LEFT, RIGHT, TOP, X, Y, BooleanVar, Listbox, StringVar, Tk, Toplevel, filedialog, messagebox, scrolledtext, ttk
from typing import Any, Callable

from learning_agent.core.artifacts import tracked_files, write_manifest
from learning_agent.core.documents import write_json
from learning_agent.core.embeddings import HashingEmbedder, LlamaCppEmbedder
from learning_agent.core.memory import (
    CorrectionMemory,
    CorrectionPair,
    ReferenceMemory,
    WorkspaceMemory,
    default_memory_paths,
)
from learning_agent.tasks.rvm.agents import agent_definitions_as_dict
from learning_agent.tasks.rvm.approval import create_approval_record
from learning_agent.tasks.rvm.compliance import audit_compliance_from_file
from learning_agent.tasks.rvm.export import export_rvm_csv
from learning_agent.tasks.rvm.improvement import suggest_rvm_improvements
from learning_agent.tasks.rvm.parsing import parse_good_rvm, parse_requirements
from learning_agent.tasks.rvm.proposals import create_change_proposal
from learning_agent.tasks.rvm.workflow import review_rvm
from learning_agent.ui_support import (
    append_learning_candidate,
    artifact_inventory,
    create_learning_candidate,
    format_memory_inventory,
    format_score,
    learning_queue_path,
    load_learning_candidates,
    load_review,
    memory_inventory,
    required_human_actions,
    summarize_review,
    update_learning_candidate_status,
)


APP_TITLE = "LearningAgent RVM Control Center"
DEFAULT_MODEL_PATH = "models/llama-cpp/bge-small-en-v1.5-q4_k_m.gguf"
DEFAULT_REVIEW_PATH = Path("out/ui/review.json")
DEFAULT_COMPLIANCE_PATH = Path("out/ui/compliance_report.json")

HELP_SECTIONS: dict[str, dict[str, str]] = {
    "Standard / requirement documents": {
        "summary": "Authoritative standards and requirement records that drive the RVM decisions.",
        "details": "Add the canonical requirements the workflow must evaluate. This section should contain requirement IDs, exact requirement text, parent and child relationships when available, verification expectations, applicability notes, assurance metadata, and stable source anchors such as document IDs, revisions, sections, paragraphs, table names, sheet names, or row numbers. Supported inputs include CSV, TSV, XLSX, JSON, TXT, Markdown, ReqIF, ReqIFZ, and XML files. Spreadsheet and CSV-style files should preserve column headings and row identity; text-like files should keep enough surrounding context for the parser to recover requirement boundaries.",
        "sources": "Use controlled standards, exported requirements databases, DOORS or ReqIF baselines, certification basis documents, project requirement specifications, or known-good requirement tables. Prefer released or baselined sources over informal notes, and keep the revision aligned with the project review baseline.",
        "usage": "These files become the requirement set reviewed by the workflow. Their IDs and text feed applicability, traceability, verification method, compliance, and impact decisions. Missing IDs, ambiguous requirement boundaries, or stale revisions can cascade into orphan traces, wrong applicability decisions, low confidence, compliance findings, and poor comparisons against known-good RVMs.",
    },
    "Project context / DOORS exports / design documents": {
        "summary": "Project-specific context that explains how the requirements apply to this system.",
        "details": "Add architecture, design, planning, interface, safety, verification, and project-scope information that helps decide applicability and trace links. Useful content includes system boundaries, subsystem responsibilities, allocation rationale, DOORS exports, design descriptions, verification plans, test strategy, change summaries, certification assumptions, DAL or assurance levels, and evidence explaining why a requirement is applicable or not applicable. Supported formats match the document picker: CSV, TSV, XLSX, JSON, TXT, Markdown, ReqIF, ReqIFZ, and XML.",
        "sources": "Use project-controlled sources such as architecture documents, design specifications, interface control documents, verification plans, exported requirement modules, change packages, safety assessments, and approved planning material. If project context comes from working drafts, make that status clear in the file content or filename.",
        "usage": "The workflow retrieves this context when drafting RVM rows, impact analysis, non-applicability rationale, verification references, and human action lists. Project context is also indexed into workspace memory, so the selected workspace controls isolation. Weak or missing context usually creates low-confidence decisions, missing evidence findings, and extra approval work.",
    },
    "Evidence artifacts to hash": {
        "summary": "Files that should be fingerprinted as verification or review evidence.",
        "details": "Add concrete artifacts whose integrity should be recorded, such as test logs, signed reports, generated review outputs, tool exports, procedure files, screenshots, simulation outputs, analysis results, approval records, or controlled CSVs. Any file type is accepted because this section does not parse semantic content; it produces SHA-256 hashes, sizes, names, and paths for manifest-style evidence tracking.",
        "sources": "Use outputs from verification runs, review sessions, configuration-controlled repositories, test environments, tool qualification records, or release packaging steps. Prefer final or review-ready artifacts rather than transient scratch files unless the transient state is exactly what needs to be preserved.",
        "usage": "The Hash Evidence action writes a manifest that reviewers can use to verify that evidence has not changed after review. These hashes can support approval records, compliance disposition, and release packages, but they do not by themselves prove that the underlying evidence is sufficient or correct.",
    },
    "Workflow and memory policy": {
        "summary": "Core run configuration, memory isolation, learning behavior, and model choices.",
        "details": "Set the workspace, memory root, output directory, known-good RVM path, GGUF model path, changed requirement IDs, workflow engine, embedder, and learning-policy toggles. The workspace identifies the project boundary for working memory. The memory root controls where persistent reference, project, and crystallized memory stores live. Changed requirement IDs should be exact IDs separated by commas, semicolons, or new lines. Known-good RVM files should be CSV, TSV, or XLSX. GGUF model paths should point to local embedding models when using llama-cpp.",
        "sources": "Use project workspace paths, local or shared memory folders chosen by your configuration-control process, approved output directories, known-good RVMs from reviewed baselines, and repo-contained or organization-approved GGUF models. Changed IDs should come from a change request, requirements delta, baseline comparison, or review package.",
        "usage": "This section controls almost every downstream operation. Workspace and memory choices affect retrieval and contamination boundaries; output directory controls where artifacts are written; engine and embedder affect workflow behavior and retrieval quality; changed IDs focus impact analysis; learning toggles decide whether reviewer feedback enters the controlled learning queue or crystallized memory.",
    },
    "Initial optimization from known-good RVMs": {
        "summary": "Training and improvement actions that learn from reviewed RVM examples.",
        "details": "Use these actions after selecting standards and a known-good RVM. The known-good RVM should contain reviewed applicability decisions, verification methods, trace links, rationale, and evidence fields that represent the behavior you want future runs to emulate. The improvement actions compare current outputs against the known-good baseline and create governed proposal artifacts rather than silently changing approved logic.",
        "sources": "Use human-reviewed, configuration-controlled RVMs from prior projects, certification exercises, regression suites, or internal gold datasets. The standards selected on the Inputs tab should be the same requirement sources used to produce the known-good RVM.",
        "usage": "Initial optimization indexes requirements, optionally indexes project context, crystallizes correction examples, writes an optimization report, and can create improvement proposals. The resulting memory can improve future retrieval and decisions, while proposal artifacts support human-controlled changes to workflow policy or agent behavior.",
    },
    "Resolved persistent memory locations": {
        "summary": "Read-only view of the file-backed memory stores currently in use.",
        "details": "This section shows resolved paths, existence, sizes, and record counts for reference memory, workspace memory, the learning queue, and related manifests. It does not take files directly; it reflects the workspace and memory root settings from the workflow policy section.",
        "sources": "The values come from the configured workspace path and memory root. Stores are created by indexing reference documents, indexing project memory, crystallizing known-good RVMs, applying learning candidates, or recording feedback.",
        "usage": "Use this view to confirm that the UI is reading and writing the intended memory locations before running reviews or applying learning. Wrong memory paths can make a run appear to forget prior learning or, worse, retrieve context from the wrong workspace.",
    },
    "Reference and project memory": {
        "summary": "Index selected inputs into reusable reference memory or workspace-specific memory.",
        "details": "Index Reference Docs stores standards and broadly reusable requirement context. Index Project Memory stores project-only documents such as architecture, design, DOORS exports, and verification planning material. Inputs come from the files already listed on the Inputs tab. Supported file formats follow the parser and document ingestion support used elsewhere in the UI.",
        "sources": "Reference memory should come from stable standards, common requirement sources, and reusable guidance. Project memory should come from controlled project artifacts and should stay scoped to the active workspace.",
        "usage": "Indexed memory is retrieved during review, search, and future workflow runs. Reference memory improves requirement discovery and citation lookup across workspaces; project memory improves applicability and trace decisions within one workspace. Indexing the wrong documents can pollute retrieval and should be corrected by changing memory roots or cleaning the store under configuration control.",
    },
    "Learning queue": {
        "summary": "Controlled holding area for reviewer feedback before it becomes reusable memory.",
        "details": "The queue contains learning candidates captured from approval actions or other feedback workflows. Each candidate includes status, task, source, created time, rationale, input text, previous output, corrected output, tags, and applied memory IDs when approved. The UI displays the main review fields while the backing JSONL file preserves the full candidate record.",
        "sources": "Candidates usually come from human approval, rejection, review, baselining, or explicit feedback captured by the UI. They may also come from generated improvement workflows that package reviewer disposition into a reusable correction.",
        "usage": "Pending candidates do not affect future runs until applied. Applying selected candidates writes them to crystallized correction memory; rejecting them preserves the decision without teaching future workflows. This keeps human feedback useful while preventing silent behavioral drift.",
    },
    "Search persistent memory": {
        "summary": "Search reference, crystallized correction, or project working memory.",
        "details": "Enter a natural-language query, requirement ID, topic, document anchor, rationale phrase, or verification concept. Select the scope that matches what you want to inspect: reference memory for standards and reusable documents, crystallized corrections for learned examples, or project working memory for workspace-specific context.",
        "sources": "Search results come only from stores already indexed or learned under the current memory configuration. If expected results are missing, refresh memory paths and confirm that the relevant documents were indexed into the selected scope.",
        "usage": "Search is a diagnostic and review aid. It helps explain what context the workflow can retrieve, supports citation discovery, and helps reviewers verify that memory contains the intended sources. Search results are not approval evidence unless they point back to exact controlled source artifacts.",
    },
    "Run actions": {
        "summary": "Commands that execute the review workflow and create operational artifacts.",
        "details": "This section runs the complete draft-plus-audit workflow, audits an existing review, exports a controlled CSV, hashes evidence, creates a release manifest, or exports the versioned worker-agent definitions. The actions consume the selected inputs, current review artifact path, evidence list, output directory, and workflow settings as appropriate.",
        "sources": "Inputs come from the Inputs tab, Agent Settings tab, and currently selected review artifact. Release manifests usually use tracked repository files; evidence manifests use the evidence list.",
        "usage": "These actions produce the files reviewed in Results, Artifacts, and Approvals. Running a complete review updates review.json and compliance_report.json. Export and manifest actions create supporting artifacts for controlled review, release readiness, traceability, and reproducibility.",
    },
    "Current review artifact": {
        "summary": "The review JSON file that Results, audit, export, and approvals operate on.",
        "details": "Select or enter a review JSON path. The file should contain the RVM workflow output, including decisions, impacts, compliance report data, verification artifact metadata, audit findings, and graph information when available. The default UI run writes this to out/ui/review.json.",
        "sources": "Use review artifacts created by Run Complete Draft + Audit, CLI review-rvm output, or another controlled workflow that follows the same JSON structure.",
        "usage": "Audit Current Review, Export Controlled CSV, Load Results, and Approval actions all read this path. Selecting the wrong artifact can show stale results, export the wrong CSV, or attach approval state to the wrong review hash.",
    },
    "Run log": {
        "summary": "Chronological status output for UI operations.",
        "details": "This section records started, finished, and error messages for long-running UI actions. It contains operational messages, output file paths, and exception text when a command fails. It is not intended for source documents or review evidence.",
        "sources": "Messages come from UI worker tasks such as indexing, running reviews, auditing, exporting, hashing, searching, learning, and approvals.",
        "usage": "Use the log to confirm what action ran, where outputs were written, and what failed. The log helps troubleshoot workflow state, but generated artifacts and manifests remain the controlled outputs.",
    },
    "Compliance": {
        "summary": "Overall deterministic compliance state for the current review.",
        "details": "This metric shows whether deterministic compliance checks passed or still need review. It is derived from the compliance report embedded in the selected review artifact, not from model confidence.",
        "sources": "The value comes from compliance_report data produced by the draft-plus-audit workflow or Audit Current Review.",
        "usage": "Compliance status gates approval readiness. A pass does not replace human review, but failures identify objective issues that must be closed or dispositioned before approval.",
    },
    "Failures": {
        "summary": "Count of deterministic compliance failures in the current review.",
        "details": "This metric counts failure-level findings such as missing trace links, missing evidence, incomplete assurance metadata, weak objective criteria, or missing non-applicability evidence depending on the audit rules triggered.",
        "sources": "The count comes from the selected review artifact's compliance report.",
        "usage": "Failure count drives required human actions and should trend to zero before approval. Each failure usually maps to one or more rows in Compliance findings.",
    },
    "Decisions": {
        "summary": "Number of RVM decision rows in the current review.",
        "details": "This metric counts drafted decisions created from the input requirement set. Each decision should correspond to a requirement ID and contain applicability, verification method, rationale, trace links, evidence references, confidence, and assurance fields when available.",
        "sources": "The count comes from the decisions array in the selected review JSON.",
        "usage": "This helps confirm input coverage. Unexpectedly low or high counts can indicate parsing problems, wrong input files, duplicate records, or a stale review artifact.",
    },
    "Avg Confidence": {
        "summary": "Average workflow confidence across RVM decisions.",
        "details": "This metric averages numeric confidence values supplied with each decision. Confidence reflects workflow certainty, retrieval support, and policy fit; it is not an approval state and should not be treated as certification evidence.",
        "sources": "Values come from decision confidence fields in the selected review artifact.",
        "usage": "Average confidence helps triage review effort. Low averages suggest missing context, ambiguous requirements, weak memory retrieval, or decisions that need more human scrutiny.",
    },
    "Low Confidence": {
        "summary": "Number of decisions below the review confidence threshold.",
        "details": "This metric counts decisions with confidence below the UI support threshold. These decisions may have weak context, ambiguous applicability, incomplete traces, or insufficient evidence support.",
        "sources": "The count comes from decision confidence fields in the selected review artifact.",
        "usage": "Low-confidence rows generate review actions and should be inspected before sign-off. Improving standards, project context, memory indexing, or known-good examples can reduce this count.",
    },
    "Not Applicable": {
        "summary": "Number of requirements marked not applicable.",
        "details": "This metric counts decisions whose applicability is not_applicable. Such decisions need explicit boundary, architecture, certification-basis, or allocation evidence explaining why the requirement is outside scope.",
        "sources": "The count comes from applicability fields in the selected review artifact.",
        "usage": "Not-applicable counts affect approval workload because each exclusion needs human review and strong evidence. Missing evidence creates compliance findings and required human actions.",
    },
    "Required human actions": {
        "summary": "Specific reviewer work needed before approval or baselining.",
        "details": "This section lists prioritized actions derived from the review decisions, compliance findings, audit findings, confidence values, assurance metadata, evidence fields, and non-applicability decisions. It includes the action type and context explaining what must be fixed, reviewed, or approved.",
        "sources": "Rows are generated from the selected review JSON by UI support logic. They are not manually entered here.",
        "usage": "Use this as the reviewer punch list. Approval should wait until required items are resolved, dispositioned, or captured in approval justification. These actions also feed learning candidates when reviewer dispositions are captured.",
    },
    "Compliance findings": {
        "summary": "Detailed deterministic audit findings for the current review.",
        "details": "Each row includes severity, rule ID, requirement ID, message, and suggested fix. Findings cover objective rule checks such as traceability, evidence anchors, execution artifacts, objective criteria, change rationale, assurance mapping, lifecycle objectives, and non-applicability evidence.",
        "sources": "Findings come from the compliance audit embedded in the selected review artifact or produced by Audit Current Review.",
        "usage": "Findings explain why Compliance is not ready and provide fix guidance. They also drive Required human actions and help reviewers decide whether to rerun the workflow, add source data, or manually correct the controlled RVM.",
    },
    "RVM decisions": {
        "summary": "Draft requirement verification matrix decisions produced by the workflow.",
        "details": "Rows show requirement ID, applicability, verification method, confidence, parent links, and child links. The backing review JSON contains additional fields such as rationale, procedure references, execution artifacts, assurance standard, DAL, lifecycle objectives, change rationale, source anchors, impacts, and audit metadata.",
        "sources": "Decisions are generated from standard or requirement documents, project context, memory retrieval, workflow policies, and any learned correction examples in crystallized memory.",
        "usage": "These decisions are the central RVM draft. They feed CSV export, compliance audit, required actions, approval context, learning capture, and downstream release or evidence artifacts. Reviewer corrections here should be reflected in controlled outputs or future learning candidates.",
    },
    "Artifact output directory": {
        "summary": "Folder scanned for generated UI artifacts.",
        "details": "Enter or confirm the directory where UI outputs are written and refreshed. The default is out/ui. The section expects a directory path, not individual artifact files.",
        "sources": "The path comes from Agent Settings and can be changed here through the same variable.",
        "usage": "Refresh scans this directory recursively and populates the artifact inventory. If this points to the wrong folder, Artifacts will appear empty or show stale files.",
    },
    "Generated artifacts": {
        "summary": "Inventory of files produced under the configured output directory.",
        "details": "This table lists artifact name, type, size, and modified timestamp. Common artifacts include review.json, compliance_report.json, review.csv, evidence_manifest.json, release_manifest.json, agent_definitions.json, improvements.json, change_proposal.json, approval records, and initial optimization reports.",
        "sources": "Rows come from files already written by UI actions or compatible CLI runs under the selected output directory.",
        "usage": "Select an artifact to inspect it in the preview pane. The inventory helps reviewers find controlled outputs, confirm timestamps, and navigate generated evidence without leaving the UI.",
    },
    "Artifact preview": {
        "summary": "Read-only preview of the selected generated artifact.",
        "details": "JSON files are pretty-printed when possible, and text-like files are shown as readable text. Very large files may be truncated for UI responsiveness. Binary files or unsupported encodings may show a preview error.",
        "sources": "The preview reads the currently selected artifact from the Generated artifacts table.",
        "usage": "Use this pane for quick inspection before opening or attaching artifacts elsewhere. Preview does not modify artifacts and does not replace controlled review of source files when fidelity matters.",
    },
    "Approval context": {
        "summary": "Review readiness context assembled from the current review artifact.",
        "details": "This section shows required human actions and the selected review artifact path. It is generated from the current review JSON and highlights unresolved work that should be considered before recording approval, rejection, baselining, or review state.",
        "sources": "Content comes from the review artifact selected in Run and the same required-action logic used by Results.",
        "usage": "Read this before creating an approval artifact. The context helps ensure the justification addresses the actual blockers and that the approval record is tied to the intended review file.",
    },
    "Record approval state": {
        "summary": "Create a signed review-state artifact for the current RVM review.",
        "details": "Enter state, author ID, role, and justification. The state can be drafted, reviewed, rejected, approved, or baselined. The justification should explain the human disposition, remaining constraints, evidence reviewed, and rationale for approval or rejection. The generated approval artifact includes timestamp and review hash metadata.",
        "sources": "Author, role, and justification should come from the responsible reviewer, approver, verification lead, certification engineer, or configuration-control authority. The review hash comes from the selected review artifact.",
        "usage": "Approval artifacts document human disposition and can optionally create learning candidates from the feedback. They affect auditability and future learning workflows, but they do not alter the original review JSON unless separate controlled edits are made.",
    },
    "Guide": {
        "summary": "Built-in operating overview for the desktop control center.",
        "details": "This section contains a compact workflow guide covering the major tabs, normal production flow, artifact locations, memory behavior, and local execution assumptions. It is informational text rather than source data.",
        "sources": "The guide summarizes repository documentation, especially the desktop UI and workflow assurance guidance.",
        "usage": "Use it as an orientation aid while operating the UI. For deeper process requirements, read the repository docs and your project-specific certification or assurance plan.",
    },
}


class FileList(ttk.Frame):
    def __init__(
        self,
        parent: ttk.Widget,
        label: str,
        filetypes: list[tuple[str, str]],
        height: int = 5,
        help_command: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.filetypes = filetypes
        self.items: list[str] = []
        header = ttk.Frame(self)
        header.pack(side=TOP, fill=X)
        ttk.Label(header, text=label, style="Section.TLabel").pack(side=LEFT)
        if help_command:
            ttk.Button(header, text="?", width=2, style="Help.TButton", command=lambda: help_command(label)).pack(
                side=LEFT, padx=(6, 0)
            )
        ttk.Button(header, text="Add", command=self.add_files).pack(side=RIGHT, padx=(4, 0))
        ttk.Button(header, text="Remove", command=self.remove_selected).pack(side=RIGHT, padx=(4, 0))

        body = ttk.Frame(self)
        body.pack(side=TOP, fill=BOTH, expand=True, pady=(4, 0))
        self.listbox = _ListBox(body, height=height)
        self.listbox.configure(
            background="#0b1118",
            foreground="#e6edf3",
            selectbackground="#2f81f7",
            selectforeground="#ffffff",
            relief="flat",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground="#334155",
            highlightcolor="#58a6ff",
        )
        self.listbox.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.listbox.configure(yscrollcommand=scrollbar.set)

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=self.filetypes)
        self.extend(paths)

    def extend(self, paths: tuple[str, ...] | list[str]) -> None:
        for path in paths:
            if path and path not in self.items:
                self.items.append(path)
                self.listbox.insert(END, path)

    def remove_selected(self) -> None:
        for index in reversed(self.listbox.curselection()):
            self.listbox.delete(index)
            del self.items[index]

    def clear(self) -> None:
        self.items.clear()
        self.listbox.delete(0, END)


class LearningAgentApp(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1280x860")
        self.minsize(1040, 720)
        self.queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.active_worker = False
        self.latest_review_path = DEFAULT_REVIEW_PATH
        self.latest_compliance_path = DEFAULT_COMPLIANCE_PATH

        self.workspace_var = StringVar(value=str(Path.cwd()))
        self.memory_root_var = StringVar(value=str(Path(".learning_agent").resolve()))
        self.out_dir_var = StringVar(value=str(Path("out/ui").resolve()))
        self.engine_var = StringVar(value="langgraph")
        self.embedder_var = StringVar(value="llama-cpp")
        self.model_path_var = StringVar(value=DEFAULT_MODEL_PATH)
        self.changed_ids_var = StringVar(value="")
        self.gold_rvm_var = StringVar(value="")
        self.review_path_var = StringVar(value=str(self.latest_review_path.resolve()))
        self.status_var = StringVar(value="Ready")

        self.learning_enabled_var = BooleanVar(value=True)
        self.auto_capture_feedback_var = BooleanVar(value=True)
        self.require_learning_approval_var = BooleanVar(value=True)
        self.search_query_var = StringVar(value="")
        self.search_scope_var = StringVar(value="Reference memory")
        self.approval_state_var = StringVar(value="reviewed")
        self.author_id_var = StringVar(value="")
        self.role_var = StringVar(value="")

        self._configure_style()
        self._build_layout()
        self._seed_examples()
        self._refresh_memory_paths()
        self._refresh_learning_queue()
        self._refresh_artifacts()
        self.after(100, self._poll_queue)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        self.configure(bg="#0f141b")
        self.option_add("*Font", ("Segoe UI", 10))
        self.option_add("*Listbox.background", "#121923")
        self.option_add("*Listbox.foreground", "#e6edf3")
        self.option_add("*Listbox.selectBackground", "#2f81f7")
        self.option_add("*Listbox.selectForeground", "#ffffff")

        bg = "#0f141b"
        surface = "#151d27"
        surface_2 = "#1b2532"
        border = "#334155"
        text = "#e6edf3"
        muted = "#94a3b8"
        accent = "#2f81f7"
        accent_hover = "#58a6ff"
        field = "#0b1118"

        style.configure(".", background=bg, foreground=text, fieldbackground=field, bordercolor=border)
        style.configure("TFrame", background=bg)
        style.configure("TLabelframe", background=bg, foreground=text, bordercolor=border, relief="solid")
        style.configure("TLabelframe.Label", background=bg, foreground="#cbd5e1", font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background=bg, foreground=text)
        style.configure("Title.TLabel", background=bg, foreground="#f8fafc", font=("Segoe UI", 18, "bold"))
        style.configure("Subtitle.TLabel", background=bg, foreground=muted, font=("Segoe UI", 10))
        style.configure("Section.TLabel", background=bg, foreground="#dbeafe", font=("Segoe UI", 10, "bold"))
        style.configure("Metric.TLabel", background=bg, foreground="#7dd3fc", font=("Segoe UI", 16, "bold"))
        style.configure("Status.TLabel", background=bg, foreground="#a7f3d0", font=("Segoe UI", 10, "bold"))
        style.configure("TButton", background=surface_2, foreground=text, bordercolor=border, focusthickness=1, padding=(10, 5))
        style.configure("Help.TButton", background=surface_2, foreground="#dbeafe", bordercolor=border, padding=(4, 1))
        style.map(
            "TButton",
            background=[("active", "#243244"), ("pressed", accent)],
            foreground=[("disabled", "#64748b"), ("active", "#ffffff")],
            bordercolor=[("focus", accent_hover)],
        )
        style.configure("TCheckbutton", background=bg, foreground=text)
        style.map("TCheckbutton", background=[("active", bg)], foreground=[("active", "#ffffff")])
        style.configure("TEntry", fieldbackground=field, foreground=text, insertcolor=text, bordercolor=border)
        style.configure("TCombobox", fieldbackground=field, background=surface_2, foreground=text, arrowcolor=text)
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", field)],
            foreground=[("readonly", text)],
            selectbackground=[("readonly", field)],
            selectforeground=[("readonly", text)],
        )
        style.configure("TNotebook", background=bg, borderwidth=0)
        style.configure("TNotebook.Tab", background=surface, foreground=muted, padding=(14, 8), bordercolor=border)
        style.map(
            "TNotebook.Tab",
            background=[("selected", surface_2), ("active", "#202b3a")],
            foreground=[("selected", "#ffffff"), ("active", "#dbeafe")],
        )
        style.configure(
            "Treeview",
            background=field,
            fieldbackground=field,
            foreground=text,
            bordercolor=border,
            rowheight=26,
        )
        style.configure("Treeview.Heading", background=surface_2, foreground="#cbd5e1", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", accent)], foreground=[("selected", "#ffffff")])
        style.configure("Action.Treeview", rowheight=28)
        style.configure("Horizontal.TProgressbar", troughcolor=field, background=accent, bordercolor=border, lightcolor=accent, darkcolor=accent)

    def _style_text_widget(self, widget: scrolledtext.ScrolledText) -> None:
        widget.configure(
            background="#0b1118",
            foreground="#e6edf3",
            insertbackground="#e6edf3",
            selectbackground="#2f81f7",
            selectforeground="#ffffff",
            relief="flat",
            borderwidth=1,
            padx=8,
            pady=6,
        )

    def _section_frame(self, parent: ttk.Widget, title: str, padding: int | tuple[int, ...] = 10) -> ttk.LabelFrame:
        header = ttk.Frame(parent)
        ttk.Label(header, text=title, style="Section.TLabel").pack(side=LEFT)
        ttk.Button(header, text="?", width=2, style="Help.TButton", command=lambda: self._show_help(title)).pack(
            side=LEFT, padx=(6, 0)
        )
        return ttk.LabelFrame(parent, labelwidget=header, padding=padding)

    def _show_help(self, title: str) -> None:
        content = HELP_SECTIONS.get(title)
        if content is None:
            messagebox.showinfo(APP_TITLE, f"No help is available for {title}.")
            return
        window = Toplevel(self)
        window.title(f"{title} Help")
        window.geometry("760x620")
        window.minsize(560, 420)
        window.configure(bg="#0f141b")
        text = scrolledtext.ScrolledText(window, wrap="word")
        self._style_text_widget(text)
        text.pack(fill=BOTH, expand=True, padx=12, pady=12)
        text.insert(
            END,
            "\n\n".join(
                [
                    title,
                    f"Short summary\n{content['summary']}",
                    f"In-depth explanation\n{content['details']}",
                    f"Where this information should come from\n{content['sources']}",
                    f"How this data is used in the workflow\n{content['usage']}",
                ]
            ),
        )
        text.configure(state="disabled")

    def _build_layout(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=BOTH, expand=True)

        header = ttk.Frame(root)
        header.pack(fill=X, pady=(0, 10))
        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").pack(side=LEFT)
        ttk.Label(
            header,
            text="Offline desktop control surface for training, RVM review, audit, approvals, and artifacts.",
            style="Subtitle.TLabel",
        ).pack(side=LEFT, padx=(16, 0))
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel").pack(side=RIGHT)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=BOTH, expand=True)

        self._build_inputs_tab()
        self._build_agent_settings_tab()
        self._build_run_tab()
        self._build_results_tab()
        self._build_artifacts_tab()
        self._build_approvals_tab()
        self._build_guide_tab()

    def _build_inputs_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Inputs")

        left = ttk.Frame(tab)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 8))
        right = ttk.Frame(tab)
        right.pack(side=RIGHT, fill=BOTH, expand=True, padx=(8, 0))

        filetypes = [
            ("Supported documents", "*.csv *.tsv *.xlsx *.json *.txt *.md *.reqif *.reqifz *.xml"),
            ("All files", "*.*"),
        ]
        self.standards_list = FileList(left, "Standard / requirement documents", filetypes, help_command=self._show_help)
        self.standards_list.pack(fill=BOTH, expand=True, pady=(0, 10))
        self.project_list = FileList(left, "Project context / DOORS exports / design documents", filetypes, help_command=self._show_help)
        self.project_list.pack(fill=BOTH, expand=True)

        self.evidence_list = FileList(
            right,
            "Evidence artifacts to hash",
            [("Evidence files", "*.*")],
            height=4,
            help_command=self._show_help,
        )
        self.evidence_list.pack(fill=BOTH, expand=True, pady=(0, 10))

    def _build_agent_settings_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Agent Settings")

        body = ttk.PanedWindow(tab, orient="horizontal")
        body.pack(fill=BOTH, expand=True)
        left = ttk.Frame(body, padding=(0, 0, 8, 0))
        right = ttk.Frame(body, padding=(8, 0, 0, 0))
        body.add(left, weight=1)
        body.add(right, weight=1)

        controls = self._section_frame(left, "Workflow and memory policy")
        controls.pack(fill=X)
        self._path_row(controls, "Workspace", self.workspace_var, self._choose_workspace, 0)
        self._path_row(controls, "Memory root", self.memory_root_var, self._choose_memory_root, 1)
        self._path_row(controls, "Output directory", self.out_dir_var, self._choose_out_dir, 2)
        self._path_row(controls, "Known-good RVM", self.gold_rvm_var, self._choose_gold_rvm, 3)
        self._path_row(controls, "GGUF model path", self.model_path_var, self._choose_model_path, 4)
        ttk.Label(controls, text="Changed requirement IDs").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Entry(controls, textvariable=self.changed_ids_var).grid(row=5, column=1, sticky="ew", pady=4, padx=(8, 8))
        ttk.Label(controls, text="Workflow engine").grid(row=6, column=0, sticky="w", pady=4)
        ttk.Combobox(
            controls,
            values=["langgraph", "built-in"],
            textvariable=self.engine_var,
            state="readonly",
            width=18,
        ).grid(row=6, column=1, sticky="w", pady=4, padx=(8, 8))
        ttk.Label(controls, text="Embedder").grid(row=7, column=0, sticky="w", pady=4)
        ttk.Combobox(
            controls,
            values=["llama-cpp", "hashing"],
            textvariable=self.embedder_var,
            state="readonly",
            width=18,
        ).grid(row=7, column=1, sticky="w", pady=4, padx=(8, 8))
        ttk.Checkbutton(controls, text="Capture review feedback as learning candidates", variable=self.auto_capture_feedback_var).grid(
            row=8, column=1, sticky="w", pady=4, padx=(8, 8)
        )
        ttk.Checkbutton(controls, text="Require approval before applying learned candidates", variable=self.require_learning_approval_var).grid(
            row=9, column=1, sticky="w", pady=4, padx=(8, 8)
        )
        ttk.Checkbutton(controls, text="Enable learning memory for future runs", variable=self.learning_enabled_var).grid(
            row=10, column=1, sticky="w", pady=4, padx=(8, 8)
        )
        controls.columnconfigure(1, weight=1)

        optimization = self._section_frame(left, "Initial optimization from known-good RVMs")
        optimization.pack(fill=X, pady=(10, 0))
        ttk.Button(optimization, text="Run Initial Optimization", command=self._run_initial_optimization).pack(side=LEFT, padx=(0, 6))
        ttk.Button(optimization, text="Crystallize Good RVM", command=self._learn_good_rvm).pack(side=LEFT, padx=6)
        ttk.Button(optimization, text="Suggest Improvements", command=self._suggest_improvements).pack(side=LEFT, padx=6)
        ttk.Button(optimization, text="Create Change Proposal", command=self._create_change_proposal).pack(side=LEFT, padx=6)

        paths = self._section_frame(left, "Resolved persistent memory locations")
        paths.pack(fill=BOTH, expand=True, pady=(10, 0))
        self.memory_paths_text = scrolledtext.ScrolledText(paths, height=9, wrap="word")
        self._style_text_widget(self.memory_paths_text)
        self.memory_paths_text.pack(fill=BOTH, expand=True)
        ttk.Button(paths, text="Refresh Memory Paths", command=self._refresh_memory_paths).pack(side=RIGHT, pady=(8, 0))

        indexing = self._section_frame(right, "Reference and project memory")
        indexing.pack(fill=X)
        ttk.Button(indexing, text="Index Reference Docs", command=self._index_reference_docs).pack(side=LEFT, padx=(0, 6))
        ttk.Button(indexing, text="Index Project Memory", command=self._index_project_docs).pack(side=LEFT, padx=6)

        queue_frame = self._section_frame(right, "Learning queue")
        queue_frame.pack(fill=BOTH, expand=True, pady=(10, 0))
        queue_buttons = ttk.Frame(queue_frame)
        queue_buttons.pack(fill=X, pady=(0, 8))
        ttk.Button(queue_buttons, text="Refresh Queue", command=self._refresh_learning_queue).pack(side=LEFT, padx=(0, 6))
        ttk.Button(queue_buttons, text="Apply Selected to Crystallized Memory", command=self._apply_selected_learning).pack(side=LEFT, padx=6)
        ttk.Button(queue_buttons, text="Reject Selected", command=self._reject_selected_learning).pack(side=LEFT, padx=6)
        self.learning_tree = ttk.Treeview(
            queue_frame,
            columns=("status", "task", "source", "created", "rationale"),
            show="headings",
            height=7,
        )
        self._setup_tree(
            self.learning_tree,
            [("status", 90), ("task", 150), ("source", 90), ("created", 170), ("rationale", 430)],
        )
        self.learning_tree.pack(fill=BOTH, expand=True)

        search = self._section_frame(right, "Search persistent memory")
        search.pack(fill=BOTH, expand=True, pady=(10, 0))
        row = ttk.Frame(search)
        row.pack(fill=X)
        ttk.Combobox(
            row,
            values=["Reference memory", "Crystallized corrections", "Project working memory"],
            textvariable=self.search_scope_var,
            state="readonly",
            width=26,
        ).pack(side=LEFT)
        ttk.Entry(row, textvariable=self.search_query_var).pack(side=LEFT, fill=X, expand=True, padx=8)
        ttk.Button(row, text="Search", command=self._search_memory).pack(side=LEFT)
        self.memory_results = scrolledtext.ScrolledText(search, wrap="word")
        self._style_text_widget(self.memory_results)
        self.memory_results.pack(fill=BOTH, expand=True, pady=(10, 0))

    def _build_run_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Run")

        actions = self._section_frame(tab, "Run actions")
        actions.pack(fill=X)
        ttk.Button(actions, text="Run Complete Draft + Audit", command=self._run_complete_review).pack(side=LEFT, padx=(0, 6))
        ttk.Button(actions, text="Audit Current Review", command=self._audit_current_review).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Export Controlled CSV", command=self._export_current_csv).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Hash Evidence", command=self._hash_evidence).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Release Manifest", command=self._release_manifest).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Export Agent Definitions", command=self._export_agent_definitions).pack(side=LEFT, padx=6)

        current = self._section_frame(tab, "Current review artifact")
        current.pack(fill=X, pady=(10, 0))
        ttk.Entry(current, textvariable=self.review_path_var).pack(side=LEFT, fill=X, expand=True, padx=8)
        ttk.Button(current, text="Select", command=self._choose_review_path).pack(side=LEFT)
        ttk.Button(current, text="Load Results", command=self._load_results_from_path).pack(side=LEFT, padx=(6, 0))

        self.progress = ttk.Progressbar(tab, mode="indeterminate")
        self.progress.pack(fill=X, pady=(12, 8))
        log_frame = self._section_frame(tab, "Run log")
        log_frame.pack(fill=BOTH, expand=True)
        self.run_log = scrolledtext.ScrolledText(log_frame, wrap="word", height=28)
        self._style_text_widget(self.run_log)
        self.run_log.pack(fill=BOTH, expand=True)

    def _build_results_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Results")

        metrics = ttk.Frame(tab)
        metrics.pack(fill=X)
        self.metric_vars = {
            "Compliance": StringVar(value="Not run"),
            "Failures": StringVar(value="0"),
            "Decisions": StringVar(value="0"),
            "Avg Confidence": StringVar(value="0.00"),
            "Low Confidence": StringVar(value="0"),
            "Not Applicable": StringVar(value="0"),
        }
        for label, var in self.metric_vars.items():
            card = self._section_frame(metrics, label)
            card.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
            ttk.Label(card, textvariable=var, style="Metric.TLabel").pack(anchor="w")

        panes = ttk.PanedWindow(tab, orient="vertical")
        panes.pack(fill=BOTH, expand=True, pady=(10, 0))

        action_frame = self._section_frame(panes, "Required human actions", padding=8)
        self.action_tree = ttk.Treeview(
            action_frame,
            columns=("priority", "action", "context"),
            show="headings",
            style="Action.Treeview",
            height=6,
        )
        self._setup_tree(self.action_tree, [("priority", 90), ("action", 230), ("context", 820)])
        self.action_tree.pack(fill=BOTH, expand=True)
        panes.add(action_frame, weight=1)

        lower = ttk.PanedWindow(panes, orient="horizontal")
        panes.add(lower, weight=3)

        findings_frame = self._section_frame(lower, "Compliance findings", padding=8)
        self.findings_tree = ttk.Treeview(
            findings_frame,
            columns=("severity", "rule_id", "requirement_id", "message", "fix"),
            show="headings",
        )
        self._setup_tree(
            self.findings_tree,
            [("severity", 80), ("rule_id", 150), ("requirement_id", 140), ("message", 400), ("fix", 400)],
        )
        self.findings_tree.pack(fill=BOTH, expand=True)
        lower.add(findings_frame, weight=1)

        decisions_frame = self._section_frame(lower, "RVM decisions", padding=8)
        self.decisions_tree = ttk.Treeview(
            decisions_frame,
            columns=("requirement_id", "applicability", "method", "confidence", "parents", "children"),
            show="headings",
        )
        self._setup_tree(
            self.decisions_tree,
            [
                ("requirement_id", 140),
                ("applicability", 130),
                ("method", 110),
                ("confidence", 90),
                ("parents", 180),
                ("children", 180),
            ],
        )
        self.decisions_tree.pack(fill=BOTH, expand=True)
        lower.add(decisions_frame, weight=1)

    def _build_artifacts_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Artifacts")

        top = self._section_frame(tab, "Artifact output directory")
        top.pack(fill=X)
        ttk.Entry(top, textvariable=self.out_dir_var).pack(side=LEFT, fill=X, expand=True, padx=8)
        ttk.Button(top, text="Refresh", command=self._refresh_artifacts).pack(side=LEFT)

        panes = ttk.PanedWindow(tab, orient="horizontal")
        panes.pack(fill=BOTH, expand=True, pady=(10, 0))
        left = self._section_frame(panes, "Generated artifacts")
        right = self._section_frame(panes, "Artifact preview")
        panes.add(left, weight=1)
        panes.add(right, weight=2)

        self.artifacts_tree = ttk.Treeview(
            left,
            columns=("name", "type", "size", "modified"),
            show="headings",
        )
        self._setup_tree(
            self.artifacts_tree,
            [("name", 280), ("type", 80), ("size", 90), ("modified", 150)],
        )
        self.artifacts_tree.pack(fill=BOTH, expand=True)
        self.artifacts_tree.bind("<<TreeviewSelect>>", self._preview_selected_artifact)

        self.artifact_preview = scrolledtext.ScrolledText(right, wrap="word")
        self._style_text_widget(self.artifact_preview)
        self.artifact_preview.pack(fill=BOTH, expand=True)

    def _build_approvals_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Approvals")

        left = self._section_frame(tab, "Approval context")
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 8))
        right = self._section_frame(tab, "Record approval state")
        right.pack(side=RIGHT, fill=BOTH, expand=True, padx=(8, 0))

        self.approval_context = scrolledtext.ScrolledText(left, wrap="word")
        self._style_text_widget(self.approval_context)
        self.approval_context.pack(fill=BOTH, expand=True)
        ttk.Button(left, text="Refresh Approval Context", command=self._refresh_approval_context).pack(
            side=RIGHT, pady=(8, 0)
        )

        ttk.Label(right, text="State").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(
            right,
            values=["drafted", "reviewed", "rejected", "approved", "baselined"],
            textvariable=self.approval_state_var,
            state="readonly",
        ).grid(row=0, column=1, sticky="ew", pady=4, padx=(8, 0))
        self._entry_row(right, "Author ID", self.author_id_var, 1)
        self._entry_row(right, "Role", self.role_var, 2)
        ttk.Label(right, text="Justification").grid(row=3, column=0, sticky="nw", pady=4)
        self.justification_text = scrolledtext.ScrolledText(right, height=10, wrap="word")
        self._style_text_widget(self.justification_text)
        self.justification_text.grid(row=3, column=1, sticky="nsew", pady=4, padx=(8, 0))
        ttk.Button(right, text="Create Approval Artifact", command=self._record_approval).grid(
            row=4, column=1, sticky="e", pady=(8, 0)
        )
        right.columnconfigure(1, weight=1)
        right.rowconfigure(3, weight=1)

    def _build_guide_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Guide")
        guide_frame = self._section_frame(tab, "Guide")
        guide_frame.pack(fill=BOTH, expand=True)
        guide = scrolledtext.ScrolledText(guide_frame, wrap="word")
        self._style_text_widget(guide)
        guide.pack(fill=BOTH, expand=True)
        guide.insert(
            END,
            "\n".join(
                [
                    "LearningAgent UI workflow",
                    "",
                    "1. Inputs: add standards, DOORS/ReqIF or Excel exports, project context, and evidence files.",
                    "2. Agent Settings: configure workflow, memory, learning policy, initial optimization, and the learning queue.",
                    "3. Run: execute the draft RVM workflow, audit it deterministically, export controlled CSVs, hash evidence, and create release manifests.",
                    "4. Results: review confidence, compliance failures, not-applicable decisions, impact analysis, and the exact human actions required before sign-off.",
                    "5. Artifacts: inspect generated JSON, CSV, manifests, proposals, and approval records from the configured output directory.",
                    "6. Approvals: record drafted, reviewed, rejected, approved, or baselined state with an author, role, justification, timestamp, RVM hash, and optional learning candidate.",
                    "",
                    "The authoritative operating guide is docs/workflow_assurance_guide.md.",
                    "Generated operational artifacts are written under the configured output directory, defaulting to out/ui/.",
                    "Persistent memories are file-backed under the configured memory root. Workspace memory is isolated by workspace path.",
                    "No local network host or loopback address is used by this UI.",
                ]
            ),
        )
        guide.configure(state="disabled")

    def _path_row(
        self,
        parent: ttk.Frame,
        label: str,
        variable: StringVar,
        command: Callable[[], None],
        row: int,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4, padx=(8, 8))
        ttk.Button(parent, text="Browse", command=command).grid(row=row, column=2, sticky="e", pady=4)

    def _entry_row(self, parent: ttk.Frame, label: str, variable: StringVar, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4, padx=(8, 0))

    def _setup_tree(self, tree: ttk.Treeview, columns: list[tuple[str, int]]) -> None:
        for name, width in columns:
            tree.heading(name, text=name.replace("_", " ").title())
            tree.column(name, width=width, stretch=True)
        scrollbar = ttk.Scrollbar(tree.master, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=RIGHT, fill=Y)

    def _seed_examples(self) -> None:
        standards = Path("examples/standards.csv")
        project = Path("examples/project.txt")
        gold = Path("examples/gold_rvm.csv")
        if standards.exists():
            self.standards_list.extend([str(standards.resolve())])
        if project.exists():
            self.project_list.extend([str(project.resolve())])
        if gold.exists():
            self.gold_rvm_var.set(str(gold.resolve()))
        self.changed_ids_var.set("STD-001")

    def _choose_workspace(self) -> None:
        path = filedialog.askdirectory(initialdir=self.workspace_var.get() or str(Path.cwd()))
        if path:
            self.workspace_var.set(path)
            self._refresh_memory_paths()

    def _choose_memory_root(self) -> None:
        path = filedialog.askdirectory(initialdir=self.memory_root_var.get() or str(Path.cwd()))
        if path:
            self.memory_root_var.set(path)
            self._refresh_memory_paths()

    def _choose_out_dir(self) -> None:
        path = filedialog.askdirectory(initialdir=self.out_dir_var.get() or str(Path.cwd()))
        if path:
            self.out_dir_var.set(path)
            self._refresh_artifacts()

    def _choose_gold_rvm(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("RVM files", "*.csv *.tsv *.xlsx"), ("All files", "*.*")]
        )
        if path:
            self.gold_rvm_var.set(path)

    def _choose_model_path(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("GGUF models", "*.gguf"), ("All files", "*.*")])
        if path:
            self.model_path_var.set(path)

    def _choose_review_path(self) -> None:
        path = filedialog.askopenfilename(
            initialdir=self.out_dir_var.get() or str(Path.cwd()),
            filetypes=[("Review JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.review_path_var.set(path)
            self.latest_review_path = Path(path)

    def _refresh_memory_paths(self) -> None:
        paths = default_memory_paths(self.workspace_var.get(), self.memory_root_var.get())
        inventory = memory_inventory(paths)
        self.memory_paths_text.configure(state="normal")
        self.memory_paths_text.delete("1.0", END)
        self.memory_paths_text.insert(END, format_memory_inventory(inventory))
        self.memory_paths_text.configure(state="disabled")

    def _changed_ids(self) -> list[str]:
        raw = self.changed_ids_var.get().replace("\n", ",").replace(";", ",")
        return [item.strip() for item in raw.split(",") if item.strip()]

    def _out_path(self, name: str) -> Path:
        return Path(self.out_dir_var.get() or "out/ui") / name

    def _build_embedder(self, embedder_name: str, model_path: str):
        if embedder_name == "llama-cpp":
            return LlamaCppEmbedder(model_path=model_path)
        return HashingEmbedder()

    def _run_worker(
        self,
        label: str,
        worker: Callable[[], Any],
        on_success: Callable[[Any], str] | None = None,
    ) -> None:
        if self.active_worker:
            messagebox.showinfo(APP_TITLE, "Another operation is still running.")
            return
        self.active_worker = True
        self.status_var.set(label)
        self.progress.start(12)
        self._log(f"Started: {label}")
        thread = threading.Thread(target=self._worker_entry, args=(label, worker, on_success), daemon=True)
        thread.start()

    def _worker_entry(
        self,
        label: str,
        worker: Callable[[], Any],
        on_success: Callable[[Any], str] | None,
    ) -> None:
        try:
            result = worker()
            self.queue.put(("done", (label, result, on_success)))
        except Exception as exc:  # pragma: no cover - exercised through manual UI use
            self.queue.put(("error", (label, exc)))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "done":
                    label, result, on_success = payload
                    message = on_success(result) if on_success else str(result)
                    self._log(f"Finished: {label}\n{message}")
                    self.status_var.set("Ready")
                    self.active_worker = False
                    self.progress.stop()
                    self._refresh_artifacts()
                    self._refresh_learning_queue()
                    self._refresh_memory_paths()
                    self._load_results_if_available()
                elif kind == "error":
                    label, exc = payload
                    self._log(f"Error during {label}: {exc}")
                    self.status_var.set("Error")
                    self.active_worker = False
                    self.progress.stop()
                    messagebox.showerror(APP_TITLE, str(exc))
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _log(self, message: str) -> None:
        self.run_log.insert(END, f"{message}\n\n")
        self.run_log.see(END)

    def _run_complete_review(self) -> None:
        standards = list(self.standards_list.items)
        projects = list(self.project_list.items)
        changed_ids = self._changed_ids()
        engine = self.engine_var.get()
        workspace = self.workspace_var.get()
        memory_root = self.memory_root_var.get()
        embedder_name = self.embedder_var.get()
        model_path = self.model_path_var.get()
        review_out = self._out_path("review.json")
        compliance_out = self._out_path("compliance_report.json")

        def worker() -> dict[str, Path]:
            if not standards:
                raise ValueError("Add at least one standard or requirements document.")
            if not projects:
                raise ValueError("Add at least one project context document.")
            result = review_rvm(
                standards,
                projects,
                changed_ids,
                engine=engine,
                workspace=workspace,
                memory_root=memory_root,
                embedder=self._build_embedder(embedder_name, model_path),
                use_memory=True,
                index_memory=True,
            )
            write_json(review_out, result["result"])
            write_json(compliance_out, result["result"].get("compliance_report", {}))
            return {"review": review_out, "compliance": compliance_out}

        def done(result: dict[str, Path]) -> str:
            self.latest_review_path = result["review"]
            self.latest_compliance_path = result["compliance"]
            self.review_path_var.set(str(result["review"].resolve()))
            return f"Wrote review to {result['review'].resolve()}"

        self._run_worker("Run complete RVM workflow", worker, done)

    def _audit_current_review(self) -> None:
        review_path = Path(self.review_path_var.get())
        out = self._out_path("compliance_report.json")

        def worker() -> Path:
            if not review_path.exists():
                raise FileNotFoundError(f"Review artifact not found: {review_path}")
            report = audit_compliance_from_file(review_path)
            review_data = json.loads(review_path.read_text(encoding="utf-8"))
            review_data["compliance_report"] = report.to_dict()
            review_data.setdefault("verification_artifact", {})["compliance_passed"] = report.passed
            review_data.setdefault("verification_artifact", {})["compliance_failure_count"] = report.failure_count
            write_json(review_path, review_data)
            write_json(out, report.to_dict())
            return out

        def done(result: Path) -> str:
            self.latest_compliance_path = result
            return f"Wrote deterministic compliance report to {result.resolve()}"

        self._run_worker("Audit current review", worker, done)

    def _export_current_csv(self) -> None:
        review_path = Path(self.review_path_var.get())
        out = self._out_path("review.csv")

        def worker() -> str:
            if not review_path.exists():
                raise FileNotFoundError(f"Review artifact not found: {review_path}")
            export_rvm_csv(review_path, out)
            return f"Wrote controlled RVM CSV to {out.resolve()}"

        self._run_worker("Export controlled CSV", worker)

    def _hash_evidence(self) -> None:
        evidence = list(self.evidence_list.items)
        out = self._out_path("evidence_manifest.json")

        def worker() -> str:
            if not evidence:
                raise ValueError("Add evidence files before hashing evidence.")
            manifest = write_manifest(evidence, out)
            return f"Wrote {len(manifest.files)} evidence hash record(s) to {out.resolve()}"

        self._run_worker("Hash evidence artifacts", worker)

    def _release_manifest(self) -> None:
        out = self._out_path("release_manifest.json")

        def worker() -> str:
            files = tracked_files()
            manifest = write_manifest(files, out)
            return f"Wrote {len(manifest.files)} release/source hash record(s) to {out.resolve()}"

        self._run_worker("Create release manifest", worker)

    def _export_agent_definitions(self) -> None:
        out = self._out_path("agent_definitions.json")

        def worker() -> str:
            write_json(out, agent_definitions_as_dict())
            return f"Wrote versioned agent definitions to {out.resolve()}"

        self._run_worker("Export agent definitions", worker)

    def _learn_good_rvm(self) -> None:
        gold_path = self.gold_rvm_var.get()
        standards = list(self.standards_list.items)
        workspace = self.workspace_var.get()
        memory_root = self.memory_root_var.get()
        embedder_name = self.embedder_var.get()
        model_path = self.model_path_var.get()

        def worker() -> str:
            if not gold_path:
                raise ValueError("Select a known-good RVM first.")
            if not standards:
                raise ValueError("Add standards used by the known-good RVM.")
            paths = default_memory_paths(workspace, memory_root)
            memory = CorrectionMemory(paths.crystallized_store, self._build_embedder(embedder_name, model_path))
            requirements = {
                req.id: req
                for standard in standards
                for req in parse_requirements(standard)
            }
            pairs = []
            for decision in parse_good_rvm(gold_path):
                req = requirements.get(decision.requirement_id)
                pairs.append(
                    CorrectionPair(
                        task="rvm_decision",
                        input_text=req.text if req else decision.requirement_id,
                        bad_output="",
                        corrected_output=(
                            f"applicability={decision.applicability}; "
                            f"verification_method={decision.verification_method}; "
                            f"trace_links={','.join(decision.trace_links)}"
                        ),
                        rationale=decision.rationale,
                        tags=["gold_rvm", decision.requirement_id],
                    )
                )
            ids = memory.add_pairs(pairs)
            return f"Crystallized {len(ids)} known-good RVM row(s) into {paths.crystallized_store}"

        self._run_worker("Crystallize known-good RVM", worker)

    def _index_reference_docs(self) -> None:
        standards = list(self.standards_list.items)
        workspace = self.workspace_var.get()
        memory_root = self.memory_root_var.get()
        embedder_name = self.embedder_var.get()
        model_path = self.model_path_var.get()

        def worker() -> str:
            if not standards:
                raise ValueError("Add standard/reference documents first.")
            paths = default_memory_paths(workspace, memory_root)
            memory = ReferenceMemory(paths.reference_store, self._build_embedder(embedder_name, model_path))
            ids = memory.index_files(standards)
            return f"Indexed {len(ids)} reference record(s) into {paths.reference_store}"

        self._run_worker("Index reference documents", worker)

    def _index_project_docs(self) -> None:
        projects = list(self.project_list.items)
        workspace = self.workspace_var.get()
        memory_root = self.memory_root_var.get()
        embedder_name = self.embedder_var.get()
        model_path = self.model_path_var.get()

        def worker() -> str:
            if not projects:
                raise ValueError("Add project context documents first.")
            memory = WorkspaceMemory(workspace, memory_root, self._build_embedder(embedder_name, model_path))
            ids = memory.index_project_files(projects)
            return f"Indexed {len(ids)} project record(s) into {memory.paths.working_store}"

        self._run_worker("Index project working memory", worker)

    def _run_initial_optimization(self) -> None:
        gold_path = self.gold_rvm_var.get()
        standards = list(self.standards_list.items)
        projects = list(self.project_list.items)
        workspace = self.workspace_var.get()
        memory_root = self.memory_root_var.get()
        embedder_name = self.embedder_var.get()
        model_path = self.model_path_var.get()
        review = Path(self.review_path_var.get())
        report_out = self._out_path("initial_optimization_report.json")
        improvements_out = self._out_path("improvements.json")

        def worker() -> str:
            if not gold_path:
                raise ValueError("Select a known-good RVM first.")
            if not standards:
                raise ValueError("Add standards used by the known-good RVM.")
            paths = default_memory_paths(workspace, memory_root)
            embedder = self._build_embedder(embedder_name, model_path)
            reference_ids = ReferenceMemory(paths.reference_store, embedder).index_files(standards)
            project_ids: list[str] = []
            if projects:
                project_ids = WorkspaceMemory(workspace, memory_root, embedder).index_project_files(projects)
            requirements = {
                req.id: req
                for standard in standards
                for req in parse_requirements(standard)
            }
            pairs = []
            for decision in parse_good_rvm(gold_path):
                req = requirements.get(decision.requirement_id)
                pairs.append(
                    CorrectionPair(
                        task="rvm_decision",
                        input_text=req.text if req else decision.requirement_id,
                        bad_output="",
                        corrected_output=(
                            f"applicability={decision.applicability}; "
                            f"verification_method={decision.verification_method}; "
                            f"trace_links={','.join(decision.trace_links)}"
                        ),
                        rationale=decision.rationale,
                        tags=["gold_rvm", decision.requirement_id, "initial_optimization"],
                    )
                )
            correction_ids = CorrectionMemory(paths.crystallized_store, embedder).add_pairs(pairs)
            improvement_written = False
            if review.exists():
                plan = suggest_rvm_improvements(gold_path, review, standards, projects)
                write_json(improvements_out, plan.to_dict())
                improvement_written = True
            write_json(
                report_out,
                {
                    "known_good_rvm": gold_path,
                    "reference_records_indexed": len(reference_ids),
                    "project_records_indexed": len(project_ids),
                    "crystallized_examples": len(correction_ids),
                    "improvements_written": str(improvements_out.resolve()) if improvement_written else "",
                    "memory": {
                        "shared_canonical_store": str(paths.reference_store),
                        "workspace_canonical_store": str(paths.working_store),
                    },
                },
            )
            return (
                f"Initial optimization complete. Indexed {len(reference_ids)} reference record(s), "
                f"{len(project_ids)} project record(s), and crystallized {len(correction_ids)} known-good example(s). "
                f"Wrote report to {report_out.resolve()}"
            )

        self._run_worker("Run initial optimization", worker)

    def _learning_queue_file(self) -> Path:
        paths = default_memory_paths(self.workspace_var.get(), self.memory_root_var.get())
        return learning_queue_path(paths)

    def _refresh_learning_queue(self) -> None:
        if not hasattr(self, "learning_tree"):
            return
        queue_file = self._learning_queue_file()
        candidates = load_learning_candidates(queue_file)
        for item in self.learning_tree.get_children():
            self.learning_tree.delete(item)
        for candidate in candidates:
            self.learning_tree.insert(
                "",
                END,
                iid=candidate.get("id", ""),
                values=(
                    candidate.get("status", ""),
                    candidate.get("task", ""),
                    candidate.get("source", ""),
                    candidate.get("created_utc", ""),
                    candidate.get("rationale", "")[:220],
                ),
            )

    def _apply_selected_learning(self) -> None:
        selected = set(self.learning_tree.selection())
        workspace = self.workspace_var.get()
        memory_root = self.memory_root_var.get()
        embedder_name = self.embedder_var.get()
        model_path = self.model_path_var.get()

        def worker() -> str:
            if not selected:
                raise ValueError("Select one or more learning candidates first.")
            paths = default_memory_paths(workspace, memory_root)
            queue_file = learning_queue_path(paths)
            candidates = [
                candidate
                for candidate in load_learning_candidates(queue_file)
                if candidate.get("id") in selected and candidate.get("status") == "pending"
            ]
            if not candidates:
                raise ValueError("No pending selected learning candidates were found.")
            pairs = [
                CorrectionPair(
                    task=str(candidate.get("task", "review_feedback")),
                    input_text=str(candidate.get("input_text", "")),
                    bad_output=str(candidate.get("bad_output", "")),
                    corrected_output=str(candidate.get("corrected_output", "")),
                    rationale=str(candidate.get("rationale", "")),
                    tags=list(candidate.get("tags", [])),
                )
                for candidate in candidates
            ]
            memory = CorrectionMemory(paths.crystallized_store, self._build_embedder(embedder_name, model_path))
            applied_ids = memory.add_pairs(pairs)
            update_learning_candidate_status(queue_file, selected, "approved", applied_ids)
            return f"Applied {len(applied_ids)} learning candidate(s) to {paths.crystallized_store}"

        self._run_worker("Apply selected learning candidates", worker, lambda message: self._learning_action_done(message))

    def _reject_selected_learning(self) -> None:
        selected = set(self.learning_tree.selection())
        queue_file = self._learning_queue_file()

        def worker() -> str:
            if not selected:
                raise ValueError("Select one or more learning candidates first.")
            changed = update_learning_candidate_status(queue_file, selected, "rejected")
            return f"Rejected {changed} learning candidate(s)."

        self._run_worker("Reject selected learning candidates", worker, lambda message: self._learning_action_done(message))

    def _learning_action_done(self, message: str) -> str:
        self._refresh_learning_queue()
        self._refresh_memory_paths()
        return message

    def _search_memory(self) -> None:
        query = self.search_query_var.get().strip()
        workspace = self.workspace_var.get()
        memory_root = self.memory_root_var.get()
        embedder_name = self.embedder_var.get()
        model_path = self.model_path_var.get()
        scope = self.search_scope_var.get()

        def worker() -> str:
            if not query:
                raise ValueError("Enter a memory search query.")
            paths = default_memory_paths(workspace, memory_root)
            embedder = self._build_embedder(embedder_name, model_path)
            if scope == "Reference memory":
                results = ReferenceMemory(paths.reference_store, embedder).search(query)
            elif scope == "Crystallized corrections":
                results = CorrectionMemory(paths.crystallized_store, embedder).search(query)
            else:
                results = WorkspaceMemory(workspace, memory_root, embedder).search(query)
            return json.dumps([item.to_dict(include_embedding=False) for item in results], indent=2)

        self._run_worker("Search memory", worker, self._memory_search_done)

    def _memory_search_done(self, text: str) -> str:
        self.memory_results.configure(state="normal")
        self.memory_results.delete("1.0", END)
        self.memory_results.insert(END, text)
        return "Memory search complete."

    def _suggest_improvements(self) -> None:
        gold = self.gold_rvm_var.get()
        review = Path(self.review_path_var.get())
        standards = list(self.standards_list.items)
        projects = list(self.project_list.items)
        out = self._out_path("improvements.json")

        def worker() -> str:
            if not gold:
                raise ValueError("Select a known-good RVM first.")
            if not review.exists():
                raise FileNotFoundError(f"Review artifact not found: {review}")
            plan = suggest_rvm_improvements(gold, review, standards, projects)
            write_json(out, plan.to_dict())
            return f"Wrote improvement suggestions to {out.resolve()}"

        self._run_worker("Suggest workflow improvements", worker)

    def _create_change_proposal(self) -> None:
        improvements = self._out_path("improvements.json")
        author = self.author_id_var.get().strip() or "unknown"
        rationale = self._text(self.justification_text) or "UI-generated proposal for reviewed workflow improvement."
        out = self._out_path("change_proposal.json")

        def worker() -> str:
            if not improvements.exists():
                raise FileNotFoundError(f"Improvement plan not found: {improvements}")
            create_change_proposal(improvements, author, rationale, out)
            return f"Wrote governed change proposal to {out.resolve()}"

        self._run_worker("Create change proposal", worker)

    def _record_approval(self) -> None:
        review_path = Path(self.review_path_var.get())
        state = self.approval_state_var.get()
        author = self.author_id_var.get().strip()
        role = self.role_var.get().strip()
        justification = self._text(self.justification_text)
        out = self._out_path(f"approval_{state}.json")
        auto_capture = self.auto_capture_feedback_var.get()
        learning_enabled = self.learning_enabled_var.get()
        require_learning_approval = self.require_learning_approval_var.get()
        workspace = self.workspace_var.get()
        memory_root = self.memory_root_var.get()
        embedder_name = self.embedder_var.get()
        model_path = self.model_path_var.get()

        def worker() -> str:
            if not review_path.exists():
                raise FileNotFoundError(f"Review artifact not found: {review_path}")
            if not author or not role or not justification:
                raise ValueError("Author ID, role, and justification are required for approval records.")
            create_approval_record(review_path, state, author, role, justification, out)
            learning_message = ""
            if auto_capture and learning_enabled:
                review_data = load_review(review_path)
                actions = required_human_actions(review_data)
                summary = summarize_review(review_path)
                candidate = create_learning_candidate(
                    task=f"review_{state}",
                    input_text=json.dumps(
                        {
                            "review_path": str(review_path.resolve()),
                            "state": state,
                            "summary": {
                                "decision_count": summary["decision_count"],
                                "average_confidence": summary["average_confidence"],
                                "compliance_failure_count": summary["compliance_failure_count"],
                                "required_human_actions": actions,
                            },
                        },
                        indent=2,
                    ),
                    bad_output="\n".join(f"{item['action']}: {item['context']}" for item in actions),
                    corrected_output=f"Reviewer disposition: {state}\nRole: {role}\nJustification: {justification}",
                    rationale=justification,
                    tags=["ui_feedback", state, role],
                    source="approval_workflow",
                )
                paths = default_memory_paths(workspace, memory_root)
                if require_learning_approval:
                    queue_file = learning_queue_path(paths)
                    candidate_id = append_learning_candidate(queue_file, candidate)
                    learning_message = f"\nCaptured learning candidate {candidate_id} in {queue_file}"
                else:
                    memory = CorrectionMemory(
                        paths.crystallized_store,
                        self._build_embedder(embedder_name, model_path),
                    )
                    ids = memory.add_pairs(
                        [
                            CorrectionPair(
                                task=candidate["task"],
                                input_text=candidate["input_text"],
                                bad_output=candidate["bad_output"],
                                corrected_output=candidate["corrected_output"],
                                rationale=candidate["rationale"],
                                tags=list(candidate["tags"]),
                            )
                        ]
                    )
                    learning_message = f"\nApplied learning candidate directly as {', '.join(ids)}"
            return f"Wrote approval record to {out.resolve()}{learning_message}"

        self._run_worker("Record approval state", worker)

    def _load_results_from_path(self) -> None:
        self.latest_review_path = Path(self.review_path_var.get())
        self._load_results_if_available()
        self._refresh_approval_context()

    def _load_results_if_available(self) -> None:
        path = Path(self.review_path_var.get())
        if not path.exists():
            return
        try:
            summary = summarize_review(path)
            data = load_review(path)
        except (OSError, json.JSONDecodeError, ValueError):
            return
        self.metric_vars["Compliance"].set("Pass" if summary["compliance_passed"] else "Needs Review")
        self.metric_vars["Failures"].set(str(summary["compliance_failure_count"]))
        self.metric_vars["Decisions"].set(str(summary["decision_count"]))
        self.metric_vars["Avg Confidence"].set(format_score(summary["average_confidence"]))
        self.metric_vars["Low Confidence"].set(str(summary["low_confidence_count"]))
        self.metric_vars["Not Applicable"].set(str(summary["not_applicable_count"]))

        self._replace_tree(
            self.action_tree,
            [
                (item["priority"], item["action"], item["context"])
                for item in summary["required_human_actions"]
            ],
        )
        findings = data.get("compliance_report", {}).get("findings", [])
        self._replace_tree(
            self.findings_tree,
            [
                (
                    item.get("severity", ""),
                    item.get("rule_id", ""),
                    item.get("requirement_id", ""),
                    item.get("message", ""),
                    item.get("fix", ""),
                )
                for item in findings
            ],
        )
        self._replace_tree(
            self.decisions_tree,
            [
                (
                    item.get("requirement_id", ""),
                    item.get("applicability", ""),
                    item.get("verification_method", ""),
                    format_score(item.get("confidence", 0.0)),
                    ";".join(item.get("parent_ids", [])),
                    ";".join(item.get("child_ids", [])),
                )
                for item in data.get("decisions", [])
            ],
        )

    def _refresh_approval_context(self) -> None:
        path = Path(self.review_path_var.get())
        self.approval_context.configure(state="normal")
        self.approval_context.delete("1.0", END)
        if not path.exists():
            self.approval_context.insert(END, "Run or select a review artifact before recording approvals.")
        else:
            data = load_review(path)
            actions = required_human_actions(data)
            self.approval_context.insert(END, "Required human actions before approval:\n\n")
            for index, action in enumerate(actions, start=1):
                self.approval_context.insert(
                    END,
                    f"{index}. [{action['priority']}] {action['action']}\n{action['context']}\n\n",
                )
            self.approval_context.insert(END, f"Review artifact: {path.resolve()}\n")
        self.approval_context.configure(state="disabled")

    def _refresh_artifacts(self) -> None:
        inventory = artifact_inventory(self.out_dir_var.get())
        for item in self.artifacts_tree.get_children():
            self.artifacts_tree.delete(item)
        for artifact in inventory:
            self.artifacts_tree.insert(
                "",
                END,
                iid=artifact.path,
                values=(artifact.name, artifact.suffix or "file", artifact.size_bytes, artifact.modified_iso),
            )

    def _preview_selected_artifact(self, _event: Any = None) -> None:
        selection = self.artifacts_tree.selection()
        if not selection:
            return
        path = Path(selection[0])
        self.artifact_preview.configure(state="normal")
        self.artifact_preview.delete("1.0", END)
        try:
            if path.suffix.lower() == ".json":
                data = json.loads(path.read_text(encoding="utf-8"))
                self.artifact_preview.insert(END, json.dumps(data, indent=2))
            else:
                self.artifact_preview.insert(END, path.read_text(encoding="utf-8")[:120000])
        except Exception as exc:  # pragma: no cover - manual UI file handling
            self.artifact_preview.insert(END, f"Preview unavailable: {exc}")
        self.artifact_preview.configure(state="disabled")

    def _replace_tree(self, tree: ttk.Treeview, rows: list[tuple[Any, ...]]) -> None:
        for item in tree.get_children():
            tree.delete(item)
        for row in rows:
            tree.insert("", END, values=row)

    def _text(self, widget: scrolledtext.ScrolledText) -> str:
        return widget.get("1.0", END).strip()


class _ListBox(Listbox):
    """Small wrapper to keep the main UI imports tidy."""


def main() -> None:
    app = LearningAgentApp()
    app.mainloop()


if __name__ == "__main__":
    main()
