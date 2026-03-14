import json
import ast
from pathlib import Path
from collections import deque


class DependencyGraphBuilder:
    def __init__(self, repo_structure_path: str, virtual_repo_path: str):
        self.repo_structure_path = Path(repo_structure_path)
        self.virtual_repo_path = Path(virtual_repo_path)
        self.graph = {}

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

    def _extract_imports(self, file_path: Path) -> list:
        """Parse a Python file using AST and extract all import statements."""
        imports = []
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)
        except Exception:
            pass

        return imports

    def _resolve_import(self, raw_import: str, file_map: dict) -> str | None:
        """Match a raw import string to a known module in the file_map."""
        normalized = raw_import.replace(".", "/")

        if normalized in file_map:
            return normalized

        for key in file_map:
            if key.endswith(normalized):
                return key

        return None

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

            raw_imports = self._extract_imports(full_path)

            resolved = []
            for raw in raw_imports:
                matched = self._resolve_import(raw, file_map)
                if matched and matched != module_key:
                    resolved.append(matched)

            self.graph[module_key] = sorted(set(resolved))

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

    def save(self, output_path: str = "storage/dependency_graph.json") -> dict:
        """Build and save the dependency graph to disk."""
        graph = self.build()
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w") as f:
            json.dump(graph, f, indent=2)

        print(f"Saved dependency graph → {output_path}")
        return graph