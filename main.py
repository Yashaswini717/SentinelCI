import json
import os
import requests
from repository_analysis.repository_parser import RepositoryParser


def fetch_repo_tree(github_url: str) -> list:
    """Fetch the full file tree from GitHub API without cloning."""
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


def build_virtual_repo(tree: list, dest_folder: str = "datasets/virtual_repo") -> str:
    """
    Build a virtual folder structure from GitHub API tree
    so RepositoryParser can walk it properly.
    Only creates empty .py files — no actual code downloaded.
    """
    import pathlib

    # Clean old virtual repo
    if os.path.exists(dest_folder):
        import shutil
        shutil.rmtree(dest_folder)

    skip_dirs = {"venv", ".venv", "__pycache__", ".git", ".tox", "node_modules", "dist", "build"}

    for item in tree:
        path = item.get("path", "")
        if not path.endswith(".py"):
            continue
        parts = path.split("/")
        if any(part in skip_dirs for part in parts):
            continue

        full_path = pathlib.Path(dest_folder) / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.touch()  # Create empty file

    print(f"Virtual repo built at {dest_folder}\n")
    return dest_folder


def print_results(result: dict):
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


if __name__ == "__main__":

    # ← Paste any public GitHub repo URL here
    GITHUB_URL = "https://github.com/Yashaswini717/research-analysis"

    # Step 1 — Fetch file tree from GitHub API
    tree = fetch_repo_tree(GITHUB_URL)

    # Step 2 — Build virtual repo structure locally (empty .py files only)
    repo_path = build_virtual_repo(tree)

    # Step 3 — Run the fixed RepositoryParser on it
    parser = RepositoryParser(repo_path=repo_path)
    result = parser.save()

    # Step 4 — Print results
    print_results(result)