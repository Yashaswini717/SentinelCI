# SentinelCI Implementation Status

This file tracks the phase-by-phase plan and what is implemented in this repository today.

## Roadmap (Planned Pipeline)

`Repository Parser -> Dependency Graph -> Pull Request Analyzer -> Change Impact Analysis -> Semantic Impact Analysis -> Test Selection Engine -> Test Generation Agent -> Risk Scoring System -> CI/CD Integration`

## Current Implementation Snapshot

Implemented (present in code and wired in `main.py`):

- Phase 1 - Repository Parser
- Phase 2 - Dependency Graph
- Phase 3 - Pull Request Analyzer
- Phase 4 - Change Impact Analysis (blast radius report)
- Phase 5 - Semantic Impact Analysis (embeddings + similarity search)
- Phase 6 - Test Selection Engine (basic implementation)
- Phase 7 - Test Generation Agent (coverage-gap driven, basic)

Not implemented yet:

- Phase 8 - Risk Scoring System
- Phase 9 - CI/CD Integration

Runtime folders and generation:

- `storage/` and `datasets/` are runtime-generated when you run `python main.py`
- analysis artifacts are intentionally gitignored via `.gitignore`
- semantic index artifacts under `storage/semantic_index/` are ignored and should remain local

## Phase 1 - Repository Parser

What it does:

- downloads Python files into `datasets/virtual_repo` (from the configured GitHub repo)
- scans the virtual repo for Python modules and test files
- extracts module-level symbols:
  - functions
  - classes
  - methods (as `Class.method`)
- produces indices for later phases (function index, class index) and a test-to-module mapping

Main implementation:

- `repository_analysis/repository_parser.py`

Generated outputs:

- `storage/repo_structure.json`
- `storage/function_index.json`
- `storage/class_index.json`
- `storage/test_mapping.json`

Key output fields:

- `modules[]`: `{name, path, functions[], classes[], methods[]}`
- `tests[]`: `{name, path, imports[]}` (imports are used for mapping)
- `file_map`: module key -> relative .py path
- `test_file_map`: test module key -> relative .py path

## Phase 2 - Dependency Graph

What it does:

- builds a module dependency graph using AST-based import extraction
- supports relative imports and attempts to resolve imports to known modules
- computes dependency metrics for later scoring:
  - `fan_in`
  - `fan_out`
  - `module_depth`
- generates a DOT visualization for debugging

Main implementation:

- `repository_analysis/dependency_graph.py`

Generated outputs:

- `storage/dependency_graph.json`
- `storage/dependency_metrics.json`
- `storage/dependency_graph.dot`
- optional: `storage/dependency_graph.png` (requires Graphviz)

Key output fields:

- dependency graph: `module -> [dependencies...]`
- metrics: `module -> {fan_in, fan_out, module_depth}`

## Phase 3 - Pull Request Analyzer

What it does:

- calls GitHub PR files API
- collects changed file paths
- maps changed files to internal module keys using `storage/repo_structure.json`
- parses patch hunks to detect:
  - changed functions (Python `def` / `async def` definitions when present in patch)
  - changed classes (Python `class` definitions when present in patch)
  - modified symbols (best-effort based on hunk context and edits)
- records change metrics:
  - files changed
  - lines added/deleted

Main implementation:

- `pr_analysis/pr_fetcher.py`
- `pr_analysis/diff_parser.py`
- `pr_analysis/pr_analyzer.py`

Generated outputs:

- `storage/pr_analysis.json`

Key output fields:

- `changed_files[]`
- `changed_modules[]`
- `changed_functions[]`
- `changed_classes[]`
- `modified_symbols[]`
- `change_metrics`: `{files_changed, lines_added, lines_deleted, patch_lines_added, patch_lines_deleted}`

## Phase 4 - Change Impact Analysis (Blast Radius)

What it does (current implementation):

- loads:
  - dependency graph + metrics (Phase 2)
  - PR change summary (Phase 3)
  - repository structure + indexes + test mapping (Phase 1)
- computes impacted modules using reverse graph traversal (who depends on changed modules)
- assigns depth (direct = depth 1, indirect = depth > 1)
- computes a confidence score (heuristic)
- classifies change type (currently heuristic): `signature_change` vs `body_change`
- flags whether public API likely changed (non-underscore symbol heuristic)
- computes blast radius class: `none/low/medium/high/critical`
- selects impacted tests using `storage/test_mapping.json`

Main implementation:

- `agents/change_impact_agent.py`

Generated outputs:

- `storage/impact_analysis.json`

Key output fields:

- `changed_modules[]`
- `impact_summary`: `{total_affected, direct_impact, indirect_impact, blast_radius, public_api_changed, change_type}`
- `affected_modules[]`: entries with `{module, impact_type, depth, confidence, reason, path, changed_by, fan_in, fan_out}`
- `impacted_tests[]`
- `symbol_impact` (present, but currently basic and not a full symbol dependency analysis)

What is still left for a fully production-ready Phase 4 blast radius:

