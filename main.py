import os
import requests
import shutil
import pathlib

from repository_analysis.repository_parser import RepositoryParser
from repository_analysis.dependency_graph import DependencyGraphBuilder

from pr_analysis.pr_analyzer import PRAnalyzer


def ensure_runtime_directories():

    pathlib.Path("storage").mkdir(parents=True, exist_ok=True)
    pathlib.Path("datasets").mkdir(parents=True, exist_ok=True)


def fetch_repo_tree(github_url: str):

    parts = github_url.rstrip("/").split("/")
    owner = parts[-2]
    repo = parts[-1]

    api_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"

    print(f"Fetching file tree for {owner}/{repo} from GitHub API ...")

    response = requests.get(api_url)

    if response.status_code != 200:
        raise Exception(f"GitHub API error: {response.status_code}")

    tree = response.json().get("tree", [])

    print(f"Fetched {len(tree)} items from repo\n")

    return tree


def fetch_file_contents(github_url, tree, dest_folder="datasets/virtual_repo"):

    parts = github_url.rstrip("/").split("/")
    owner = parts[-2]
    repo = parts[-1]

    if os.path.exists(dest_folder):
        shutil.rmtree(dest_folder)

    pathlib.Path(dest_folder).mkdir(parents=True, exist_ok=True)

    for item in tree:

        path = item.get("path", "")

        if not path.endswith(".py"):
            continue

        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{path}"

        response = requests.get(raw_url)

        full_path = pathlib.Path(dest_folder) / path

        full_path.parent.mkdir(parents=True, exist_ok=True)

        if response.status_code == 200:
            full_path.write_text(response.text, encoding="utf-8")
        else:
            full_path.touch()

    return dest_folder


if __name__ == "__main__":

    GITHUB_URL = "https://github.com/HKUDS/CLI-Anything"

    ensure_runtime_directories()

    print("\n========== PHASE 1: Repository Parser ==========\n")

    tree = fetch_repo_tree(GITHUB_URL)

    repo_path = fetch_file_contents(GITHUB_URL, tree)

    parser = RepositoryParser(repo_path)

    repo_structure = parser.save()

    print("\n========== PHASE 2: Dependency Graph ==========\n")

    graph_builder = DependencyGraphBuilder(
        repo_structure_path="storage/repo_structure.json",
        virtual_repo_path=repo_path
    )

    graph = graph_builder.save()

    print("\n========== PHASE 3: Pull Request Analyzer ==========\n")

    REPO_OWNER = "HKUDS"
    REPO_NAME = "CLI-Anything"
    PR_NUMBER = 75

    pr_analyzer = PRAnalyzer(REPO_OWNER, REPO_NAME, PR_NUMBER)

    pr_result = pr_analyzer.save()

    print("\nChanged Files:")
    for f in pr_result["changed_files"]:
        print(" ", f)

    print("\nChanged Modules:")
    for m in pr_result["changed_modules"]:
        print(" ", m)

    print("\nChanged Functions:")
    for fn in pr_result["changed_functions"]:
        print(" ", fn)

    print("\nChanged Classes:")
    for cls in pr_result["changed_classes"]:
        print(" ", cls)

    print("\nModified Symbols:")
    for symbol in pr_result["modified_symbols"]:
        print(" ", symbol)

    print("\nChange Metrics:")
    for key, value in pr_result["change_metrics"].items():
        print(f"  {key}: {value}")

    print("\n========== PHASE 4: Change Impact Analysis ==========")

    traversal_result = graph_builder.save_traversal_results(
        changed_modules=pr_result["changed_modules"],
        graph=graph
    )

    print("\nAffected Modules:")
    for module in traversal_result["affected_modules"]:
        print(" ", module)

    print(f"\nTotal Affected: {traversal_result['total_affected']}")

    if os.path.exists("datasets/virtual_repo"):
        shutil.rmtree("datasets/virtual_repo")
