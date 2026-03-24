import json
from pathlib import Path
from collections import deque


class ChangeImpactAgent:
    def __init__(
        self,
        dependency_graph_path: str = "storage/dependency_graph.json",
        dependency_metrics_path: str = "storage/dependency_metrics.json",
        pr_analysis_path: str = "storage/pr_analysis.json",
        repo_structure_path: str = "storage/repo_structure.json",
        function_index_path: str = "storage/function_index.json",
        class_index_path: str = "storage/class_index.json",
        test_mapping_path: str = "storage/test_mapping.json"
    ):
        self.dependency_graph_path = Path(dependency_graph_path)
        self.dependency_metrics_path = Path(dependency_metrics_path)
        self.pr_analysis_path = Path(pr_analysis_path)
        self.repo_structure_path = Path(repo_structure_path)
        self.function_index_path = Path(function_index_path)
        self.class_index_path = Path(class_index_path)
        self.test_mapping_path = Path(test_mapping_path)

        self.graph = {}
        self.reverse_graph = {}
        self.metrics = {}
        self.pr_analysis = {}
        self.repo_structure = {}
        self.function_index = {}
        self.class_index = {}
        self.test_mapping = {}

    # ── Loaders ──────────────────────────────────────────────────

    def _load_all(self):
        """Load all required data from storage."""
        with open(self.dependency_graph_path) as f:
            self.graph = json.load(f)

        with open(self.dependency_metrics_path) as f:
            self.metrics = json.load(f)

        with open(self.pr_analysis_path) as f:
            self.pr_analysis = json.load(f)

        with open(self.repo_structure_path) as f:
            self.repo_structure = json.load(f)

        if self.function_index_path.exists():
            with open(self.function_index_path) as f:
                self.function_index = json.load(f)

        if self.class_index_path.exists():
            with open(self.class_index_path) as f:
                self.class_index = json.load(f)

        if self.test_mapping_path.exists():
            with open(self.test_mapping_path) as f:
                self.test_mapping = json.load(f)

        self.reverse_graph = self._build_reverse_graph(self.graph)

    def _build_reverse_graph(self, graph: dict) -> dict:
        """Build reverse graph: for each module, who imports it."""
        reverse = {}
        for module, deps in graph.items():
            for dep in deps:
                reverse.setdefault(dep, [])
                if module not in reverse[dep]:
                    reverse[dep].append(module)
        return reverse

    # ── Core Traversal ───────────────────────────────────────────

    def _bfs_with_depth(self, start_module: str) -> dict:
        """
        BFS traversal returning each affected module with its depth.
        depth 1 = directly imports changed module
        depth 2 = imports something at depth 1
        """
        visited = {}
        queue = deque([(start_module, 0)])

        while queue:
            current, depth = queue.popleft()
            if current in visited:
                continue
            visited[current] = depth
            for affected in self.reverse_graph.get(current, []):
                if affected not in visited:
                    queue.append((affected, depth + 1))

        # Remove the start module itself
        visited.pop(start_module, None)
        return visited

    def _find_dependency_path(self, start: str, target: str) -> list:
        """
        Find shortest path from changed module to affected module.
        Shows WHY a module is impacted.
        e.g. compat -> structures -> cookies -> sessions
        """
        queue = deque([[start]])
        visited = {start}

        while queue:
            path = queue.popleft()
            current = path[-1]

            if current == target:
                return path

            for neighbor in self.reverse_graph.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])

        return [start, target]

    # ── Impact Classification ────────────────────────────────────

    def _classify_change_type(self, changed_module: str) -> str:
        """
        Classify the type of change based on what was modified.
        signature_change = function/class added or removed (higher risk)
        body_change = only internal logic changed (lower risk)
        """
        changed_functions = self.pr_analysis.get("changed_functions", [])
        changed_classes = self.pr_analysis.get("changed_classes", [])
        modified_symbols = self.pr_analysis.get("modified_symbols", [])

        # Check if any public symbols changed (not starting with _)
        public_functions = [f for f in changed_functions if not f.startswith("_")]
        public_classes = [c for c in changed_classes if not c.startswith("_")]

        if public_functions or public_classes:
            return "signature_change"
        elif modified_symbols:
            return "body_change"
        else:
            return "unknown"

    def _is_public_api_change(self, changed_module: str) -> bool:
        """Check if the change affects public API (non-private symbols)."""
        changed_functions = self.pr_analysis.get("changed_functions", [])
        changed_classes = self.pr_analysis.get("changed_classes", [])

        public_functions = [f for f in changed_functions if not f.startswith("_")]
        public_classes = [c for c in changed_classes if not c.startswith("_")]

        return bool(public_functions or public_classes)

    # ── Confidence Scoring ───────────────────────────────────────

    def _compute_confidence(
        self,
        affected_module: str,
        depth: int,
        changed_module: str,
        change_type: str
    ) -> float:
        """
        Compute confidence score (0.0 to 1.0) that this module is affected.

        Factors:
        - depth: deeper = less confident
        - fan_in of changed module: more dependents = more spread
        - change_type: signature change = higher confidence
        - metrics: fan_out of affected module
        """
        base_confidence = 1.0

        # Depth penalty: each level reduces confidence
        depth_penalty = 0.15 * (depth - 1)
        base_confidence -= depth_penalty

        # Change type bonus
        if change_type == "signature_change":
            base_confidence += 0.1
        elif change_type == "body_change":
            base_confidence -= 0.05

        # Fan-in bonus: if changed module is heavily imported, higher confidence
        fan_in = self.metrics.get(changed_module, {}).get("fan_in", 0)
        if fan_in > 5:
            base_confidence += 0.05

        # Clamp between 0.1 and 1.0
        return round(max(0.1, min(1.0, base_confidence)), 2)

    # ── Blast Radius ─────────────────────────────────────────────

    def _compute_blast_radius(
        self,
        total_affected: int,
        direct_count: int,
        change_type: str
    ) -> str:
        """
        Classify blast radius as low/medium/high/critical.
        """
        # Weight: signature changes are riskier
        weight = 1.5 if change_type == "signature_change" else 1.0
        weighted_score = total_affected * weight

        if weighted_score == 0:
            return "none"
        elif weighted_score <= 2:
            return "low"
        elif weighted_score <= 5:
            return "medium"
        elif weighted_score <= 10:
            return "high"
        else:
            return "critical"

    # ── Test Impact ──────────────────────────────────────────────

    def _find_impacted_tests(self, all_affected_modules: list) -> list:
        """
        Find all test files that cover any of the affected modules.
        Uses test_mapping.json from Phase 1.
        """
        impacted_tests = set()

        for test_path, covered_modules in self.test_mapping.items():
            for covered in covered_modules:
                if covered in all_affected_modules:
                    impacted_tests.add(test_path)
                    break

        return sorted(impacted_tests)

    # ── Symbol Level Impact ──────────────────────────────────────

    def _compute_symbol_impact(self, changed_module: str) -> dict:
        """
        Use function_index and class_index to find which specific
        symbols in affected modules reference the changed symbols.
        """
        changed_functions = set(self.pr_analysis.get("changed_functions", []))
        changed_classes = set(self.pr_analysis.get("changed_classes", []))

        if not changed_functions and not changed_classes:
            return {}

        symbol_impact = {}

        # Find affected functions in function_index
        for key, info in self.function_index.items():
            if info["module"] == changed_module:
                continue
            if info["name"] in changed_functions:
                module = info["module"]
                symbol_impact.setdefault(module, [])
                symbol_impact[module].append({
                    "symbol": info["qualname"],
                    "type": info["type"]
                })

        # Find affected classes in class_index
        for key, info in self.class_index.items():
            if info["module"] == changed_module:
                continue
            if info["name"] in changed_classes:
                module = info["module"]
                symbol_impact.setdefault(module, [])
                symbol_impact[module].append({
                    "symbol": info["name"],
                    "type": "class"
                })

        return symbol_impact

    # ── Main Analysis ────────────────────────────────────────────

    def analyze(self) -> dict:
        """
        Full Phase 4 analysis.
        Reads PR analysis + dependency graph and produces rich impact report.
        """
        self._load_all()

        changed_modules = self.pr_analysis.get("changed_modules", [])

        if not changed_modules:
            return {
                "changed_modules": [],
                "impact_summary": {
                    "total_affected": 0,
                    "direct_impact": 0,
                    "indirect_impact": 0,
                    "blast_radius": "none"
                },
                "affected_modules": [],
                "impacted_tests": [],
                "symbol_impact": {}
            }

        # Collect impact across all changed modules
        all_affected = {}  # module -> {depth, paths, changed_by}

        for changed_module in changed_modules:
            depth_map = self._bfs_with_depth(changed_module)

            for affected_module, depth in depth_map.items():
                if affected_module not in all_affected:
                    all_affected[affected_module] = {
                        "min_depth": depth,
                        "changed_by": []
                    }
                else:
                    all_affected[affected_module]["min_depth"] = min(
                        all_affected[affected_module]["min_depth"],
                        depth
                    )
                all_affected[affected_module]["changed_by"].append(changed_module)

        # Build rich affected module entries
        affected_modules_detail = []
        direct_count = 0
        indirect_count = 0

        for affected_module, info in sorted(all_affected.items()):
            depth = info["min_depth"]
            primary_changed = info["changed_by"][0]
            change_type = self._classify_change_type(primary_changed)
            confidence = self._compute_confidence(
                affected_module, depth, primary_changed, change_type
            )
            path = self._find_dependency_path(primary_changed, affected_module)
            impact_type = "direct" if depth == 1 else "indirect"

            if impact_type == "direct":
                direct_count += 1
            else:
                indirect_count += 1

            # Get metrics for affected module
            module_metrics = self.metrics.get(affected_module, {})

            affected_modules_detail.append({
                "module": affected_module,
                "impact_type": impact_type,
                "depth": depth,
                "confidence": confidence,
                "change_type": change_type,
                "reason": f"imports {primary_changed}" if depth == 1
                          else f"transitively depends on {primary_changed}",
                "path": path,
                "changed_by": sorted(set(info["changed_by"])),
                "fan_in": module_metrics.get("fan_in", 0),
                "fan_out": module_metrics.get("fan_out", 0)
            })

        # Sort by depth then confidence
        affected_modules_detail.sort(
            key=lambda x: (x["depth"], -x["confidence"])
        )

        # Compute blast radius
        primary_change_type = self._classify_change_type(changed_modules[0])
        blast_radius = self._compute_blast_radius(
            len(all_affected), direct_count, primary_change_type
        )

        # Find impacted tests
        all_affected_module_names = list(all_affected.keys()) + changed_modules
        impacted_tests = self._find_impacted_tests(all_affected_module_names)

        # Symbol level impact
        symbol_impact = {}
        for changed_module in changed_modules:
            symbol_impact.update(self._compute_symbol_impact(changed_module))

        # Public API change detection
        public_api_changed = any(
            self._is_public_api_change(m) for m in changed_modules
        )

        result = {
            "changed_modules": sorted(changed_modules),
            "impact_summary": {
                "total_affected": len(all_affected),
                "direct_impact": direct_count,
                "indirect_impact": indirect_count,
                "blast_radius": blast_radius,
                "public_api_changed": public_api_changed,
                "change_type": primary_change_type
            },
            "affected_modules": affected_modules_detail,
            "impacted_tests": impacted_tests,
            "symbol_impact": symbol_impact
        }

        return result

    def save(self, output_path: str = "storage/impact_analysis.json") -> dict:
        """Run analysis and save results."""
        result = self.analyze()
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w") as f:
            json.dump(result, f, indent=2)

        print(f"Saved impact analysis -> {output_path}")
        return result
