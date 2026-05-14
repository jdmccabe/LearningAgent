from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from tkinter import END, BOTH, LEFT, RIGHT, TOP, X, Y, Listbox, StringVar, Tk, filedialog, messagebox, scrolledtext, ttk
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
    artifact_inventory,
    format_score,
    load_review,
    memory_inventory,
    required_human_actions,
    summarize_review,
)


APP_TITLE = "LearningAgent RVM Control Center"
DEFAULT_MODEL_PATH = "models/ollama/embeddinggemma/embeddinggemma.gguf"
DEFAULT_REVIEW_PATH = Path("out/ui/review.json")
DEFAULT_COMPLIANCE_PATH = Path("out/ui/compliance_report.json")


class FileList(ttk.Frame):
    def __init__(
        self,
        parent: ttk.Widget,
        label: str,
        filetypes: list[tuple[str, str]],
        height: int = 5,
    ) -> None:
        super().__init__(parent)
        self.filetypes = filetypes
        self.items: list[str] = []
        header = ttk.Frame(self)
        header.pack(side=TOP, fill=X)
        ttk.Label(header, text=label, style="Section.TLabel").pack(side=LEFT)
        ttk.Button(header, text="Add", command=self.add_files).pack(side=RIGHT, padx=(4, 0))
        ttk.Button(header, text="Remove", command=self.remove_selected).pack(side=RIGHT, padx=(4, 0))

        body = ttk.Frame(self)
        body.pack(side=TOP, fill=BOTH, expand=True, pady=(4, 0))
        self.listbox = _ListBox(body, height=height)
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
        self.engine_var = StringVar(value="default")
        self.embedder_var = StringVar(value="hashing")
        self.model_path_var = StringVar(value=DEFAULT_MODEL_PATH)
        self.changed_ids_var = StringVar(value="")
        self.gold_rvm_var = StringVar(value="")
        self.review_path_var = StringVar(value=str(self.latest_review_path.resolve()))
        self.status_var = StringVar(value="Ready")

        self.correction_task_var = StringVar(value="rvm_decision")
        self.correction_tags_var = StringVar(value="")
        self.search_query_var = StringVar(value="")
        self.search_scope_var = StringVar(value="Reference memory")
        self.approval_state_var = StringVar(value="reviewed")
        self.author_id_var = StringVar(value="")
        self.role_var = StringVar(value="")

        self._configure_style()
        self._build_layout()
        self._seed_examples()
        self._refresh_memory_paths()
        self._refresh_artifacts()
        self.after(100, self._poll_queue)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), foreground="#445063")
        style.configure("Section.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Metric.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Action.Treeview", rowheight=28)

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
        self._build_training_tab()
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
        self.standards_list = FileList(left, "Standard / requirement documents", filetypes)
        self.standards_list.pack(fill=BOTH, expand=True, pady=(0, 10))
        self.project_list = FileList(left, "Project context / DOORS exports / design documents", filetypes)
        self.project_list.pack(fill=BOTH, expand=True)

        self.evidence_list = FileList(right, "Evidence artifacts to hash", [("Evidence files", "*.*")], height=4)
        self.evidence_list.pack(fill=BOTH, expand=True, pady=(0, 10))

        controls = ttk.LabelFrame(right, text="Run configuration", padding=10)
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
            values=["default", "langgraph"],
            textvariable=self.engine_var,
            state="readonly",
            width=18,
        ).grid(row=6, column=1, sticky="w", pady=4, padx=(8, 8))
        ttk.Label(controls, text="Embedder").grid(row=7, column=0, sticky="w", pady=4)
        ttk.Combobox(
            controls,
            values=["hashing", "llama-cpp"],
            textvariable=self.embedder_var,
            state="readonly",
            width=18,
        ).grid(row=7, column=1, sticky="w", pady=4, padx=(8, 8))
        controls.columnconfigure(1, weight=1)

        paths = ttk.LabelFrame(right, text="Resolved persistent memory locations", padding=10)
        paths.pack(fill=BOTH, expand=True, pady=(10, 0))
        self.memory_paths_text = scrolledtext.ScrolledText(paths, height=9, wrap="word")
        self.memory_paths_text.pack(fill=BOTH, expand=True)
        ttk.Button(paths, text="Refresh Memory Paths", command=self._refresh_memory_paths).pack(side=RIGHT, pady=(8, 0))

    def _build_training_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Training & Memory")

        top = ttk.Frame(tab)
        top.pack(fill=X)
        ttk.Button(top, text="Crystallize Good RVM", command=self._learn_good_rvm).pack(side=LEFT, padx=(0, 6))
        ttk.Button(top, text="Index Reference Docs", command=self._index_reference_docs).pack(side=LEFT, padx=6)
        ttk.Button(top, text="Index Project Memory", command=self._index_project_docs).pack(side=LEFT, padx=6)
        ttk.Button(top, text="Suggest Improvements", command=self._suggest_improvements).pack(side=LEFT, padx=6)
        ttk.Button(top, text="Create Change Proposal", command=self._create_change_proposal).pack(side=LEFT, padx=6)

        body = ttk.PanedWindow(tab, orient="horizontal")
        body.pack(fill=BOTH, expand=True, pady=(10, 0))
        left = ttk.Frame(body, padding=(0, 0, 8, 0))
        right = ttk.Frame(body, padding=(8, 0, 0, 0))
        body.add(left, weight=1)
        body.add(right, weight=1)

        correction = ttk.LabelFrame(left, text="Human feedback correction pair", padding=10)
        correction.pack(fill=BOTH, expand=True)
        self._entry_row(correction, "Task", self.correction_task_var, 0)
        self._entry_row(correction, "Tags", self.correction_tags_var, 1)
        ttk.Label(correction, text="Input context").grid(row=2, column=0, sticky="nw", pady=4)
        self.correction_input = scrolledtext.ScrolledText(correction, height=5, wrap="word")
        self.correction_input.grid(row=2, column=1, sticky="nsew", pady=4, padx=(8, 0))
        ttk.Label(correction, text="Bad output").grid(row=3, column=0, sticky="nw", pady=4)
        self.correction_bad = scrolledtext.ScrolledText(correction, height=4, wrap="word")
        self.correction_bad.grid(row=3, column=1, sticky="nsew", pady=4, padx=(8, 0))
        ttk.Label(correction, text="Corrected output").grid(row=4, column=0, sticky="nw", pady=4)
        self.correction_good = scrolledtext.ScrolledText(correction, height=4, wrap="word")
        self.correction_good.grid(row=4, column=1, sticky="nsew", pady=4, padx=(8, 0))
        ttk.Label(correction, text="Rationale").grid(row=5, column=0, sticky="nw", pady=4)
        self.correction_rationale = scrolledtext.ScrolledText(correction, height=4, wrap="word")
        self.correction_rationale.grid(row=5, column=1, sticky="nsew", pady=4, padx=(8, 0))
        ttk.Button(correction, text="Save Correction Pair", command=self._add_correction_pair).grid(
            row=6, column=1, sticky="e", pady=(8, 0)
        )
        correction.columnconfigure(1, weight=1)
        correction.rowconfigure(2, weight=1)
        correction.rowconfigure(3, weight=1)
        correction.rowconfigure(4, weight=1)
        correction.rowconfigure(5, weight=1)

        search = ttk.LabelFrame(right, text="Search persistent memory", padding=10)
        search.pack(fill=BOTH, expand=True)
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
        self.memory_results.pack(fill=BOTH, expand=True, pady=(10, 0))

    def _build_run_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Run")

        actions = ttk.Frame(tab)
        actions.pack(fill=X)
        ttk.Button(actions, text="Run Complete Draft + Audit", command=self._run_complete_review).pack(side=LEFT, padx=(0, 6))
        ttk.Button(actions, text="Audit Current Review", command=self._audit_current_review).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Export Controlled CSV", command=self._export_current_csv).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Hash Evidence", command=self._hash_evidence).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Release Manifest", command=self._release_manifest).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Export Agent Definitions", command=self._export_agent_definitions).pack(side=LEFT, padx=6)

        current = ttk.Frame(tab)
        current.pack(fill=X, pady=(10, 0))
        ttk.Label(current, text="Current review artifact").pack(side=LEFT)
        ttk.Entry(current, textvariable=self.review_path_var).pack(side=LEFT, fill=X, expand=True, padx=8)
        ttk.Button(current, text="Select", command=self._choose_review_path).pack(side=LEFT)
        ttk.Button(current, text="Load Results", command=self._load_results_from_path).pack(side=LEFT, padx=(6, 0))

        self.progress = ttk.Progressbar(tab, mode="indeterminate")
        self.progress.pack(fill=X, pady=(12, 8))
        self.run_log = scrolledtext.ScrolledText(tab, wrap="word", height=28)
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
            card = ttk.LabelFrame(metrics, text=label, padding=10)
            card.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
            ttk.Label(card, textvariable=var, style="Metric.TLabel").pack(anchor="w")

        panes = ttk.PanedWindow(tab, orient="vertical")
        panes.pack(fill=BOTH, expand=True, pady=(10, 0))

        action_frame = ttk.LabelFrame(panes, text="Required human actions", padding=8)
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

        findings_frame = ttk.LabelFrame(lower, text="Compliance findings", padding=8)
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

        decisions_frame = ttk.LabelFrame(lower, text="RVM decisions", padding=8)
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

        top = ttk.Frame(tab)
        top.pack(fill=X)
        ttk.Label(top, text="Output directory").pack(side=LEFT)
        ttk.Entry(top, textvariable=self.out_dir_var).pack(side=LEFT, fill=X, expand=True, padx=8)
        ttk.Button(top, text="Refresh", command=self._refresh_artifacts).pack(side=LEFT)

        panes = ttk.PanedWindow(tab, orient="horizontal")
        panes.pack(fill=BOTH, expand=True, pady=(10, 0))
        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
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
        self.artifact_preview.pack(fill=BOTH, expand=True)

    def _build_approvals_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Approvals")

        left = ttk.Frame(tab)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 8))
        right = ttk.LabelFrame(tab, text="Record approval state", padding=10)
        right.pack(side=RIGHT, fill=BOTH, expand=True, padx=(8, 0))

        self.approval_context = scrolledtext.ScrolledText(left, wrap="word")
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
        self.justification_text.grid(row=3, column=1, sticky="nsew", pady=4, padx=(8, 0))
        ttk.Button(right, text="Create Approval Artifact", command=self._record_approval).grid(
            row=4, column=1, sticky="e", pady=(8, 0)
        )
        right.columnconfigure(1, weight=1)
        right.rowconfigure(3, weight=1)

    def _build_guide_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Guide")
        guide = scrolledtext.ScrolledText(tab, wrap="word")
        guide.pack(fill=BOTH, expand=True)
        guide.insert(
            END,
            "\n".join(
                [
                    "LearningAgent UI workflow",
                    "",
                    "1. Inputs: add standards, DOORS/ReqIF or Excel exports, project context, evidence files, and a known-good RVM when training or benchmarking.",
                    "2. Training & Memory: index reference documents, crystallize known-good RVMs, capture human correction pairs, and create reviewed change proposals.",
                    "3. Run: execute the draft RVM workflow, audit it deterministically, export controlled CSVs, hash evidence, and create release manifests.",
                    "4. Results: review confidence, compliance failures, not-applicable decisions, impact analysis, and the exact human actions required before sign-off.",
                    "5. Artifacts: inspect generated JSON, CSV, manifests, proposals, and approval records from the configured output directory.",
                    "6. Approvals: record drafted, reviewed, rejected, approved, or baselined state with an author, role, justification, timestamp, and RVM hash.",
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
        self.memory_paths_text.insert(END, json.dumps(inventory, indent=2))
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
        review_out = self._out_path("review.json")
        compliance_out = self._out_path("compliance_report.json")

        def worker() -> dict[str, Path]:
            if not standards:
                raise ValueError("Add at least one standard or requirements document.")
            if not projects:
                raise ValueError("Add at least one project context document.")
            result = review_rvm(standards, projects, changed_ids, engine=engine)
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
            return f"Indexed {len(ids)} reference chunk(s) into {paths.reference_store}"

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
            return f"Indexed {len(ids)} project chunk(s) into {memory.paths.working_store}"

        self._run_worker("Index project working memory", worker)

    def _add_correction_pair(self) -> None:
        workspace = self.workspace_var.get()
        memory_root = self.memory_root_var.get()
        embedder_name = self.embedder_var.get()
        model_path = self.model_path_var.get()
        tags = [item.strip() for item in self.correction_tags_var.get().split(",") if item.strip()]
        pair = CorrectionPair(
            task=self.correction_task_var.get().strip() or "rvm_decision",
            input_text=self._text(self.correction_input),
            bad_output=self._text(self.correction_bad),
            corrected_output=self._text(self.correction_good),
            rationale=self._text(self.correction_rationale),
            tags=tags,
        )

        def worker() -> str:
            paths = default_memory_paths(workspace, memory_root)
            memory = CorrectionMemory(paths.crystallized_store, self._build_embedder(embedder_name, model_path))
            ids = memory.add_pairs([pair])
            return f"Saved correction pair {', '.join(ids)} into {paths.crystallized_store}"

        self._run_worker("Save correction pair", worker)

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

        def worker() -> str:
            if not review_path.exists():
                raise FileNotFoundError(f"Review artifact not found: {review_path}")
            if not author or not role or not justification:
                raise ValueError("Author ID, role, and justification are required for approval records.")
            create_approval_record(review_path, state, author, role, justification, out)
            return f"Wrote approval record to {out.resolve()}"

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
