import json
from collections import defaultdict
from pathlib import Path


def load_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {} if default is None else default


def normalize_module_name(module: str) -> str:
    normalized = module.replace("\\", "/")
    normalized = normalized.replace(".py", "")
    return normalized.strip("/")


def invert_test_mapping(test_mapping: dict) -> dict:
    module_to_tests = defaultdict(set)

    for test_file, modules in test_mapping.items():
        if not isinstance(modules, list):
            continue
        for module in modules:
            if not isinstance(module, str):
                continue
            module_to_tests[normalize_module_name(module)].add(test_file)

    return module_to_tests


def is_valid_test_file(test_path: str) -> bool:
    return test_path.startswith("tests/test_") or "/test_" in test_path


def compute_risk_score(module: str, dependency_metrics: dict, impact_lookup: dict) -> float:
    metrics = dependency_metrics.get(module, {})
    fan_in = metrics.get("fan_in", 0)
    fan_out = metrics.get("fan_out", 0)

    impact = impact_lookup.get(module, {})
    depth = impact.get("depth", 1)
    try:
        depth_num = max(1, int(depth))
    except Exception:
        depth_num = 1

    return float(fan_in * 2 + fan_out + (3 - depth_num) * 2)


def run_test_selection(output_path: str = "storage/test_selection.json"):
    print("\nRunning Phase 6: Test Selection Engine\n")

    impact_data = load_json("storage/impact_analysis.json", default={})
    semantic_data = load_json(
        "storage/semantic_impact.json",
        default={"semantic_related_modules": [], "total_semantic_matches": 0}
    )
    raw_test_mapping = load_json("storage/test_mapping.json", default={})
    dependency_metrics = load_json("storage/dependency_metrics.json", default={})

    module_to_tests = invert_test_mapping(raw_test_mapping)

    affected_modules_raw = impact_data.get("affected_modules", [])
    if not isinstance(affected_modules_raw, list):
        affected_modules_raw = []

    affected_modules = []
    impact_lookup = {}
    for item in affected_modules_raw:
        if not isinstance(item, dict):
            continue
        module = item.get("module")
        if not isinstance(module, str):
            continue
        module_key = normalize_module_name(module)
        affected_modules.append(module_key)
        impact_lookup[module_key] = item

    changed_modules_raw = impact_data.get("changed_modules", [])
    if not isinstance(changed_modules_raw, list):
        changed_modules_raw = []
    changed_modules = [
        normalize_module_name(m)
        for m in changed_modules_raw
        if isinstance(m, str)
    ]

    semantic_related_raw = semantic_data.get("semantic_related_modules", [])
    if not isinstance(semantic_related_raw, list):
        semantic_related_raw = []
    semantic_modules = [
        normalize_module_name(item["module"])
        for item in semantic_related_raw
        if isinstance(item, dict) and isinstance(item.get("module"), str)
    ]

    test_candidates = {}

    def ensure_candidate(test_path: str) -> dict:
        if test_path not in test_candidates:
            test_candidates[test_path] = {
                "priority": 999,
                "score": 0.0,
                "reasons": []
            }
        return test_candidates[test_path]

    for module in affected_modules:
        tests = sorted(module_to_tests.get(module, set()))
        if not tests:
            continue
        risk = compute_risk_score(module, dependency_metrics, impact_lookup)
        for test in tests:
            if not is_valid_test_file(test):
                continue
            cand = ensure_candidate(test)
            current_priority = int(cand["priority"])
            current_score = float(cand["score"])
            current_reasons = list(cand["reasons"])

            cand["priority"] = min(current_priority, 1)
            cand["score"] = current_score + risk
            current_reasons.append(f"static:{module}")
            cand["reasons"] = current_reasons

    for module in semantic_modules[:5]:
        tests = sorted(module_to_tests.get(module, set()))
        if not tests:
            continue
        risk = compute_risk_score(module, dependency_metrics, impact_lookup)
        for test in tests:
            if not is_valid_test_file(test):
                continue
            cand = ensure_candidate(test)
            current_priority = int(cand["priority"])
            current_score = float(cand["score"])
            current_reasons = list(cand["reasons"])

            if current_priority > 1:
                cand["priority"] = 2

            cand["score"] = current_score + (risk * 0.5)
            current_reasons.append(f"semantic:{module}")
            cand["reasons"] = current_reasons

    coverage_gaps = [
        module for module in sorted(set(affected_modules + changed_modules))
        if module not in module_to_tests
    ]

    if not test_candidates:
        print("WARNING: No mapped tests found -> fallback to all discovered tests")
        all_tests = set()
        for tests in module_to_tests.values():
            for test in tests:
                if is_valid_test_file(test):
                    all_tests.add(test)
        for test in sorted(all_tests):
            test_candidates[test] = {
                "priority": 3,
                "score": 0.0,
                "reasons": ["fallback_all_tests"]
            }

    tests_to_run = sorted(
        test_candidates.keys(),
        key=lambda test: (int(test_candidates[test]["priority"]), -float(test_candidates[test]["score"]))
    )

    test_details = {
        test: {
            "priority": int(details["priority"]),
            "score": round(float(details["score"]), 2),
            "reasons": sorted(set(list(details["reasons"])))
        }
        for test, details in test_candidates.items()
    }

    output = {
        "tests_to_run": tests_to_run,
        "selection_summary": {
            "total_tests": len(tests_to_run),
            "static_tests": sum(1 for t in tests_to_run if test_candidates[t]["priority"] == 1),
            "semantic_tests": sum(1 for t in tests_to_run if test_candidates[t]["priority"] == 2),
            "fallback_tests": sum(1 for t in tests_to_run if test_candidates[t]["priority"] == 3)
        },
        "coverage_gaps": coverage_gaps,
        "test_details": test_details
    }

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"Selected {len(tests_to_run)} tests")
    print(f"Coverage gaps: {len(coverage_gaps)} modules")
    return output
