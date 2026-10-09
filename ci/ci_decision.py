import json
import shlex
from pathlib import Path
from typing import Optional


class CIDecision:
    """
    Phase 9 - CI Decision Executor

    Reads risk_report.json and test_selection.json
    and decides exactly what the CI pipeline should do.
    """

    def __init__(
        self,
        risk_report_path: str = "storage/risk_report.json",
        test_selection_path: str = "storage/test_selection.json",
        test_generation_path: str = "storage/test_generation.json",
        repo_path: Optional[str] = None
    ):
        # Root of the analyzed repo, used to check which test paths exist
        self.repo_path = Path(repo_path) if repo_path else None
        self.risk_report_path = Path(risk_report_path)
        self.test_selection_path = Path(test_selection_path)
        self.test_generation_path = Path(test_generation_path)

    def _load_json(self, path: Path, default: Optional[dict] = None) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return default if default is not None else {}
        except json.JSONDecodeError:
            return default if default is not None else {}

    def _existing(self, paths: list) -> list:
        """Keep only test paths that exist in the analyzed repo."""
        if self.repo_path is None:
            return [p for p in paths if isinstance(p, str)]
        return [
            p for p in paths
            if isinstance(p, str) and (self.repo_path / p).exists()
        ]

    def _find_test_dir(self) -> Optional[str]:
        """Find the repo's main test folder, if it has one."""
        if self.repo_path is None:
            return None
        for name in ("tests", "test"):
            if (self.repo_path / name).is_dir():
                return name
        return None

    def _get_test_runs(
        self, tests_to_run: list, generated_tests: list, risk_level: str
    ) -> list:
        """
        Build the pytest runs the CI should execute.

        Each run has pytest arguments and a "blocking" flag. Failures in
        blocking runs fail CI; generated tests are informational only,
        since auto-generated code can be wrong.
        """
        runs = []
        selected = self._existing(tests_to_run)
        test_dir = self._find_test_dir()

        if selected:
            runs.append({
                "name": "selected_tests",
                "pytest_args": selected + ["-v", "--tb=short"],
                "blocking": True
            })
        elif test_dir:
            # Nothing mapped to the change - run the whole suite to be safe
            runs.append({
                "name": "full_suite",
                "pytest_args": [test_dir, "-v", "--tb=short"],
                "blocking": True
            })

        if test_dir and selected:
            if risk_level == "medium":
                runs.append({
                    "name": "smoke_tests",
                    "pytest_args": [test_dir, "-v", "-m", "smoke", "--tb=short"],
                    "blocking": True
                })
            elif risk_level == "high":
                runs.append({
                    "name": "smoke_and_integration_tests",
                    "pytest_args": [test_dir, "-v", "-m", "smoke or integration", "--tb=short"],
                    "blocking": True
                })
            elif risk_level == "critical":
                runs.append({
                    "name": "full_regression",
                    "pytest_args": [test_dir, "-v", "--tb=long"],
                    "blocking": True
                })

        # Generated tests are written by SentinelCI relative to the working
        # directory, not inside the analyzed repo
        generated = [
            p for p in generated_tests
            if isinstance(p, str) and Path(p).exists()
        ]
        if generated:
            runs.append({
                "name": "generated_tests",
                "pytest_args": generated + ["-v", "--tb=short"],
                "blocking": False
            })

        for run in runs:
            run["command"] = "python -m pytest " + shlex.join(run["pytest_args"])

        return runs

    def _get_pipeline_status(
        self, risk_level: str, coverage_gaps: list
    ) -> str:
        """Determine overall pipeline status."""
        if risk_level == "critical":
            return "blocked"
        elif risk_level == "high" and len(coverage_gaps) > 2:
            return "warning"
        else:
            return "ready"

    def decide(self) -> dict:
        """Build the CI decision from risk report."""
        risk_report = self._load_json(self.risk_report_path)
        test_selection = self._load_json(
            self.test_selection_path,
            default={"tests_to_run": [], "coverage_gaps": []}
        )
        test_generation = self._load_json(
            self.test_generation_path,
            default={"generated_tests": []}
        )

        # Fail-safe: if risk report missing, block merge
        if not risk_report:
            print("FAIL-SAFE triggered: risk_report.json missing or empty.")
            test_runs = self._get_test_runs([], [], "critical")
            return {
                "error": "risk_report.json not found",
                "pipeline_status": "blocked",
                "ci_action": "fail_safe",
                "risk_score": 100,
                "risk_level": "critical",
                "message": (
                    "Risk report missing - core pipeline may have failed. "
                    "Failing safe to protect codebase."
                ),
                "tests_to_run": [],
                "generated_tests": [],
                "coverage_gaps": [],
                "required_suites": ["full_regression"],
                "test_runs": test_runs,
                "test_commands": [r["command"] for r in test_runs],
                "top_drivers": ["Risk report unavailable"],
                "total_risk_drivers": 1
            }

        risk_score = risk_report.get("risk_score", 0)
        risk_level = risk_report.get("risk_level", "unknown")
        recommendation = risk_report.get("recommendation", {})
        drivers = risk_report.get("drivers", [])

        tests_to_run = test_selection.get("tests_to_run", [])
        coverage_gaps = test_selection.get("coverage_gaps", [])
        generated_tests = test_generation.get("generated_tests", [])
        generated_test_paths = [
            t.get("path", "") for t in generated_tests
            if isinstance(t, dict)
        ]

        ci_action = recommendation.get("action", "run_selected_tests")
        required_suites = recommendation.get("required_suites", [])
        message = recommendation.get("message", "")

        test_runs = self._get_test_runs(
            tests_to_run, generated_test_paths, risk_level
        )
        pipeline_status = self._get_pipeline_status(risk_level, coverage_gaps)

        return {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "ci_action": ci_action,
            "pipeline_status": pipeline_status,
            "message": message,
            "tests_to_run": tests_to_run,
            "generated_tests": generated_test_paths,
            "coverage_gaps": coverage_gaps,
            "required_suites": required_suites,
            "test_runs": test_runs,
            "test_commands": [r["command"] for r in test_runs],
            "top_drivers": drivers[:3],
            "total_risk_drivers": len(drivers),
            "score_breakdown": {
                name: {"points": points, "max": risk_report.get("max_points", {}).get(name)}
                for name, points in risk_report.get("components", {}).items()
            }
        }

    def save(self, output_path: str = "storage/ci_decision.json") -> dict:
        """Build and save CI decision."""
        result = self.decide()
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        print(f"Saved CI decision -> {output_path}")
        return result
