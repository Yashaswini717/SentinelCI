import json
import os
import requests
import shutil
import pathlib
from repository_analysis.repository_parser import RepositoryParser
from repository_analysis.dependency_graph import DependencyGraphBuilder


def fetch_repo_tree(github_url: str) -> list:
    parts = github_url.rstrip("/").split("/")
    owner = parts[-2]
    repo = parts[-1]

    api_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
    print(f"Fetching file tree for {owner}/{repo} from GitHub API ...")

    response = requests.get(api_url)

    if response.status_code != 200:
        raise Exception(f"GitHub API error: {response.status_code} - {response.json().get('message')}")

    tree = response.json().get("tree", [])
    print(f"Fetched {len(tree)} items from repo\n")
    return tree


def fetch_file_contents(github_url: str, tree: list, dest_folder: str = "datasets/virtual_repo") -> str:
    parts = github_url.rstrip("/").split("/")
    owner = parts[-2]
    repo = parts[-1]

    skip_dirs = {
        "venv", ".venv", "__pycache__", ".git",
        ".tox", "node_modules", "dist", "build", ".eggs",
        "docs", "tests"
    }

    if os.path.exists(dest_folder):
        shutil.rmtree(dest_folder)

    print("Downloading Python file contents for import analysis...")

    for item in tree:
        path = item.get("path", "")

        if not path.endswith(".py"):
            continue

        path_parts = path.split("/")
        if any(part in skip_dirs for part in path_parts):
            continue

        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{path}"
        response = requests.get(raw_url)

        full_path = pathlib.Path(dest_folder) / path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        if response.status_code == 200:
            full_path.write_text(response.text, encoding="utf-8")
        else:
            full_path.touch()

    print(f"Files downloaded to {dest_folder}\n")
    return dest_folder


def save_traversal_results(changed_module: str, affected: list,
                           output_path: str = "storage/traversal_results.json"):
    result = {
        "changed_module": changed_module,
        "affected_modules": affected,
        "total_affected": len(affected)
    }

    output = pathlib.Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Saved traversal results → {output_path}")
    return result


def print_parser_results(result: dict):
    print("=" * 50)
    print(f"  Modules found : {len(result['modules'])}")
    print(f"  Tests found   : {len(result['tests'])}")
    print("=" * 50)

    print("\nModules:")
    if result["modules"]:
        for m in result["modules"]:
            print(f"  {m['name']}  →  {m['path']}")
    else:
        print("  No Python modules found.")

    print("\nTests:")
    if result["tests"]:
        for t in result["tests"]:
            print(f"  {t['name']}  →  {t['path']}")
    else:
        print("  No test files found.")


def print_graph_results(graph: dict):
    print("\n" + "=" * 50)
    print("  DEPENDENCY GRAPH")
    print("=" * 50)

    has_deps = False
    for module, deps in graph.items():
        if deps:
            has_deps = True
            print(f"\n  {module}")
            for dep in deps:
                print(f"    └→  {dep}")

    if not has_deps:
        print("\n  No cross-module dependencies detected.")


def print_traversal_results(changed_module: str, affected: list):
    print("\n" + "=" * 50)
    print("  GRAPH TRAVERSAL")
    print("=" * 50)
    print(f"\n  Changed module  : {changed_module}")
    print(f"  Affected modules: {len(affected)}")
    print()

    if affected:
        for m in affected:
            print(f"    → {m}")
    else:
        print("    No modules affected.")


if __name__ == "__main__":

    GITHUB_URL = "https://github.com/psf/requests"

    print("\n" + "=" * 50)
    print("  PHASE 1: Repository Parser")
    print("=" * 50 + "\n")

    tree = fetch_repo_tree(GITHUB_URL)
    repo_path = fetch_file_contents(GITHUB_URL, tree)

    parser = RepositoryParser(repo_path=repo_path)
    result = parser.save()
    print_parser_results(result)

    print("\n" + "=" * 50)
    print("  PHASE 2: Dependency Graph")
    print("=" * 50 + "\n")

    graph_builder = DependencyGraphBuilder(
        repo_structure_path="storage/repo_structure.json",
        virtual_repo_path=repo_path
    )
    graph = graph_builder.save()
    print_graph_results(graph)

    print("\n" + "=" * 50)
    print("  PHASE 2: Graph Traversal")
    print("=" * 50 + "\n")

    CHANGED_MODULE = "src/requests/compat"

    affected = graph_builder.find_affected_modules(CHANGED_MODULE, graph)

    print_traversal_results(CHANGED_MODULE, affected)

    save_traversal_results(CHANGED_MODULE, affected)

    if os.path.exists("datasets/virtual_repo"):
        shutil.rmtree("datasets/virtual_repo")
        print("\nCleaned up datasets/virtual_repo")

    print("\n" + "=" * 50)
    print("  ALL PHASES COMPLETE")
    print("=" * 50)