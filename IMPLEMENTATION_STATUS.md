# SentinelCI Implementation Status

This file documents what is currently implemented in the project so it can be used as a reference for future phases.

## Current Status

Officially implemented phases:

- Phase 1 - Repository Parser
- Phase 2 - Dependency Graph
- Phase 3 - Pull Request Analyzer

Important note about Phase 4:

- Phase 4 has not been officially started as a full project phase.
- A basic graph traversal result generator exists because traversal logic was already present in the codebase and was restored to generate `storage/traversal_results.json` for reference.
- Treat this as preliminary support code, not as a completed Phase 4 implementation.

## Implemented Pipeline So Far

Current implemented flow:

`Repository Parser -> Dependency Graph -> Pull Request Analyzer`

Reference-only support currently available:

`Pull Request Analyzer -> basic graph traversal output`

## Phase 1 - Repository Parser

Purpose:

- Scan the downloaded repository
- Identify Python modules and test files
- Extract functions, classes, and methods
- Build mapping data for later phases

Main implementation:

- `repository_analysis/repository_parser.py`

Generated outputs:

- `storage/repo_structure.json`
- `storage/function_index.json`
- `storage/class_index.json`
- `storage/test_mapping.json`

Expected contents:

- `modules`
- `tests`
- `file_map`
- `test_file_map`
- function index entries
- class index entries
- test-to-module mapping

Example output shape:

```json
{
  "modules": [
    {
      "name": "package/module",
      "path": "package/module.py",
      "functions": ["func_a"],
      "classes": ["MyClass"],
      "methods": ["MyClass.run"]
    }
  ],
  "tests": [
    {
      "name": "tests/test_module",
      "path": "tests/test_module.py",
      "functions": [],
      "classes": [],
      "methods": [],
      "imports": ["package.module"]
    }
  ],
  "file_map": {
    "package/module": "package/module.py"
  },
  "test_file_map": {
    "tests/test_module": "tests/test_module.py"
  }
}
```

## Phase 2 - Dependency Graph

Purpose:

- Analyze imports between modules
- Build dependency relationships
- Compute graph metrics for later risk and impact analysis

Main implementation:

- `repository_analysis/dependency_graph.py`

Generated outputs:

- `storage/dependency_graph.json`
- `storage/dependency_metrics.json`
- `storage/dependency_graph.dot`
- optional: `storage/dependency_graph.png`

Expected contents:

- module-to-module dependency graph
- `fan_in`
- `fan_out`
- `module_depth`
- DOT graph visualization

Example output shape:

```json
{
  "package/module_a": ["package/module_b"],
  "package/module_b": []
}
```

```json
{
  "package/module_a": {
    "fan_in": 2,
    "fan_out": 1,
    "module_depth": 3
  }
}
```

## Phase 3 - Pull Request Analyzer

Purpose:

- Connect to the GitHub API
- Fetch pull request file changes
- Detect changed files and changed modules
- Detect changed functions, classes, and modified symbols
- Store basic change metrics

Main implementation:

- `pr_analysis/pr_fetcher.py`
- `pr_analysis/diff_parser.py`
- `pr_analysis/pr_analyzer.py`

Generated outputs:

- `storage/pr_analysis.json`

Expected contents:

- `changed_files`
- `changed_modules`
- `changed_functions`
- `changed_classes`
- `modified_symbols`
- `change_metrics`

Example output shape:

```json
{
  "changed_files": ["package/module_a.py"],
  "changed_modules": ["package/module_a"],
  "changed_functions": ["process_data"],
  "changed_classes": ["Processor"],
  "modified_symbols": ["process_data", "Processor"],
  "change_metrics": {
    "files_changed": 1,
    "lines_added": 10,
    "lines_deleted": 6,
    "patch_lines_added": 10,
    "patch_lines_deleted": 6
  }
}
```

## Preliminary Traversal Support

This is available in code, but should not yet be treated as an officially started or completed Phase 4.

What exists:

- reverse graph traversal to find affected modules
- output written to `storage/traversal_results.json`

Implementation:

- `repository_analysis/dependency_graph.py`

Reference output shape:

