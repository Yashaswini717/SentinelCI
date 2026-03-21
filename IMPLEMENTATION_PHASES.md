# SentinelCI Implementation Phases and Expected Outputs

This document is for handoff to the next teammate. It explains what is implemented now, what each phase produces, and what output to expect when running the pipeline.

## Current Pipeline in Code

`Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5 (optional) -> Phase 6 -> Phase 7`

Entry point: `main.py`

## Runtime Notes

- Run command: `python main.py`
- Runtime-generated folders:
  - `storage/`
  - `datasets/`
- `datasets/virtual_repo` is removed at the end of a run.
- Phase 5 requires optional dependencies:
  - `chromadb`
  - `OPENROUTER_API_KEY`
- If Phase 5 fails, pipeline continues and Phases 6-7 still run.

## Environment Variables

Use `.envexample` as reference.

- `GITHUB_URL`
- `PR_OWNER`
- `PR_REPO`
- `PR_NUMBER`
- `OPENROUTER_API_KEY` (needed for LLM embedding + LLM test generation)
- `SEMANTIC_SIMILARITY_THRESHOLD`
- `SEMANTIC_TOP_K`

## Phase-by-Phase Status

## Phase 1 - Repository Parser

Status: implemented

Main code:

- `repository_analysis/repository_parser.py`

Outputs:

- `storage/repo_structure.json`
- `storage/function_index.json`
- `storage/class_index.json`
- `storage/test_mapping.json`

Expected output fields:

```json
{
  "modules": [{"name": "src/requests/api", "path": "src/requests/api.py", "functions": [], "classes": [], "methods": []}],
  "tests": [{"name": "tests/test_requests", "path": "tests/test_requests.py", "imports": []}],
  "file_map": {"src/requests/api": "src/requests/api.py"},
  "test_file_map": {"tests/test_requests": "tests/test_requests.py"}
}
```

## Phase 2 - Dependency Graph

Status: implemented

Main code:

- `repository_analysis/dependency_graph.py`

Outputs:

- `storage/dependency_graph.json`
- `storage/dependency_metrics.json`
- `storage/dependency_graph.dot`
- optional: `storage/dependency_graph.png`

Expected output fields:

```json
{
  "src/requests/api": ["src/requests/sessions"],
  "src/requests/sessions": ["src/requests/adapters"]
}
```

```json
{
  "src/requests/api": {"fan_in": 1, "fan_out": 1, "module_depth": 2}
}
```

## Phase 3 - Pull Request Analyzer

Status: implemented

Main code:

- `pr_analysis/pr_fetcher.py`
- `pr_analysis/diff_parser.py`
- `pr_analysis/pr_analyzer.py`

Output:

- `storage/pr_analysis.json`

Expected output fields:

```json
{
  "changed_files": ["src/requests/adapters.py"],
  "changed_modules": ["src/requests/adapters"],
  "changed_functions": ["_get_connection", "get_connection_with_tls_context"],
  "changed_classes": [],
  "modified_symbols": ["_get_connection", "get_connection_with_tls_context", "send"],
  "change_metrics": {
    "files_changed": 1,
    "lines_added": 31,
    "lines_deleted": 6,
    "patch_lines_added": 31,
    "patch_lines_deleted": 6
  }
}
```

## Phase 4 - Change Impact Analysis

Status: implemented (advanced static blast radius)

Main code:

- `agents/change_impact_agent.py`

Output:

- `storage/impact_analysis.json`

Expected output fields:

```json
{
  "changed_modules": ["src/requests/adapters"],
  "impact_summary": {
    "total_affected": 2,
    "direct_impact": 1,
    "indirect_impact": 1,
    "blast_radius": "medium",
    "public_api_changed": true,
    "change_type": "signature_change"
  },
  "affected_modules": [
    {
      "module": "src/requests/sessions",
      "impact_type": "direct",
      "depth": 1,
      "confidence": 1.0,
      "reason": "imports src/requests/adapters",
      "path": ["src/requests/adapters", "src/requests/sessions"],
      "changed_by": ["src/requests/adapters"],
      "fan_in": 1,
      "fan_out": 11
    }
  ],
  "impacted_tests": ["tests/test_adapters.py", "tests/test_requests.py"],
  "symbol_impact": {}
}
```

## Phase 5 - Semantic Impact Analysis

Status: implemented but dependency-gated

Main code:

- `semantic_analysis/code_chunker.py`
- `semantic_analysis/code_embedder.py`
- `semantic_analysis/similarity_engine.py`
- `semantic_analysis/semantic_impact_agent.py`

Outputs:

- `storage/semantic_impact.json`
- `storage/semantic_index/` (local index)

Expected output fields:

```json
{
  "changed_symbols": ["src/requests/adapters::get_connection_with_tls_context"],
  "semantic_related_modules": [
    {
      "module": "src/requests/sessions",
      "score": 0.82,
      "reason": "similar module functionality",
      "match_type": "module",
      "matched_symbol": "src/requests/sessions",
      "path": "src/requests/sessions.py",
      "changed_symbol": "src/requests/adapters::__module__"
    }
  ],
  "total_semantic_matches": 1
}
```

If dependency/key is missing, expected console behavior is:

- Phase 5 skipped with clear reason
- pipeline continues

## Phase 6 - Test Selection Engine

Status: implemented (basic-to-intermediate)

Main code:

- `agents/test_selection_agent.py`

Output:

- `storage/test_selection.json`

Expected output fields:

```json
{
  "tests_to_run": [
    "tests/test_requests.py",
    "tests/test_lowlevel.py"
  ],
  "selection_summary": {
    "total_tests": 4,
    "static_tests": 1,
    "semantic_tests": 3,
    "fallback_tests": 0
  },
  "coverage_gaps": ["src/requests/api"],
  "test_details": {
    "tests/test_requests.py": {
      "priority": 1,
      "score": 5.0,
      "reasons": ["static:src/requests/sessions"]
    }
  }
}
```

## Phase 7 - Test Generation Agent

Status: implemented (basic, with useful fallback templates)

Main code:

- `agents/test_generation_agent.py`

Outputs:

- `storage/test_generation.json`
- `generated_tests/*.py`

Expected output fields:

```json
{
  "generated_tests": [
    {
      "target": "requests.api",
      "test_type": "unit",
      "reason": "coverage_gap",
      "path": "generated_tests/test_requests_api.py"
    }
  ],
  "generation_summary": {
    "created": 1,
    "validated": 1,
    "failed": 0
  }
}
```

Example generated fallback for `requests.api` includes behavior checks with monkeypatch:

- request delegates to `sessions.request`
- wrapper methods (`get`, `post`) call `request` with expected arguments

## Not Implemented Yet

## Phase 8 - Risk Scoring System

Status: not implemented

Planned output:

```json
{
  "risk_score": 0,
  "risk_level": "low|medium|high",
  "drivers": []
}
```

## Phase 9 - CI/CD Integration

Status: not implemented

Planned output:

- GitHub Actions workflow and CI report artifacts

## Phase 10 - Evaluation and Experiments

Status: not implemented

Planned output:

- benchmarks for test reduction, runtime, and failure-detection quality

## Expected Console Checkpoints

During a successful run, you should see:

- `PHASE 1: Repository Parser`
- `PHASE 2: Dependency Graph`
- `PHASE 3: Pull Request Analyzer`
- `PHASE 4: Change Impact Analysis`
- `PHASE 5: Semantic Impact Analysis` (or clear skip message)
- `PHASE 6: Test Selection Engine`
- `PHASE 7: Test Generation Agent`
- final `RUN COMPLETE`
