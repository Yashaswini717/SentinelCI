import ast
import json
import os
from collections import defaultdict
from pathlib import Path


class RepositoryParser:
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()

    def _is_test_file(self, path: Path) -> bool:
        filename = path.name
        return (
            filename.startswith("test_")
            or filename.endswith("_test.py")
            or any(part in {"test", "tests"} for part in path.parts)
        )

    def _should_skip(self, path: Path) -> bool:
        skip_dirs = {
            "venv", ".venv", "__pycache__", ".git",
            ".tox", "node_modules", "dist", "build", ".eggs",
            "docs"
        }
        return any(part in skip_dirs for part in path.parts)

    def _is_init_file(self, filename: str) -> bool:
        return filename == "__init__.py"

    def _get_module_key(self, relative_path: str) -> str:
        return relative_path.replace("\\", "/").replace(".py", "")

    def _read_source(self, file_path: Path) -> str:
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return file_path.read_text(encoding="utf-8", errors="ignore")

    def _parse_ast(self, source: str):
        try:
            return ast.parse(source)
        except SyntaxError:
            return None

    def _extract_imports(self, source: str) -> list:
        tree = self._parse_ast(source)
        if tree is None:
            return []

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)

        return sorted(set(imports))

    def _extract_symbols(self, source: str) -> dict:
        tree = self._parse_ast(source)
        if tree is None:
            return {
                "functions": [],
                "classes": [],
                "methods": [],
                "class_methods": {}
            }

        functions = []
        classes = []
        methods = []
        class_methods = {}

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(node.name)
            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)
                method_names = []
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        qualified_name = f"{node.name}.{child.name}"
                        method_names.append(child.name)
                        methods.append(qualified_name)
                class_methods[node.name] = sorted(method_names)

        return {
            "functions": sorted(functions),
            "classes": sorted(classes),
            "methods": sorted(methods),
            "class_methods": class_methods
        }

    def _match_import_to_module(self, import_name: str, file_map: dict) -> str | None:
        normalized = import_name.replace(".", "/")

        if normalized in file_map:
            return normalized

        for module_key in file_map:
            if module_key == normalized or module_key.endswith(f"/{normalized}"):
                return module_key

        return None

    def _build_test_mapping(self, tests: list, modules: list, file_map: dict) -> dict:
        modules_by_basename = defaultdict(set)
        for module in modules:
            modules_by_basename[Path(module["path"]).stem].add(module["name"])

        mapping = {}

        for test in tests:
            related_modules = set()
            basename = Path(test["path"]).stem
            candidates = {basename}

            if basename.startswith("test_"):
                candidates.add(basename[len("test_"):])

            if basename.endswith("_test"):
                candidates.add(basename[:-len("_test")])

            for candidate in candidates:
                if not candidate:
                    continue

                normalized = candidate.replace("-", "_")
                related_modules.update(modules_by_basename.get(normalized, set()))

                for module_key in file_map:
                    if module_key == normalized or module_key.endswith(f"/{normalized}"):
                        related_modules.add(module_key)

            for import_name in test.get("imports", []):
                matched = self._match_import_to_module(import_name, file_map)
                if matched:
                    related_modules.add(matched)

            mapping[test["path"]] = sorted(related_modules)

        return mapping

    def _build_function_index(self, modules: list) -> dict:
        function_index = {}

        for module in modules:
            for function_name in module["functions"]:
                key = f"{module['name']}::{function_name}"
                function_index[key] = {
                    "module": module["name"],
                    "path": module["path"],
                    "name": function_name,
                    "qualname": function_name,
                    "type": "function"
                }

            for method_name in module["methods"]:
                class_name, method = method_name.split(".", 1)
                key = f"{module['name']}::{method_name}"
                function_index[key] = {
                    "module": module["name"],
                    "path": module["path"],
                    "name": method,
                    "qualname": method_name,
                    "class": class_name,
                    "type": "method"
                }

        return function_index

    def _build_class_index(self, modules: list, class_methods_by_module: dict) -> dict:
        class_index = {}

        for module in modules:
            module_classes = class_methods_by_module.get(module["name"], {})
            for class_name in module["classes"]:
                key = f"{module['name']}::{class_name}"
                class_index[key] = {
                    "module": module["name"],
                    "path": module["path"],
                    "name": class_name,
                    "methods": module_classes.get(class_name, [])
                }

        return class_index

    def parse(self) -> dict:
        modules = []
        tests = []
        file_map = {}
        test_file_map = {}
        class_methods_by_module = {}

        for root, dirs, files in os.walk(self.repo_path):
            current_path = Path(root)
            dirs[:] = [d for d in dirs if not self._should_skip(current_path / d)]

            for filename in files:
                if not filename.endswith(".py"):
                    continue

                full_path = current_path / filename
                if self._should_skip(full_path):
                    continue

                if self._is_init_file(filename):
                    continue

                relative_path = str(full_path.relative_to(self.repo_path)).replace("\\", "/")
                module_key = self._get_module_key(relative_path)

                source = self._read_source(full_path)
                symbols = self._extract_symbols(source)
                imports = self._extract_imports(source)
                class_methods_by_module[module_key] = symbols["class_methods"]

                entry = {
                    "name": module_key,
                    "path": relative_path,
                    "functions": symbols["functions"],
                    "classes": symbols["classes"],
                    "methods": symbols["methods"]
                }

                if self._is_test_file(Path(relative_path)):
                    entry["imports"] = imports
                    tests.append(entry)
                    test_file_map[module_key] = relative_path
                else:
                    file_map[module_key] = relative_path
                    modules.append(entry)

        test_mapping = self._build_test_mapping(tests, modules, file_map)
        function_index = self._build_function_index(modules)
        class_index = self._build_class_index(modules, class_methods_by_module)

        return {
            "modules": sorted(modules, key=lambda x: x["name"]),
            "tests": sorted(tests, key=lambda x: x["name"]),
            "file_map": file_map,
            "test_file_map": test_file_map,
            "test_mapping": test_mapping,
            "function_index": function_index,
            "class_index": class_index
        }

    def save(self, output_path: str = "storage/repo_structure.json") -> dict:
        result = self.parse()
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w") as f:
            json.dump({
                "modules": result["modules"],
                "tests": result["tests"],
                "file_map": result["file_map"],
                "test_file_map": result["test_file_map"]
            }, f, indent=2)

        with open(output.parent / "function_index.json", "w") as f:
            json.dump(result["function_index"], f, indent=2)

        with open(output.parent / "class_index.json", "w") as f:
            json.dump(result["class_index"], f, indent=2)

        with open(output.parent / "test_mapping.json", "w") as f:
            json.dump(result["test_mapping"], f, indent=2)

        print(f"Saved repo structure -> {output_path}")
        print("Saved function index -> storage/function_index.json")
        print("Saved class index -> storage/class_index.json")
        print("Saved test mapping -> storage/test_mapping.json")
        return result
