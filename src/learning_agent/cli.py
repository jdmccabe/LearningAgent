from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from learning_agent.core.documents import write_json
from learning_agent.core.embeddings import HashingEmbedder, OllamaEmbedder
from learning_agent.core.memory import CorrectionMemory, CorrectionPair, ReferenceMemory
from learning_agent.tasks.rvm.evaluation import evaluate_rvm
from learning_agent.tasks.rvm.improvement import suggest_rvm_improvements
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

    improve = subcommands.add_parser(
        "suggest-rvm-improvements",
        help="Suggest offline policy improvements from gold-vs-prediction failures.",
    )
    improve.add_argument("--gold", required=True, help="Known-good RVM CSV.")
    improve.add_argument("--pred", required=True, help="Prediction JSON from review-rvm.")
    improve.add_argument("--standards", nargs="+", required=True, help="Requirement files used for prediction.")
    improve.add_argument("--project", nargs="+", required=True, help="Project context files used for prediction.")
    improve.add_argument("--out", required=True, help="Output JSON improvement plan.")

    index_ref = subcommands.add_parser("index-reference", help="Index reference documents into a JSONL vector store.")
    index_ref.add_argument("--docs", nargs="+", required=True, help="Reference documents to index.")
    index_ref.add_argument("--store", required=True, help="Vector store JSONL path.")
    _add_embedding_args(index_ref)

    search_ref = subcommands.add_parser("search-reference", help="Search indexed reference documents.")
    search_ref.add_argument("--query", required=True)
    search_ref.add_argument("--store", required=True)
    search_ref.add_argument("--top-k", type=int, default=5)
    _add_embedding_args(search_ref)

    add_correction = subcommands.add_parser("add-correction", help="Add an error-correction pair.")
    add_correction.add_argument("--store", required=True)
    add_correction.add_argument("--task", required=True)
    add_correction.add_argument("--input", required=True)
    add_correction.add_argument("--bad-output", required=True)
    add_correction.add_argument("--corrected-output", required=True)
    add_correction.add_argument("--rationale", default="")
    add_correction.add_argument("--tag", action="append", default=[])
    _add_embedding_args(add_correction)

    search_correction = subcommands.add_parser("search-corrections", help="Search stored correction pairs.")
    search_correction.add_argument("--query", required=True)
    search_correction.add_argument("--store", required=True)
    search_correction.add_argument("--top-k", type=int, default=5)
    _add_embedding_args(search_correction)

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
    if args.command == "suggest-rvm-improvements":
        plan = suggest_rvm_improvements(args.gold, args.pred, args.standards, args.project)
        write_json(args.out, plan.to_dict())
        print(f"Wrote improvement plan to {Path(args.out).resolve()}")
        return
    if args.command == "index-reference":
        memory = ReferenceMemory(args.store, _build_embedder(args))
        ids = memory.index_files(args.docs)
        print(f"Indexed {len(ids)} reference chunk(s) into {Path(args.store).resolve()}")
        return
    if args.command == "search-reference":
        memory = ReferenceMemory(args.store, _build_embedder(args))
        _print_results([item.to_dict(include_embedding=False) for item in memory.search(args.query, args.top_k)])
        return
    if args.command == "add-correction":
        memory = CorrectionMemory(args.store, _build_embedder(args))
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
        print(f"Added {len(ids)} correction pair(s) into {Path(args.store).resolve()}")
        return
    if args.command == "search-corrections":
        memory = CorrectionMemory(args.store, _build_embedder(args))
        _print_results([item.to_dict(include_embedding=False) for item in memory.search(args.query, args.top_k)])
        return

def _add_embedding_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--embedder", choices=["hashing", "ollama"], default="hashing")
    parser.add_argument("--ollama-host", help="Local Ollama service URL.")
    parser.add_argument("--ollama-model", default="embeddinggemma")


def _build_embedder(args: argparse.Namespace):
    if args.embedder == "ollama":
        return OllamaEmbedder(model=args.ollama_model, host=args.ollama_host)
    return HashingEmbedder()


def _print_results(results: list[dict]) -> None:
    import json

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
