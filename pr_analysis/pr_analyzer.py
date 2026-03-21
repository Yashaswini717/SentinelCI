import json
from pathlib import Path

from pr_analysis.pr_fetcher import PRFetcher
from pr_analysis.diff_parser import DiffParser


class PRAnalyzer:

    def __init__(
        self,
        repo_owner,
        repo_name,
        pr_number,
        repo_structure_path="storage/repo_structure.json"
    ):
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.pr_number = pr_number
        self.repo_structure_path = Path(repo_structure_path)

    def load_repo_structure(self):

        with open(self.repo_structure_path, "r") as f:
            return json.load(f)

    def map_files_to_modules(self, changed_files, file_map):

        modules = []

        for module_key, path in file_map.items():

            if path in changed_files:
                modules.append(module_key)

        return modules

    def analyze(self):

        fetcher = PRFetcher(self.repo_owner, self.repo_name, self.pr_number)

        changed_files, patches, pr_metrics = fetcher.fetch_pr_files()

        parser = DiffParser()

        changed_functions = set()
        changed_classes = set()
        modified_symbols = set()
        diff_metrics = {
            "lines_added": 0,
            "lines_deleted": 0
        }

        for file, patch in patches.items():

            analysis = parser.analyze_patch(patch)

            changed_functions.update(analysis["changed_functions"])
            changed_classes.update(analysis["changed_classes"])
            modified_symbols.update(analysis["modified_symbols"])
            diff_metrics["lines_added"] += analysis["lines_added"]
            diff_metrics["lines_deleted"] += analysis["lines_deleted"]

        repo_structure = self.load_repo_structure()

        changed_modules = self.map_files_to_modules(
            changed_files,
            repo_structure["file_map"]
        )

        result = {
            "changed_files": changed_files,
            "changed_modules": list(set(changed_modules)),
            "changed_functions": sorted(changed_functions),
            "changed_classes": sorted(changed_classes),
            "modified_symbols": sorted(modified_symbols),
            "change_metrics": {
                "files_changed": pr_metrics["files_changed"],
                "lines_added": pr_metrics["lines_added"],
                "lines_deleted": pr_metrics["lines_deleted"],
                "patch_lines_added": diff_metrics["lines_added"],
                "patch_lines_deleted": diff_metrics["lines_deleted"]
            }
        }

        return result

    def save(self, output_path="storage/pr_analysis.json"):

        result = self.analyze()

        output = Path(output_path)

        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w") as f:
            json.dump(result, f, indent=2)

        print(f"Saved PR analysis -> {output_path}")

        return result
