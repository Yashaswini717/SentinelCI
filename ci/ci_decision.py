import json
import os
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
        test_generation_path: str = "storage/test_generation.json"
    ):
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

    def _get_test_commands(self, tests_to_run: list, risk_level: str) -> list:
        """Generate pytest commands based on selected tests and risk level."""
        commands = []

        def quote(path: str) -> str:
            if any(ch in path for ch in [" ", "\t", "\n", "\""]):
                escaped = path.replace("\"", '\\\"')
                return f'"{escaped}"'
            return path

        if not tests_to_run:
            if risk_level in ("high", "critical"):
                commands.append("pytest tests/ -v")
            else:
                commands.append("pytest tests/ -v --tb=short")
            return commands

        test_args = " ".join(quote(test) for test in tests_to_run)
        commands.append(f"pytest {test_args} -v")

        if risk_level == "medium":
            commands.append("pytest tests/ -v -m smoke --tb=short")
        elif risk_level == "high":
            commands.append("pytest tests/ -v -m 'smoke or integration' --tb=short")
        elif risk_level == "critical":
            commands.append("pytest tests/ -v --tb=long")

        return commands

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
                "test_commands": ["pytest tests/ -v"],
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

        test_commands = self._get_test_commands(tests_to_run, risk_level)
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
            "test_commands": test_commands,
            "top_drivers": drivers[:3],
            "total_risk_drivers": len(drivers)
        }

    def save(self, output_path: str = "storage/ci_decision.json") -> dict:
        """Build and save CI decision."""
        result = self.decide()
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w") as f:
            json.dump(result, f, indent=2)

        print(f"Saved CI decision -> {output_path}")
        return result
