# Demo RVM Input Package

This package is a realistic, fully fake Requirements Verification Matrix (RVM) demo for the offline LearningAgent workflow.

The reference standards listed here are represented by metadata and paraphrased demo requirements only. Several source standards are public NASA documents, while others are commercial, controlled, or distribution-limited specifications. This fixture intentionally does not reproduce source-standard text.

## Files

- `standards_requirements.csv`: decomposed demo requirements mapped to commonly referenced aerospace standards.
- `project_documents/*.md`: fake program inputs that an RVM reviewer would normally receive.
- `project_documents/waiver_register.csv`: fake waivers and tailoring dispositions.
- `project_documents/evidence_manifest.csv`: fake verification artifacts and hashes.
- `reference_specs/spec_catalog.csv`: fake reference specification inventory with access/source notes.
- `reference_specs/demo_spec_abstracts.md`: short, paraphrased context summaries for retrieval tests.
- `gold_rvm.csv`: expected applicability and method decisions for evaluation.
- `gold_rvm_complete.csv`: fuller controlled-RVM style output with traces, procedures, artifacts, criteria, DAL, and change rationale.

## Example Commands

```powershell
python -m learning_agent.cli review-rvm `
  --standards examples/demo_rvm/standards_requirements.csv `
  --project examples/demo_rvm/project_documents/mission_profile.md `
  --project examples/demo_rvm/project_documents/system_architecture.md `
  --project examples/demo_rvm/project_documents/electrical_design.md `
  --project examples/demo_rvm/project_documents/pressure_system_design.md `
  --project examples/demo_rvm/project_documents/materials_processes_plan.md `
  --project examples/demo_rvm/project_documents/verification_plan.md `
  --project examples/demo_rvm/project_documents/hazard_report.md `
  --project examples/demo_rvm/project_documents/waiver_register.csv `
  --workspace . `
  --out out/demo_rvm_review.json

python -m learning_agent.cli evaluate-rvm `
  --gold examples/demo_rvm/gold_rvm.csv `
  --pred out/demo_rvm_review.json
```

