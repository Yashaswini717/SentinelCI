import os
import json
from pathlib import Path


class RepositoryParser:
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()

    def _is_test_file(self, filename: str) -> bool:
        return filename.startswith("test_") or filename.endswith("_test.py")

    def _should_skip(self, path: Path) -> bool:
        skip_dirs = {
            "venv", ".venv", "__pycache__", ".git",
            ".tox", "node_modules", "dist", "build", ".eggs",
            "docs", "tests"
        }
        return any(part in skip_dirs for part in path.parts)

    def _is_init_file(self, filename: str) -> bool:
        return filename == "__init__.py"

    def _get_module_key(self, relative_path: str) -> str:
        return relative_path.replace("\\", "/").replace(".py", "")

    def parse(self) -> dict:
        modules = []
        tests = []
        file_map = {}

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

                file_map[module_key] = relative_path

                entry = {
                    "name": module_key,
                    "path": relative_path
                }

                if self._is_test_file(filename):
                    tests.append(entry)
                else:
                    modules.append(entry)

        return {
            "modules": sorted(modules, key=lambda x: x["name"]),
            "tests": sorted(tests, key=lambda x: x["name"]),
            "file_map": file_map
        }

    def save(self, output_path: str = "storage/repo_structure.json") -> dict:
        result = self.parse()
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w") as f:
            json.dump(result, f, indent=2)

        print(f"Saved repo structure → {output_path}")
        return result