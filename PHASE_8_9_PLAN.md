# SentinelCI Phase 8 and 9 Implementation Plan

This document explains what needs to be implemented for Phase 8 (Risk Scoring System) and Phase 9 (CI/CD Integration), based on the current state of the project.

## Phase 8 - Risk Scoring System

## Objective

Convert analysis outputs from Phases 3-7 into a deterministic risk score with clear reasoning and CI action recommendations.

## Inputs

- `storage/pr_analysis.json`
- `storage/impact_analysis.json`
- `storage/semantic_impact.json` (optional)
- `storage/test_selection.json`
- `storage/test_generation.json`
- `storage/dependency_metrics.json`

## Core Components to Build

### 1. Risk Input Aggregator

Create a module that loads all available phase outputs and normalizes them into a single in-memory structure.

Requirements:

- tolerate missing optional files (especially semantic output)
- provide safe defaults
- validate expected keys

### 2. Scoring Engine

Compute a weighted score from multiple dimensions:

- change size:
  - files changed
  - lines added/deleted
- blast radius:
  - direct impact count
  - indirect impact count
  - affected depth
- dependency criticality:
  - fan_in
  - fan_out
  - module_depth
- API/change type sensitivity:
  - public API changed
  - signature vs body change
- test confidence:
  - number of selected tests
  - coverage gaps
  - generated tests count
- semantic impact (if available):
  - semantic matches count
  - average/top semantic score

### 3. Risk Classification Layer

Map score to a risk level:

- `0-30 -> low`
- `31-60 -> medium`
- `61-80 -> high`
- `81-100 -> critical`

### 4. Driver Explanation Layer

Generate top textual reasons explaining why the score is high/low.

Examples:

- "Public API function changed"
- "High fan-in dependency affected"
- "Coverage gap detected in impacted module"

### 5. Recommendation Layer

Map risk level to CI action:

- low -> run selected tests only
- medium -> selected + smoke/integration subset
- high -> selected + extended regression
- critical -> full regression + manual review signal

## Expected Output File

File: `storage/risk_report.json`

Example shape:

```json
{
  "risk_score": 74,
  "risk_level": "high",
  "drivers": [
    "Public API function changed",
    "2 impacted modules with transitive dependency depth",
    "Coverage gap detected"
  ],
  "components": {
    "change_size": 14,
    "blast_radius": 20,
    "dependency_criticality": 18,
    "coverage_confidence": 12,
    "semantic_impact": 10
  },
  "recommendation": {
    "action": "run_extended_pipeline",
    "required_suites": [
      "selected_tests",
      "integration",
      "regression_smoke"
    ]
  }
}
```

## Phase 8 Done Criteria

- deterministic score generation from current inputs
- robust handling of missing optional files
- clear drivers included in output
- unit tests for threshold and scoring logic
- stable output contract saved to `storage/risk_report.json`

---

## Phase 9 - CI/CD Integration

## Objective

Integrate SentinelCI analysis into pull request workflows so the CI system can choose tests and enforce risk-aware gating.

## Core Components to Build

### 1. GitHub Actions Workflow

Create workflow file under `.github/workflows/`.

Trigger:

- `pull_request`

Main steps:

- checkout
- setup python
- install dependencies
- run `python main.py`
- archive artifacts

### 2. CI Decision Executor

Read:

- `storage/risk_report.json`
- `storage/test_selection.json`

Use recommendation to choose test suites and commands.

### 3. Risk-Based Gating

Examples:

- low: selected tests only
- medium: selected + smoke/integration
- high: selected + broader regression
- critical: full regression and explicit failure conditions if key checks fail

### 4. PR Reporting

Post a CI summary comment with:

- changed modules
- blast radius
- tests selected
- generated tests
- risk score and level
- recommended action

### 5. Fallback and Safety Policy

- hard fail if core phases (1-4) fail
- allow optional phase degradation (phase 5) with warning
- if risk report is missing, fail-safe to broader test execution (not silent pass)

## Expected Output File

File: `storage/ci_decision.json`

Example shape:

```json
{
  "tests_to_run": [
    "tests/test_requests.py",
    "tests/test_lowlevel.py"
  ],
  "generated_tests": [
    "generated_tests/test_requests_api.py"
  ],
  "risk_score": 74,
  "risk_level": "high",
  "ci_action": "run_extended_pipeline",
  "pipeline_status": "ready"
}
```

## Phase 9 Done Criteria

- pipeline runs automatically on PRs
- artifacts uploaded consistently
- risk score influences CI behavior
- PR summary/report is generated
- fail-safe behavior is enforced when optional parts are unavailable

---

## Recommended Implementation Sequence

1. Build Phase 8 aggregator + scoring + report output.
2. Add unit tests for risk scoring logic.
3. Add minimal Phase 9 workflow to run pipeline + upload artifacts.
4. Add risk-based test execution branching.
5. Add PR reporting and policy enforcement.

## Current vs Target Summary

Current implemented phases:

- Phase 1 through Phase 7

Next target:

- implement Phase 8 risk scoring output
- implement Phase 9 CI orchestration and gating
