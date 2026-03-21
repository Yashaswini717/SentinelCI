import ast
import json
from collections import deque
from pathlib import Path


class DependencyGraphBuilder:
    def __init__(self, repo_structure_path: str, virtual_repo_path: str):
        self.repo_structure_path = Path(repo_structure_path)
        self.virtual_repo_path = Path(virtual_repo_path)
        self.graph = {}
        self.metrics = {}

    def _should_skip(self, path: Path) -> bool:
        skip_dirs = {
            "venv", ".venv", "__pycache__", ".git",
            ".tox", "node_modules", "dist", "build", ".eggs",
            "docs", "tests"
        }
        return any(part in skip_dirs for part in path.parts)

    def _load_repo_structure(self) -> dict:
        with open(self.repo_structure_path, "r") as f:
            return json.load(f)

    def _module_to_package(self, module_key: str) -> str:
        parts = module_key.split("/")
        return ".".join(parts[:-1]) if len(parts) > 1 else ""

    def _normalize_module_path(self, dotted_path: str) -> str:
        return dotted_path.replace(".", "/")

    def _resolve_relative_module(self, module_key: str, level: int, module_name: str | None) -> str:
        package = self._module_to_package(module_key)
        package_parts = [part for part in package.split(".") if part]

        if level > 0:
            trimmed_parts = package_parts[:-level + 1] if level > 1 else package_parts
        else:
            trimmed_parts = package_parts

        if module_name:
            trimmed_parts.extend([part for part in module_name.split(".") if part])

        return "/".join(trimmed_parts)

    def _extract_imports(self, file_path: Path, module_key: str) -> list:
        imports = []
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(self._normalize_module_path(alias.name))
                elif isinstance(node, ast.ImportFrom):
                    base_module = self._resolve_relative_module(
                        module_key,
                        getattr(node, "level", 0),
                        node.module
                    )

                    if base_module:
                        imports.append(base_module)

                    for alias in node.names:
                        if alias.name == "*":
                            continue

                        alias_module = "/".join(part for part in [base_module, alias.name] if part)
                        if alias_module:
                            imports.append(alias_module)
        except Exception:
            pass

        return sorted(set(imports))

    def _resolve_import(self, raw_import: str, file_map: dict) -> str | None:
        """Match a raw import string to a known module in the file_map."""
        normalized = self._normalize_module_path(raw_import)

        if normalized in file_map:
            return normalized

        package_init = f"{normalized}/__init__"
        if package_init in file_map:
            return package_init

        for key in file_map:
            if key.endswith(normalized):
                return key

            if normalized.startswith(f"{key}/"):
                return key

        return None

    def _compute_metrics(self, graph: dict) -> dict:
        reverse_graph = {module: set() for module in graph}

        for module, deps in graph.items():
            for dep in deps:
                reverse_graph.setdefault(dep, set()).add(module)

        metrics = {}
        for module, deps in graph.items():
            metrics[module] = {
                "fan_in": len(reverse_graph.get(module, set())),
                "fan_out": len(deps),
                "module_depth": self._compute_module_depth(module, graph)
            }

        return metrics

    def _compute_module_depth(self, module: str, graph: dict) -> int:
        memo = {}

        def depth(node: str, trail: set) -> int:
            if node in memo:
                return memo[node]

            if node in trail:
                return 0

            deps = graph.get(node, [])
            if not deps:
                memo[node] = 0
                return 0

            trail = set(trail)
            trail.add(node)
            max_depth = 0

            for dep in deps:
                max_depth = max(max_depth, 1 + depth(dep, trail))

            memo[node] = max_depth
            return max_depth

        return depth(module, set())

    def _write_dot(self, graph: dict, output_path: Path):
        lines = ["digraph dependency_graph {"]

        for module in sorted(graph):
            deps = graph[module]
            if not deps:
                lines.append(f'  "{module}";')
                continue

            for dep in deps:
                lines.append(f'  "{module}" -> "{dep}";')

        lines.append("}")
        output_path.write_text("\n".join(lines), encoding="utf-8")

    def _write_png(self, dot_path: Path, png_path: Path):
        try:
            import graphviz  # type: ignore

            source = graphviz.Source(dot_path.read_text(encoding="utf-8"))
            rendered_path = Path(source.render(filename=png_path.stem, directory=str(png_path.parent), format="png", cleanup=True))
            if rendered_path != png_path and rendered_path.exists():
                rendered_path.replace(png_path)
            return True
        except Exception:
            return False

    def build(self) -> dict:
        """Build the dependency graph from the repo structure."""
        structure = self._load_repo_structure()
        file_map = structure.get("file_map", {})
        modules = structure.get("modules", [])

        # Filter out docs and tests from modules list
        modules = [
            m for m in modules
            if not self._should_skip(Path(m["path"]))
        ]

        print(f"Building dependency graph for {len(modules)} modules...")

        for module in modules:
            module_key = module["name"]
            module_path = module["path"]

            full_path = self.virtual_repo_path / module_path

            if not full_path.exists():
                self.graph[module_key] = []
                continue

            raw_imports = self._extract_imports(full_path, module_key)

            resolved = []
            for raw in raw_imports:
                matched = self._resolve_import(raw, file_map)
                if matched and matched != module_key:
                    resolved.append(matched)

            self.graph[module_key] = sorted(set(resolved))

        self.metrics = self._compute_metrics(self.graph)
        return self.graph

    def find_affected_modules(self, changed_module: str, graph: dict) -> list:
        """
        Given a changed module, traverse the graph and find
        ALL modules that directly or indirectly depend on it.
        Uses reverse BFS — finds who imports the changed module.
        """
        # Build reverse graph: "who imports X"
        reverse_graph = {}
        for module, deps in graph.items():
            for dep in deps:
                if dep not in reverse_graph:
                    reverse_graph[dep] = []
                reverse_graph[dep].append(module)

        # BFS from changed module
        visited = set()
        queue = deque([changed_module])

        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            for affected in reverse_graph.get(current, []):
                if affected not in visited:
                    queue.append(affected)

        # Remove the changed module itself from results
        visited.discard(changed_module)
        return sorted(list(visited))

    def analyze_change_impact(self, changed_modules: list[str], graph: dict | None = None) -> dict:
        graph = graph or self.graph or self.build()
        traversal_by_module = {}
        all_affected = set()

        for changed_module in sorted(set(changed_modules)):
            affected_modules = self.find_affected_modules(changed_module, graph)
            traversal_by_module[changed_module] = affected_modules
            all_affected.update(affected_modules)

        result = {
            "changed_modules": sorted(set(changed_modules)),
            "affected_modules": sorted(all_affected),
            "total_affected": len(all_affected),
            "traversal_by_module": traversal_by_module
        }

        if len(result["changed_modules"]) == 1:
            result["changed_module"] = result["changed_modules"][0]

        return result

    def save_traversal_results(
        self,
        changed_modules: list[str],
        graph: dict | None = None,
        output_path: str = "storage/traversal_results.json"
    ) -> dict:
        result = self.analyze_change_impact(changed_modules, graph)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w") as f:
            json.dump(result, f, indent=2)

        print(f"Saved traversal results -> {output_path}")
        return result

    def save(self, output_path: str = "storage/dependency_graph.json") -> dict:
        graph = self.build()
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        metrics_output = output.parent / "dependency_metrics.json"
        dot_output = output.parent / "dependency_graph.dot"
        png_output = output.parent / "dependency_graph.png"

        with open(output, "w") as f:
            json.dump(graph, f, indent=2)

        with open(metrics_output, "w") as f:
            json.dump(self.metrics, f, indent=2)

        self._write_dot(graph, dot_output)
        png_written = self._write_png(dot_output, png_output)

        print(f"Saved dependency graph -> {output_path}")
        print("Saved dependency metrics -> storage/dependency_metrics.json")
        print("Saved dependency graph visualization -> storage/dependency_graph.dot")
        if png_written:
            print("Saved dependency graph image -> storage/dependency_graph.png")
        else:
            print("Skipped PNG graph render (graphviz package or binary unavailable)")
        return graph