- include explicit `changed_symbols` in the output (not only modules)
- add numeric scoring (ex: `blast_radius_score`) in addition to the label
- store per-module dependency paths as structured data (already present as `path`, but expand for multiple shortest paths)
- strengthen change type detection using AST signature diff (not underscore heuristics)
- strengthen symbol-level impact by analyzing actual symbol references (not name-only matching)
- attach confidence explanations and evidence per impacted module
- output coverage gaps: impacted modules with no mapped tests
- support stable behavior for multi-change scenarios (ranking, deduping, primary cause selection)
- add unit tests for traversal/path/confidence and edge cases (cycles, missing modules)

## Phase 5 - Semantic Impact Analysis

What it does (current implementation):

- chunks code into embeddable units:
  - modules
  - functions
  - classes
- generates embeddings for chunks using OpenRouter embeddings API
- stores embeddings in a persistent ChromaDB index
- queries the index for semantic similarity to changed symbols from Phase 3
- outputs ranked semantic matches
- failure-tolerant orchestration in `main.py`: if semantic runtime deps are missing or broken, run continues and later phases still execute

Main implementation:

- `semantic_analysis/code_chunker.py`
- `semantic_analysis/code_embedder.py`
- `semantic_analysis/similarity_engine.py`
- `semantic_analysis/semantic_impact_agent.py`

Generated outputs:

- `storage/semantic_impact.json`
- `storage/semantic_index/` (ChromaDB persistent index)

Runtime requirements:

- `OPENROUTER_API_KEY` must be set in the environment (or via `.env`)
- `chromadb` must be installed for the index/search

Operational notes:

- known chromadb runtime/index issues are handled with guarded initialization and clear recovery guidance
- recommended recovery when semantic index fails: delete `storage/semantic_index/` and rerun

Key output fields:

- `changed_symbols[]`
- `semantic_related_modules[]`: entries with `{module, score, reason, match_type, matched_symbol, path, changed_symbol}`
- `total_semantic_matches`

What is still left for a fully production-ready Phase 5:

- support method-level chunking
- improve chunk extraction using AST ranges instead of simple indentation parsing
- caching and incremental reindexing by file hash
- stronger filtering to avoid trivial self-matches and near-duplicates
- merge semantic impact with Phase 4 static impact into a unified impact report

## Phases 6-9 (Planned)

## Phase 6 - Test Selection Engine

What it does (current implementation):

- loads static impact (`storage/impact_analysis.json`), semantic impact (`storage/semantic_impact.json` if available), test mapping, and dependency metrics
- inverts test mapping into module -> tests lookup
- computes risk-weighted priority for candidate tests
- prioritizes:
  - static impacted modules first
  - semantic modules second
  - fallback-all-tests when no candidates are found
- emits coverage gaps for affected/changed modules without mapped tests

Main implementation:

- `agents/test_selection_agent.py`

Generated outputs:

- `storage/test_selection.json`

Key output fields:

- `tests_to_run[]`
- `selection_summary`
- `coverage_gaps[]`
- `test_details`

What is still left for a fully production-ready Phase 6:

- deterministic test ordering with stable tie-breaking across environments
- richer reasons with per-test evidence paths from Phase 4 and Phase 5
- better semantic candidate weighting from similarity scores (currently fixed-weight contribution)
- tighter integration with CI runtime constraints (sharding, timeout-aware selection)
- validation suite for selection quality and regression checks

## Phase 7 - Test Generation Agent

What it does (current implementation):

- reads `storage/test_selection.json`
- takes `coverage_gaps[]` as generation targets
- attempts to read module source from `datasets/virtual_repo`
- generates tests using OpenRouter chat completion when API key is present
- falls back to deterministic pytest templates when API is unavailable:
  - targeted fallback for `requests.api` with monkeypatched behavioral tests
  - structural fallback for other modules using parsed public function names
- writes generated files to `generated_tests/`
- emits run summary to `storage/test_generation.json`

Main implementation:

- `agents/test_generation_agent.py`

Generated outputs:

- `storage/test_generation.json`
- `generated_tests/*.py`

Key output fields:

- `generated_tests[]` with `{target, test_type, reason, path}`
- `generation_summary` with `{created, validated, failed}`

What is still left for a fully production-ready Phase 7:

- schema and syntax validation of generated tests before marking as validated
- execution validation by running generated tests in isolation
- duplicate test detection and de-duplication
- richer prompts per symbol/function instead of module-only generation targets
- integration with Phase 6 priorities and Phase 4 impact confidence
- optional PR-comment/report formatting for generated tests
- richer assertion synthesis from AST and type hints (currently template-based)

## Phase 8 - Risk Scoring System

- compute a risk score and explain main drivers; consume change metrics + blast radius + coverage

## Phase 9 - CI/CD Integration

- GitHub Actions integration; publish artifacts/reports; gate CI based on risk and coverage

## Orchestration

Entry point:

- `main.py` runs Phases 1 through 7 sequentially and writes outputs to `storage/`
- runtime config can be supplied via environment variables:
  - `GITHUB_URL`
  - `PR_OWNER`
  - `PR_REPO`
  - `PR_NUMBER`
  - `SEMANTIC_SIMILARITY_THRESHOLD`
  - `SEMANTIC_TOP_K`

Cleanup behavior:

- `datasets/virtual_repo` is removed at the end of `main.py`
