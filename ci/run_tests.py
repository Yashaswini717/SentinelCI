import json
import os
import subprocess
import sys
import time
from pathlib import Path


# pytest exit codes: https://docs.pytest.org/en/stable/reference/exit-codes.html
EXIT_STATUS = {
    0: "passed",
    1: "failed",
    2: "error",       # interrupted
    3: "error",       # internal error
    4: "error",       # usage error, e.g. a path that doesn't exist
    5: "no_tests",    # nothing collected, e.g. no tests carry a marker
}

# Environment variables never passed to test processes - test code
# (including auto-generated tests) doesn't need credentials
SECRET_ENV_VARS = ("GITHUB_TOKEN", "OPENROUTER_API_KEY", "ACTIONS_RUNTIME_TOKEN")


def classify_exit_code(returncode: int) -> str:
    return EXIT_STATUS.get(returncode, "error")


def run_one(run: dict, timeout: int) -> dict:
    """Run a single pytest invocation and record its outcome."""
    args = [sys.executable, "-m", "pytest", *run.get("pytest_args", [])]
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV_VARS}

    print(f"\n>>> [{run.get('name')}] {run.get('command')}", flush=True)
    start = time.monotonic()

    try:
        result = subprocess.run(args, env=env, timeout=timeout)
        returncode = result.returncode
        status = classify_exit_code(returncode)
    except subprocess.TimeoutExpired:
        returncode = None
        status = "timeout"

    return {
        "name": run.get("name"),
        "command": run.get("command"),
        "blocking": bool(run.get("blocking", True)),
        "status": status,
        "returncode": returncode,
        "duration_seconds": round(time.monotonic() - start, 1)
    }


def run_tests(
    decision_path: str = "storage/ci_decision.json",
    output_path: str = "storage/test_execution.json",
    timeout: int = 600
) -> int:
    """
    Execute the test runs chosen by the CI decision.
    Returns the process exit code: 1 if any blocking run failed.
    """
    try:
        with open(decision_path, "r", encoding="utf-8") as f:
            decision = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Cannot read {decision_path}: {e}")
        return 1

    runs = decision.get("test_runs", [])
    print(f"Risk level: {decision.get('risk_level', 'unknown')}")
    print(f"Test runs : {len(runs)}")

    results = [run_one(run, timeout) for run in runs]

    blocking_failures = [
        r for r in results
        if r["blocking"] and r["status"] in ("failed", "error", "timeout")
    ]

    if not results:
        overall = "no_tests"
    elif blocking_failures:
        overall = "failed"
    elif all(r["status"] == "no_tests" for r in results):
        overall = "no_tests"
    else:
        overall = "passed"

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump({
            "risk_level": decision.get("risk_level"),
            "overall": overall,
            "results": results
        }, f, indent=2)

    print("\n" + "=" * 55)
    print("  TEST EXECUTION SUMMARY")
    print("=" * 55)
    if not results:
        print("  No tests to run.")
    for r in results:
        blocking = "" if r["blocking"] else " (non-blocking)"
        print(f"  {r['status'].upper():<9} {r['name']}{blocking}")
    print("=" * 55)

    for r in results:
        if not r["blocking"] and r["status"] != "passed" and r["status"] != "no_tests":
            print(f"::warning::Non-blocking test run '{r['name']}' {r['status']}")

    if blocking_failures:
        names = ", ".join(r["name"] for r in blocking_failures)
        print(f"::error::Blocking test run(s) failed: {names}")
        return 1

    return 0


if __name__ == "__main__":
    timeout = int(os.getenv("TEST_RUN_TIMEOUT", "600"))
    sys.exit(run_tests(timeout=timeout))