```json
{
  "changed_modules": ["package/module_a"],
  "affected_modules": ["package/service_x"],
  "total_affected": 1,
  "traversal_by_module": {
    "package/module_a": ["package/service_x"]
  }
}
```
## Phase 4 - Change Impact Analysis

Purpose:
- Separate direct from indirect impact
- Include dependency paths explaining why a module is impacted
- Include impact depth for each affected module
- Compute weighted blast radius
- Connect impacted modules to impacted tests
- Confidence scoring for each impacted result
- Classify impact by change type (signature vs body change)
- Public API vs private symbol detection

Main implementation:
- `agents/change_impact_agent.py`

Generated outputs:
- `storage/impact_analysis.json`

Expected contents:
- `changed_modules`
- `impact_summary` with blast_radius, direct_impact, indirect_impact
- `affected_modules` with depth, confidence, reason, path
- `impacted_tests`
- `symbol_impact`

Example output shape:
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
      "change_type": "signature_change",
      "reason": "imports src/requests/adapters",
      "path": ["src/requests/adapters", "src/requests/sessions"],
      "changed_by": ["src/requests/adapters"],
      "fan_in": 1,
      "fan_out": 11
    }
  ],
  "impacted_tests": [],
  "symbol_impact": {}
}
```
Analysis

Purpose:
- Generate embeddings for repository code artifacts
- Store embeddings in ChromaDB vector database
- Find semantically related code not captured by static imports alone
- Identify hidden relationships between changed code and rest of codebase
- Return ranked semantic impact results to merge with Phase 4 static results

Main implementation:
- `semantic_analysis/code_chunker.py`
- `semantic_analysis/code_embedder.py`
- `semantic_analysis/similarity_engine.py`
- `semantic_analysis/semantic_impact_agent.py`

Generated outputs:
- `storage/semantic_impact.json`
- `storage/semantic_index/` (ChromaDB persistent index)

Embedding model:
- `openai/text-embedding-3-small` via OpenRouter API

Chunking strategy:
- Module level: one chunk per .py file
- Class level: one chunk per class definition
- Function level: one chunk per function definition
- Total chunks for requests library: 132

Expected output shape:
```json
{
  "changed_symbols": [
    "src/requests/adapters::get_connection_with_tls_context",
    "src/requests/adapters::__module__"
  ],
  "semantic_related_modules": [
    {
      "module": "src/requests/utils",
      "score": 0.6122,
      "reason": "semantically related module functionality to src/requests/adapters",
      "match_type": "module",
      "matched_symbol": "src/requests/utils",
      "path": "src/requests/utils.py",
      "changed_symbol": "src/requests/adapters::__module__"
    }
  ],
  "total_semantic_matches": 6
}
```

Configuration:
- `similarity_threshold`: 0.50 (tunable)
- `top_k`: 10 results per symbol search
- `force_reindex`: False by default (uses cached index)

Notes:
- ChromaDB index is persisted in storage/semantic_index/
- Second run skips embedding generation and uses cached index
- Function-level matches require larger codebases with duplicated patterns
- Module-level matching works well for well-structured libraries
- Threshold can be lowered for more matches or raised for stricter filtering

TODO (future enhancement):
- Add method-level chunking for finer granularity
- Add cross-repo semantic search
- Experiment with code-specific embedding models (CodeBERT, StarCoder)
- Merge semantic results with Phase 4 static blast radius into unified score
TODO (future enhancement):
- Replace underscore-only check with full AST signature comparison
- Fetch file before and after PR from GitHub API
- Compare function parameters using ast.parse()
- Detect: param added, param removed, return type changed
Status:

- useful as a reference/helper
- not counted as a fully implemented project phase yet

## Summary For Future Reference


Completed project phases:
- Phase 1 - Repository Parser
- Phase 2 - Dependency Graph
- Phase 3 - Pull Request Analyzer
- Phase 4 - Change Impact Analysis
- Phase 5 - Semantic Impact Analysis

Not yet officially started/completed:
- Phase 6 - Test Selection Engine
- Phase 7 - Test Generation Agent
- Phase 8 - Risk Scoring System
- Phase 9 - CI/CD Integration
