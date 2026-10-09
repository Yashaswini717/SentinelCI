import json
from pathlib import Path, PurePosixPath
from typing import Optional


class RiskScoringAgent:
    """
    Phase 8 - Risk Scoring System

    Reads all phase outputs and computes a deterministic, explainable
    risk score. The factors are the ones defect-prediction research links
    to risky changes (change size and relative churn, dependency structure,
    API changes, test coverage).

    Each factor is scored from 0.0 to 1.0 with a smooth curve - no
    cliffs where one extra line jumps the score - and measured relative
    to the repository where possible, so the same rules work for small
    and large repos. The score is the weighted sum; weights add up to 100.
    """

    # Points available for each factor - sums to 100
    WEIGHTS = {
        "change_size": 20,
        "blast_radius": 25,
        "coupling": 10,
        "api_break": 20,
        "test_coverage": 20,
        "semantic_impact": 5,
    }

    # Lines in brand-new files count for less: nothing calls new code yet,
    # so it can't break existing behavior until it's wired in
    NEW_FILE_LINE_WEIGHT = 0.5

    # Effective changed lines at which the size factor reaches half
    SIZE_HALF_POINT = 250

    def __init__(
        self,
        pr_analysis_path: str = "storage/pr_analysis.json",
        impact_analysis_path: str = "storage/impact_analysis.json",
        semantic_impact_path: str = "storage/semantic_impact.json",
        test_selection_path: str = "storage/test_selection.json",
        test_generation_path: str = "storage/test_generation.json",
        dependency_metrics_path: str = "storage/dependency_metrics.json",
        repo_structure_path: str = "storage/repo_structure.json",
        repo_path: Optional[str] = None
    ):
        self.pr_analysis_path = Path(pr_analysis_path)
        self.impact_analysis_path = Path(impact_analysis_path)
        self.semantic_impact_path = Path(semantic_impact_path)
        self.test_selection_path = Path(test_selection_path)
        self.test_generation_path = Path(test_generation_path)
        self.dependency_metrics_path = Path(dependency_metrics_path)
        self.repo_structure_path = Path(repo_structure_path)
        # Root of the analyzed repo, used to measure file sizes
        self.repo_path = Path(repo_path) if repo_path else None

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
                default={"tests_to_run": [], "coverage_gaps": []}
            ),
            "metrics": self._load_json(self.dependency_metrics_path),
            "structure": self._load_json(self.repo_structure_path),
        }

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _saturate(value: float, half_point: float) -> float:
        """Smooth 0..1 curve: 0 at 0, 0.5 at half_point, approaching 1."""
        if value <= 0:
            return 0.0
        return value / (value + half_point)

    @staticmethod
    def _percentile_rank(value: float, population: list) -> float:
        """Share of the population strictly below value (0..1)."""
        if not population:
            return 0.0
        return sum(1 for v in population if v < value) / len(population)

    def _is_test_path(self, path: str, test_paths: set) -> bool:
        if path in test_paths:
            return True
        parts = PurePosixPath(path).parts
        name = parts[-1] if parts else ""
        return (
            any(part in ("test", "tests") for part in parts[:-1])
            or name.startswith("test_")
            or name.endswith("_test.py")
        )

    def _count_lines(self, path: str) -> Optional[int]:
        if self.repo_path is None:
            return None
        full = self.repo_path / path
        try:
            return len(full.read_text(encoding="utf-8", errors="ignore").splitlines())
        except OSError:
            return None

    # ── Factor Scorers (each returns score 0..1, detail, driver) ──

    def _score_change_size(self, pr: dict, structure: dict) -> tuple[float, dict, str]:
        """
        How much existing code the PR changes.

        Effective lines = lines changed in existing non-test Python files
        + half the lines in brand-new files. Combined with relative churn -
        the share of the touched files that was rewritten - which research
        finds predicts defects better than raw line counts (Nagappan & Ball,
        ICSE 2005).
        """
        test_paths = set(structure.get("test_file_map", {}).values())
        modified_lines = 0
        new_lines = 0
        modified_files = []

        for path, stats in pr.get("file_stats", {}).items():
            if not path.endswith(".py") or self._is_test_path(path, test_paths):
                continue
            added = stats.get("added", 0)
            deleted = stats.get("deleted", 0)
            if stats.get("status") == "added":
                new_lines += added
            else:
                modified_lines += added + deleted
                if stats.get("status") != "removed":
                    modified_files.append((path, added + deleted))

        effective = modified_lines + self.NEW_FILE_LINE_WEIGHT * new_lines
        size = self._saturate(effective, self.SIZE_HALF_POINT)

        # Relative churn of the modified files
        churn = None
        sizes = [(self._count_lines(p), c) for p, c in modified_files]
        known = [(lines, c) for lines, c in sizes if lines]
        if known:
            churn = min(1.0, sum(c for _, c in known) / sum(lines for lines, _ in known))

        score = size if churn is None else 0.6 * size + 0.4 * churn

        detail = {
            "modified_lines": modified_lines,
            "new_file_lines": new_lines,
            "effective_lines": round(effective),
            "relative_churn": None if churn is None else round(churn, 2),
        }
        driver = f"{modified_lines} lines changed in existing code, {new_lines} in new files"
        if churn is not None:
            driver += f" ({churn:.0%} of the touched files rewritten)"
        return score, detail, driver

    def _score_blast_radius(self, impact: dict, metrics: dict) -> tuple[float, dict, str]:
        """
        How much of the rest of the codebase depends on the changed code.

        Each dependent module counts by distance: direct importers 1.0,
        then 0.5, 0.25, ... Scored relative to the size of the rest of
        the repo (30% of it = maximum) or absolutely (20 = maximum),
        whichever is higher.
        """
        affected = impact.get("affected_modules", [])
        changed = impact.get("changed_modules", [])

        weighted = sum(
            0.5 ** (max(1, int(m.get("depth", 1))) - 1)
            for m in affected if isinstance(m, dict)
        )
        others = max(1, len(metrics) - len(changed))
        relative = min(1.0, (weighted / others) / 0.3)
        absolute = min(1.0, weighted / 20)
        score = max(relative, absolute)

        direct = sum(1 for m in affected if isinstance(m, dict) and m.get("depth") == 1)
        detail = {
            "affected_modules": len(affected),
            "direct_dependents": direct,
            "weighted_dependents": round(weighted, 2),
            "share_of_other_modules": round(weighted / others, 2),
        }
        driver = (
            f"{len(affected)} other module(s) depend on the changed code "
            f"({direct} directly)"
        )
        return score, detail, driver

    def _score_coupling(self, impact: dict, metrics: dict) -> tuple[float, dict, str]:
        """
        How tightly coupled the changed modules are: a module that imports
        many others is more complex and more likely to break when changed.

        Needs both a high fan-out rank within this repo and a high fan-out
        in absolute terms (5 imports = half), so the most-coupled module of
        a loosely coupled repo doesn't automatically score the maximum.
        """
        fan_outs = [m.get("fan_out", 0) for m in metrics.values()]
        best_module, best_score, best_rank, best_fan_out = None, 0.0, 0.0, 0
        for module in impact.get("changed_modules", []):
            fan_out = metrics.get(module, {}).get("fan_out", 0)
            if fan_out == 0:
                continue
            rank = self._percentile_rank(fan_out, fan_outs)
            module_score = rank * self._saturate(fan_out, 5)
            if module_score > best_score:
                best_module, best_score, best_rank, best_fan_out = module, module_score, rank, fan_out

        detail = {"most_coupled_module": best_module, "fan_out": best_fan_out,
                  "fan_out_rank": round(best_rank, 2)}
        driver = (
            f"Changed module {best_module} imports {best_fan_out} other modules "
            f"(more than {best_rank:.0%} of modules in this repo)"
            if best_module else "Changed modules have few dependencies"
        )
        return best_score, detail, driver

    def _score_api_break(self, pr: dict, impact: dict) -> tuple[float, dict, str]:
        """
        Changed or removed public signatures can break callers - but only
        if something calls them. Scaled by how many modules import the
        changed code. Adding new public functions is low risk.
        """
        breaking = sorted(
            n for n in pr.get("modified_definitions", []) if not n.startswith("_")
        )
        added = sorted(
            n for n in pr.get("changed_functions", []) + pr.get("changed_classes", [])
            if not n.startswith("_") and n not in breaking
        )
        dependents = sum(
            1 for m in impact.get("affected_modules", [])
            if isinstance(m, dict) and m.get("depth") == 1
        )

        if breaking:
            breadth = 0.5 + 0.5 * min(1.0, len(breaking) / 5)
            exposure = 0.3 + 0.7 * min(1.0, dependents / 3)
            score = breadth * exposure
            shown = ", ".join(breaking[:3]) + (f" (+{len(breaking) - 3} more)" if len(breaking) > 3 else "")
            # Callers changed in the same PR were updated along with the
            # signature, so only unchanged importers are at risk
            driver = (
                f"Public signature(s) changed: {shown} - "
                f"{dependents} unchanged module(s) import the changed code"
            )
        elif added:
            score = 0.15
            driver = f"{len(added)} new public function(s)/class(es) added"
        else:
            score = 0.0
            driver = "No public API changes"

        detail = {"breaking_symbols": breaking, "new_public_symbols": len(added),
                  "direct_dependents": dependents}
        return score, detail, driver

    def _score_test_coverage(self, pr: dict, impact: dict, test_selection: dict) -> tuple[float, dict, str]:
        """
        Share of the changed and affected modules with no tests. A PR that
        also updates tests gets credit - the change came with test changes.
        """
        scope = set(impact.get("changed_modules", [])) | {
            m.get("module") for m in impact.get("affected_modules", []) if isinstance(m, dict)
        }
        gaps = [g for g in test_selection.get("coverage_gaps", []) if g in scope]
        gap_share = len(gaps) / len(scope) if scope else 0.0
        tests_updated = bool(pr.get("changed_tests"))

        score = gap_share * (0.6 if tests_updated else 1.0)
        detail = {"modules_in_scope": len(scope), "untested_modules": len(gaps),
                  "tests_updated_in_pr": tests_updated}
        driver = f"{len(gaps)} of {len(scope)} changed/affected module(s) have no tests"
        if tests_updated:
            driver += " (PR updates tests)"
        return score, detail, driver

    def _score_semantic_impact(self, semantic: dict) -> tuple[float, dict, str]:
        """Code that looks similar to the change may need the same fix."""
        matches = semantic.get("total_semantic_matches", 0)
        score = min(1.0, matches / 5)
        detail = {"semantic_matches": matches}
        driver = f"{matches} semantically similar module(s) may also be affected"
        return score, detail, driver

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
        metrics = data["metrics"]

        factors = {
            "change_size": self._score_change_size(pr, data["structure"]),
            "blast_radius": self._score_blast_radius(impact, metrics),
            "coupling": self._score_coupling(impact, metrics),
            "api_break": self._score_api_break(pr, impact),
            "test_coverage": self._score_test_coverage(pr, impact, data["test_selection"]),
            "semantic_impact": self._score_semantic_impact(data["semantic"]),
        }

        components = {
            name: round(self.WEIGHTS[name] * score, 1)
            for name, (score, _, _) in factors.items()
        }
        total_score = round(sum(components.values()), 1)
        risk_level = self._classify_risk(total_score)

        # Explain the score: factors in order of points contributed,
        # skipping those that barely moved it
        ranked = sorted(factors, key=lambda name: components[name], reverse=True)
        all_drivers = [
            f"{factors[name][2]} (+{components[name]:g} pts)"
            for name in ranked if components[name] >= 2
        ]

        recommendation = self._build_recommendation(
            risk_level, data["test_selection"], all_drivers
        )

        return {
            "risk_score": total_score,
            "risk_level": risk_level,
            "drivers": all_drivers,
            "components": components,
            "max_points": self.WEIGHTS,
            "factor_details": {name: detail for name, (_, detail, _) in factors.items()},
            "recommendation": recommendation
        }

    def save(self, output_path: str = "storage/risk_report.json") -> dict:
        """Compute and save risk report."""
        result = self.compute()
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        print(f"Saved risk report -> {output_path}")
        return result
