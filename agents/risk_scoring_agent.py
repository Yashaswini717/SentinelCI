import json
from pathlib import Path
from typing import Optional


class RiskScoringAgent:
    """
    Phase 8 - Risk Scoring System

    Reads all phase outputs and computes a deterministic
    risk score with clear reasoning and CI recommendations.

    Score range: 0 - 100
    """

    def __init__(
        self,
        pr_analysis_path: str = "storage/pr_analysis.json",
        impact_analysis_path: str = "storage/impact_analysis.json",
        semantic_impact_path: str = "storage/semantic_impact.json",
        test_selection_path: str = "storage/test_selection.json",
        test_generation_path: str = "storage/test_generation.json",
        dependency_metrics_path: str = "storage/dependency_metrics.json"
    ):
        self.pr_analysis_path = Path(pr_analysis_path)
        self.impact_analysis_path = Path(impact_analysis_path)
        self.semantic_impact_path = Path(semantic_impact_path)
        self.test_selection_path = Path(test_selection_path)
        self.test_generation_path = Path(test_generation_path)
        self.dependency_metrics_path = Path(dependency_metrics_path)

    # ── Loaders ──────────────────────────────────────────────────

    def _load_json(self, path: Path, default: Optional[dict] = None) -> dict:
        """Load JSON file safely - returns default if missing."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return default if default is not None else {}
        except json.JSONDecodeError:
            return default if default is not None else {}

    def _load_all(self) -> dict:
        """Load all phase outputs into one structure."""
        return {
            "pr": self._load_json(self.pr_analysis_path),
            "impact": self._load_json(self.impact_analysis_path),
            "semantic": self._load_json(
                self.semantic_impact_path,
                default={"semantic_related_modules": [], "total_semantic_matches": 0}
            ),
            "test_selection": self._load_json(
                self.test_selection_path,
                default={"tests_to_run": [], "coverage_gaps": [], "selection_summary": {}}
            ),
            "test_generation": self._load_json(
                self.test_generation_path,
                default={"generated_tests": [], "generation_summary": {}}
            ),
            "metrics": self._load_json(self.dependency_metrics_path)
        }

    # ── Component Scorers ─────────────────────────────────────────

    def _score_change_size(self, pr: dict) -> tuple[float, list[str]]:
        """
        Score based on how much code changed.
        Max: 20 points
        """
        metrics = pr.get("change_metrics", {})
        files_changed = metrics.get("files_changed", 0)
        lines_added = metrics.get("lines_added", 0)
        lines_deleted = metrics.get("lines_deleted", 0)
        total_lines = lines_added + lines_deleted

        score = 0.0
        drivers = []

        if files_changed >= 10:
            score += 10
            drivers.append(f"{files_changed} files changed (large change)")
        elif files_changed >= 5:
            score += 7
            drivers.append(f"{files_changed} files changed (medium change)")
        elif files_changed >= 2:
            score += 4
            drivers.append(f"{files_changed} files changed")
        else:
            score += 2

        if total_lines >= 500:
            score += 10
            drivers.append(f"{total_lines} lines changed (very large diff)")
        elif total_lines >= 100:
            score += 7
            drivers.append(f"{total_lines} lines changed (large diff)")
        elif total_lines >= 30:
            score += 4
            drivers.append(f"{total_lines} lines changed")
        else:
            score += 2

        return round(score, 2), drivers

    def _score_blast_radius(self, impact: dict) -> tuple[float, list[str]]:
        """
        Score based on how many modules are affected.
        Max: 25 points
        """
        summary = impact.get("impact_summary", {})
        direct_impact = summary.get("direct_impact", 0)
        indirect_impact = summary.get("indirect_impact", 0)
        blast_radius = summary.get("blast_radius", "none")

        score = 0.0
        drivers = []

        blast_scores = {
            "none": 0,
            "low": 5,
            "medium": 10,
            "high": 15,
            "critical": 15
        }
        score += blast_scores.get(blast_radius, 0)

        if blast_radius in ("high", "critical"):
            drivers.append(f"Blast radius is {blast_radius.upper()}")

        if direct_impact >= 3:
            score += 5
            drivers.append(f"{direct_impact} modules directly affected")
        elif direct_impact >= 1:
            score += 3
            drivers.append(f"{direct_impact} module directly affected")

        if indirect_impact >= 5:
            score += 5
            drivers.append(f"{indirect_impact} modules transitively affected")
        elif indirect_impact >= 2:
            score += 3
        elif indirect_impact >= 1:
            score += 1

        return round(score, 2), drivers

    def _score_dependency_criticality(
        self, impact: dict, metrics: dict
    ) -> tuple[float, list[str]]:
        """
        Score based on how critical the changed/affected modules are.
        Max: 20 points
        """
        affected_modules = impact.get("affected_modules", [])
        changed_modules = impact.get("changed_modules", [])
        all_modules = changed_modules + [
            m.get("module", "") for m in affected_modules
            if isinstance(m, dict)
        ]

        score = 0.0
        drivers = []
        max_fan_in = 0
        max_fan_out = 0

        for module in all_modules:
            m_metrics = metrics.get(module, {})
            fan_in = m_metrics.get("fan_in", 0)
            fan_out = m_metrics.get("fan_out", 0)
            max_fan_in = max(max_fan_in, fan_in)
            max_fan_out = max(max_fan_out, fan_out)

        if max_fan_in >= 8:
            score += 10
            drivers.append(
                f"High fan-in dependency affected (imported by {max_fan_in} modules)"
            )
        elif max_fan_in >= 5:
            score += 7
            drivers.append(f"Moderately critical dependency (fan_in={max_fan_in})")
        elif max_fan_in >= 2:
            score += 4
        else:
            score += 1

        if max_fan_out >= 8:
            score += 10
            drivers.append(
                f"Complex module affected (imports {max_fan_out} dependencies)"
            )
        elif max_fan_out >= 5:
            score += 7
        elif max_fan_out >= 2:
            score += 4
        else:
            score += 1

        return round(score, 2), drivers

    def _score_api_sensitivity(self, impact: dict) -> tuple[float, list[str]]:
        """
        Score based on what type of change was made.
        Max: 20 points
        """
        summary = impact.get("impact_summary", {})
        public_api_changed = summary.get("public_api_changed", False)
        change_type = summary.get("change_type", "unknown")

        score = 0.0
        drivers = []

        if public_api_changed:
            score += 12
            drivers.append("Public API function signature changed")

        if change_type == "signature_change":
            score += 8
            drivers.append("Signature change detected - callers may break")
        elif change_type == "body_change":
            score += 3
        else:
            score += 1

        return round(score, 2), drivers

    def _score_test_confidence(
        self, test_selection: dict, test_generation: dict
    ) -> tuple[float, list[str]]:
        """
        Score based on test coverage confidence.
        Higher coverage gaps = higher risk.
        Max: 15 points
        """
        coverage_gaps = test_selection.get("coverage_gaps", [])
        tests_to_run = test_selection.get("tests_to_run", [])
        generation_summary = test_generation.get("generation_summary", {})
        failed_generations = generation_summary.get("failed", 0)

        score = 0.0
        drivers = []

        if len(coverage_gaps) >= 3:
            score += 8
            drivers.append(
                f"{len(coverage_gaps)} affected modules have no test coverage"
            )
        elif len(coverage_gaps) >= 1:
            score += 5
            drivers.append(
                f"Coverage gap detected in {len(coverage_gaps)} module(s): "
                f"{', '.join(coverage_gaps[:2])}"
            )

        if len(tests_to_run) == 0:
            score += 4
            drivers.append("No tests selected - full regression recommended")

        if failed_generations > 0:
            score += 3
            drivers.append(f"{failed_generations} test generation(s) failed")

        return round(score, 2), drivers

    def _score_semantic_impact(self, semantic: dict) -> tuple[float, list[str]]:
        """
        Score based on semantic similarity matches.
        More matches = more hidden risk.
        Max: 10 points
        """
        total_matches = semantic.get("total_semantic_matches", 0)
        related_modules = semantic.get("semantic_related_modules", [])

        if total_matches == 0:
            return 0.0, []

        score = 0.0
        drivers = []

        if total_matches >= 5:
            score += 6
            drivers.append(
                f"{total_matches} semantically related modules detected "
                f"(hidden impact risk)"
            )
        elif total_matches >= 2:
            score += 4
            drivers.append(f"{total_matches} semantic matches found")
        else:
            score += 2

        if related_modules:
            avg_score = sum(
                m.get("score", 0) for m in related_modules
            ) / len(related_modules)
            if avg_score >= 0.70:
                score += 4
                drivers.append(
                    f"High semantic similarity detected (avg score: {avg_score:.2f})"
                )
            elif avg_score >= 0.55:
                score += 2

        return round(score, 2), drivers

    # ── Risk Classification ───────────────────────────────────────

    def _classify_risk(self, score: float) -> str:
        """Map score to risk level."""
        if score <= 30:
            return "low"
        elif score <= 60:
            return "medium"
        elif score <= 80:
            return "high"
        else:
            return "critical"

    # ── Recommendation Layer ──────────────────────────────────────

    def _build_recommendation(
        self, risk_level: str, test_selection: dict, all_drivers: list
    ) -> dict:
        """
        Map risk level to CI action.
        Message is dynamically built from actual drivers.
        """
        tests_to_run = test_selection.get("tests_to_run", [])

        # Action and suites are policy-based
        actions = {
            "low": {
                "action": "run_selected_tests",
                "required_suites": ["selected_tests"]
            },
            "medium": {
                "action": "run_extended_pipeline",
                "required_suites": ["selected_tests", "smoke_tests"]
            },
            "high": {
                "action": "run_extended_pipeline",
                "required_suites": [
                    "selected_tests",
                    "integration",
                    "regression_smoke"
                ]
            },
            "critical": {
                "action": "block_merge",
                "required_suites": [
                    "selected_tests",
                    "full_regression",
                    "integration",
                    "manual_review"
                ]
            }
        }

        rec = actions.get(risk_level, actions["medium"]).copy()

        # Dynamic message from actual drivers
        top_driver = all_drivers[0] if all_drivers else "multiple risk factors"
        driver_count = len(all_drivers)

        if risk_level == "low":
            rec["message"] = (
                f"Low risk - {driver_count} minor factor(s) detected. "
                f"Running selected tests is sufficient before merging."
            )
        elif risk_level == "medium":
            rec["message"] = (
                f"Medium risk - {driver_count} factor(s) detected. "
                f"Top concern: {top_driver}. "
                f"Run selected tests and smoke suite before merging."
            )
        elif risk_level == "high":
            rec["message"] = (
                f"High risk - {driver_count} factor(s) detected. "
                f"Top concern: {top_driver}. "
                f"Extended regression required before merging."
            )
        elif risk_level == "critical":
            rec["message"] = (
                f"Critical risk - {driver_count} factor(s) detected. "
                f"Top concern: {top_driver}. "
                f"Full regression and manual review required before merging."
            )

        rec["tests_to_run"] = tests_to_run
        rec["top_driver"] = top_driver
        rec["total_drivers"] = driver_count
        return rec

    # ── Main Scorer ───────────────────────────────────────────────

    def compute(self) -> dict:
        """
        Run full risk scoring pipeline.
        Returns complete risk report.
        """
        data = self._load_all()

        pr = data["pr"]
        impact = data["impact"]
        semantic = data["semantic"]
        test_selection = data["test_selection"]
        test_generation = data["test_generation"]
        metrics = data["metrics"]

        # Score each component
        change_size_score, change_drivers = self._score_change_size(pr)
        blast_score, blast_drivers = self._score_blast_radius(impact)
        dep_score, dep_drivers = self._score_dependency_criticality(
            impact, metrics
        )
        api_score, api_drivers = self._score_api_sensitivity(impact)
        test_score, test_drivers = self._score_test_confidence(
            test_selection, test_generation
        )
        semantic_score, semantic_drivers = self._score_semantic_impact(semantic)

        # Total score capped at 100
        total_score = min(100, round(
            change_size_score +
            blast_score +
            dep_score +
            api_score +
            test_score +
            semantic_score,
            2
        ))

        # Classify risk level
        risk_level = self._classify_risk(total_score)

        # Combine all drivers from all scorers
        all_drivers = (
            change_drivers +
            blast_drivers +
            dep_drivers +
            api_drivers +
            test_drivers +
            semantic_drivers
        )

        # Build dynamic recommendation using actual drivers
        recommendation = self._build_recommendation(
            risk_level, test_selection, all_drivers
        )

        return {
            "risk_score": total_score,
            "risk_level": risk_level,
            "drivers": all_drivers,
            "components": {
                "change_size": change_size_score,
                "blast_radius": blast_score,
                "dependency_criticality": dep_score,
                "api_sensitivity": api_score,
                "coverage_confidence": test_score,
                "semantic_impact": semantic_score
            },
            "recommendation": recommendation
        }

    def save(self, output_path: str = "storage/risk_report.json") -> dict:
        """Compute and save risk report."""
        result = self.compute()
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w") as f:
            json.dump(result, f, indent=2)

        print(f"Saved risk report -> {output_path}")
        return result

