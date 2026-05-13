from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

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
from learning_agent.tasks.rvm.compliance import audit_compliance_from_file
from learning_agent.tasks.rvm.evaluation import evaluate_rvm
from learning_agent.tasks.rvm.improvement import suggest_rvm_improvements
from learning_agent.tasks.rvm.parsing import parse_good_rvm, parse_requirements
from learning_agent.tasks.rvm.workflow import review_rvm


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="learning-agent")
    subcommands = parser.add_subparsers(dest="command", required=True)

    demo = subcommands.add_parser("demo", help="Run the offline RVM demo.")
    demo.add_argument("--out", default="out/demo_review.json")

    review = subcommands.add_parser("review-rvm", help="Review requirements against project context.")
    review.add_argument("--standards", nargs="+", required=True, help="Requirement CSV/TXT/MD/JSON files.")
    review.add_argument("--project", nargs="+", required=True, help="Project context files.")
    review.add_argument("--changed", nargs="*", default=[], help="Changed requirement IDs for impact analysis.")
    review.add_argument("--out", required=True, help="Output JSON file.")
    review.add_argument("--engine", choices=["default", "langgraph"], default="default")

    evaluate = subcommands.add_parser("evaluate-rvm", help="Evaluate predictions against a good RVM CSV.")
    evaluate.add_argument("--gold", required=True, help="Known-good RVM CSV.")
    evaluate.add_argument("--pred", required=True, help="Prediction JSON from review-rvm.")
    evaluate.add_argument("--out", help="Optional output JSON report.")

    audit_compliance = subcommands.add_parser(
        "audit-rvm-compliance",
        help="Run deterministic aerospace compliance checks on an RVM review JSON.",
    )
    audit_compliance.add_argument("--rvm", required=True, help="Review JSON from review-rvm.")
    audit_compliance.add_argument("--out", help="Optional output JSON report.")

    improve = subcommands.add_parser(
        "suggest-rvm-improvements",
        help="Suggest offline policy improvements from gold-vs-prediction failures.",
    )
    improve.add_argument("--gold", required=True, help="Known-good RVM CSV.")
    improve.add_argument("--pred", required=True, help="Prediction JSON from review-rvm.")
    improve.add_argument("--standards", nargs="+", required=True, help="Requirement files used for prediction.")
    improve.add_argument("--project", nargs="+", required=True, help="Project context files used for prediction.")
    improve.add_argument("--out", required=True, help="Output JSON improvement plan.")

    learn_good = subcommands.add_parser(
        "learn-good-rvm",
        help="Crystallize known-good RVM rows into persistent learned memory.",
    )
    learn_good.add_argument("--gold", required=True, help="Known-good RVM CSV/TSV/XLSX file.")
    learn_good.add_argument("--standards", nargs="+", required=True, help="Requirement files used by the good RVM.")
    learn_good.add_argument("--memory-root", help="Persistent memory root. Defaults to .learning_agent.")
    _add_embedding_args(learn_good)

    index_ref = subcommands.add_parser("index-reference", help="Index reference documents into a JSONL vector store.")
    index_ref.add_argument("--docs", nargs="+", required=True, help="Reference documents to index.")
    index_ref.add_argument("--store", help="Vector store JSONL path.")
    index_ref.add_argument("--memory-root", help="Persistent memory root. Defaults to .learning_agent.")
    _add_embedding_args(index_ref)

    search_ref = subcommands.add_parser("search-reference", help="Search indexed reference documents.")
    search_ref.add_argument("--query", required=True)
    search_ref.add_argument("--store", help="Vector store JSONL path.")
    search_ref.add_argument("--memory-root", help="Persistent memory root. Defaults to .learning_agent.")
    search_ref.add_argument("--top-k", type=int, default=5)
    _add_embedding_args(search_ref)

    add_correction = subcommands.add_parser("add-correction", help="Add an error-correction pair.")
    add_correction.add_argument("--store", help="Vector store JSONL path.")
    add_correction.add_argument("--memory-root", help="Persistent memory root. Defaults to .learning_agent.")
    add_correction.add_argument("--task", required=True)
    add_correction.add_argument("--input", required=True)
    add_correction.add_argument("--bad-output", required=True)
    add_correction.add_argument("--corrected-output", required=True)
    add_correction.add_argument("--rationale", default="")
    add_correction.add_argument("--tag", action="append", default=[])
    _add_embedding_args(add_correction)

    search_correction = subcommands.add_parser("search-corrections", help="Search stored correction pairs.")
    search_correction.add_argument("--query", required=True)
    search_correction.add_argument("--store", help="Vector store JSONL path.")
    search_correction.add_argument("--memory-root", help="Persistent memory root. Defaults to .learning_agent.")
    search_correction.add_argument("--top-k", type=int, default=5)
    _add_embedding_args(search_correction)

    index_project = subcommands.add_parser("index-project", help="Index project details into workspace-scoped working memory.")
    index_project.add_argument("--docs", nargs="+", required=True, help="Project documents to index.")
    index_project.add_argument("--workspace", default=".", help="Workspace path for memory isolation.")
    index_project.add_argument("--memory-root", help="Persistent memory root. Defaults to .learning_agent.")
    _add_embedding_args(index_project)

    search_project = subcommands.add_parser("search-project", help="Search workspace-scoped project working memory.")
    search_project.add_argument("--query", required=True)
    search_project.add_argument("--workspace", default=".", help="Workspace path for memory isolation.")
    search_project.add_argument("--memory-root", help="Persistent memory root. Defaults to .learning_agent.")
    search_project.add_argument("--top-k", type=int, default=5)
    _add_embedding_args(search_project)

    memory_paths = subcommands.add_parser("memory-paths", help="Show persistent memory paths for this workspace.")
    memory_paths.add_argument("--workspace", default=".")
    memory_paths.add_argument("--memory-root")

    agent_defs = subcommands.add_parser("agent-definitions", help="Print the versioned RVM worker agent definitions.")
    agent_defs.add_argument("--out", help="Optional JSON output path.")

    args = parser.parse_args(argv)
    if args.command == "demo":
        result = review_rvm(
            standard_paths=["examples/standards.csv"],
            project_paths=["examples/project.txt"],
            changed_requirement_ids=["STD-001"],
        )
        write_json(args.out, result["result"])
        print(f"Wrote demo review to {Path(args.out).resolve()}")
        return
    if args.command == "review-rvm":
        result = review_rvm(args.standards, args.project, args.changed, engine=args.engine)
        write_json(args.out, result["result"])
        print(f"Wrote review to {Path(args.out).resolve()}")
        return
    if args.command == "evaluate-rvm":
        report = evaluate_rvm(args.gold, args.pred)
        if args.out:
            write_json(args.out, report.to_dict())
            print(f"Wrote evaluation report to {Path(args.out).resolve()}")
        else:
            import json

            print(json.dumps(report.to_dict(), indent=2))
        return
    if args.command == "audit-rvm-compliance":
        report = audit_compliance_from_file(args.rvm)
        if args.out:
            write_json(args.out, report.to_dict())
            print(f"Wrote compliance report to {Path(args.out).resolve()}")
        else:
            import json

            print(json.dumps(report.to_dict(), indent=2))
        return
    if args.command == "suggest-rvm-improvements":
        plan = suggest_rvm_improvements(args.gold, args.pred, args.standards, args.project)
        write_json(args.out, plan.to_dict())
        print(f"Wrote improvement plan to {Path(args.out).resolve()}")
        return
    if args.command == "learn-good-rvm":
        paths = default_memory_paths(root=args.memory_root)
        memory = CorrectionMemory(paths.crystallized_store, _build_embedder(args))
        requirements = {
            req.id: req
            for standard in args.standards
            for req in parse_requirements(standard)
        }
        pairs = []
        for decision in parse_good_rvm(args.gold):
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
        print(f"Crystallized {len(ids)} good RVM example(s) into {paths.crystallized_store}")
        return
    if args.command == "index-reference":
        paths = default_memory_paths(root=args.memory_root)
        store = args.store or paths.reference_store
        memory = ReferenceMemory(store, _build_embedder(args))
        ids = memory.index_files(args.docs)
        print(f"Indexed {len(ids)} reference chunk(s) into {Path(store).resolve()}")
        return
    if args.command == "search-reference":
        paths = default_memory_paths(root=args.memory_root)
        memory = ReferenceMemory(args.store or paths.reference_store, _build_embedder(args))
        _print_results([item.to_dict(include_embedding=False) for item in memory.search(args.query, args.top_k)])
        return
    if args.command == "add-correction":
        paths = default_memory_paths(root=args.memory_root)
        store = args.store or paths.crystallized_store
        memory = CorrectionMemory(store, _build_embedder(args))
        ids = memory.add_pairs(
            [
                CorrectionPair(
                    task=args.task,
                    input_text=args.input,
                    bad_output=args.bad_output,
                    corrected_output=args.corrected_output,
                    rationale=args.rationale,
                    tags=args.tag,
                )
            ]
        )
        print(f"Added {len(ids)} correction pair(s) into {Path(store).resolve()}")
        return
    if args.command == "search-corrections":
        paths = default_memory_paths(root=args.memory_root)
        memory = CorrectionMemory(args.store or paths.crystallized_store, _build_embedder(args))
        _print_results([item.to_dict(include_embedding=False) for item in memory.search(args.query, args.top_k)])
        return
    if args.command == "index-project":
        memory = WorkspaceMemory(args.workspace, args.memory_root, _build_embedder(args))
        ids = memory.index_project_files(args.docs)
        print(f"Indexed {len(ids)} project chunk(s) into {memory.paths.working_store}")
        return
    if args.command == "search-project":
        memory = WorkspaceMemory(args.workspace, args.memory_root, _build_embedder(args))
        _print_results([item.to_dict(include_embedding=False) for item in memory.search(args.query, args.top_k)])
        return
    if args.command == "memory-paths":
        paths = default_memory_paths(args.workspace, args.memory_root)
        _print_results(
            [
                {
                    "root": str(paths.root),
                    "reference_store": str(paths.reference_store),
                    "crystallized_store": str(paths.crystallized_store),
                    "workspace_root": str(paths.workspace_root),
                    "working_store": str(paths.working_store),
                    "workspace_manifest": str(paths.workspace_manifest),
                }
            ]
        )
        return
    if args.command == "agent-definitions":
        definitions = agent_definitions_as_dict()
        if args.out:
            write_json(args.out, definitions)
            print(f"Wrote agent definitions to {Path(args.out).resolve()}")
        else:
            _print_results([definitions])
        return

def _add_embedding_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--embedder", choices=["hashing", "llama-cpp"], default="hashing")
    parser.add_argument("--model-path", default="models/ollama/embeddinggemma/embeddinggemma.gguf")


def _build_embedder(args: argparse.Namespace):
    if args.embedder == "llama-cpp":
        return LlamaCppEmbedder(model_path=args.model_path)
    return HashingEmbedder()


def _print_results(results: list[dict]) -> None:
    import json

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
