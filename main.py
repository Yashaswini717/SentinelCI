import json
import os
import requests
import shutil
import pathlib

from repository_analysis.repository_parser import RepositoryParser
from repository_analysis.dependency_graph import DependencyGraphBuilder
from pr_analysis.pr_analyzer import PRAnalyzer
from agents.change_impact_agent import ChangeImpactAgent
from agents.test_selection_agent import run_test_selection
from agents.test_generation_agent import run_test_generation

try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    pass


def get_runtime_config() -> dict:
    github_url = os.getenv("GITHUB_URL", "https://github.com/psf/requests")
    pr_owner = os.getenv("PR_OWNER", "psf")
    pr_repo = os.getenv("PR_REPO", "requests")

    pr_number_raw = os.getenv("PR_NUMBER", "6710")
    try:
        pr_number = int(pr_number_raw)
    except ValueError as e:
        raise ValueError(f"Invalid PR_NUMBER '{pr_number_raw}'. Expected an integer.") from e

    semantic_threshold_raw = os.getenv("SEMANTIC_SIMILARITY_THRESHOLD", "0.50")
    try:
        semantic_threshold = float(semantic_threshold_raw)
    except ValueError as e:
        raise ValueError(
            f"Invalid SEMANTIC_SIMILARITY_THRESHOLD '{semantic_threshold_raw}'. Expected a float."
        ) from e

    semantic_top_k_raw = os.getenv("SEMANTIC_TOP_K", "10")
    try:
        semantic_top_k = int(semantic_top_k_raw)
    except ValueError as e:
        raise ValueError(f"Invalid SEMANTIC_TOP_K '{semantic_top_k_raw}'. Expected an integer.") from e

    return {
        "github_url": github_url,
        "pr_owner": pr_owner,
        "pr_repo": pr_repo,
        "pr_number": pr_number,
        "semantic_threshold": semantic_threshold,
        "semantic_top_k": semantic_top_k
    }


def ensure_runtime_directories():
    pathlib.Path("storage").mkdir(parents=True, exist_ok=True)
    pathlib.Path("datasets").mkdir(parents=True, exist_ok=True)


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
        "docs"
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


def print_phase1_results(result: dict):
    print("=" * 55)
    print(f"  Modules found : {len(result['modules'])}")
    print(f"  Tests found   : {len(result['tests'])}")
    print("=" * 55)

    print("\nModules:")
    for m in result["modules"]:
        print(f"  {m['name']}  ->  {m['path']}")

    print("\nTests:")
    if result["tests"]:
        for t in result["tests"]:
            print(f"  {t['name']}  ->  {t['path']}")
    else:
        print("  No test files found.")


def print_phase2_results(graph: dict):
    print("\n" + "=" * 55)
    print("  DEPENDENCY GRAPH")
    print("=" * 55)

    has_deps = False
    for module, deps in graph.items():
        if deps:
            has_deps = True
            print(f"\n  {module}")
            for dep in deps:
                print(f"    ->  {dep}")

    if not has_deps:
        print("\n  No cross-module dependencies detected.")


def print_phase3_results(result: dict):
    print("\nChanged Files:")
    for f in result.get("changed_files", []):
        print(f"  {f}")

    print("\nChanged Modules:")
    for m in result.get("changed_modules", []):
        print(f"  {m}")

    print("\nChanged Functions:")
    for f in result.get("changed_functions", []):
        print(f"  {f}")

    print("\nChanged Classes:")
    for c in result.get("changed_classes", []):
        print(f"  {c}")

    print("\nModified Symbols:")
    for s in result.get("modified_symbols", []):
        print(f"  {s}")

    print("\nChange Metrics:")
    for k, v in result.get("change_metrics", {}).items():
        print(f"  {k}: {v}")


def print_phase4_results(result: dict):
    summary = result.get("impact_summary", {})

    print(f"\n  Blast Radius    : {summary.get('blast_radius', 'unknown').upper()}")
    print(f"  Total Affected  : {summary.get('total_affected', 0)}")
    print(f"  Direct Impact   : {summary.get('direct_impact', 0)}")
    print(f"  Indirect Impact : {summary.get('indirect_impact', 0)}")
    print(f"  Change Type     : {summary.get('change_type', 'unknown')}")
    print(f"  Public API      : {'YES' if summary.get('public_api_changed') else 'NO'}")

    affected = result.get("affected_modules", [])

    if affected:
        print("\n  Affected Modules:")
        for m in affected:
            print(f"\n    [{m['impact_type'].upper()} | depth {m['depth']} | confidence {m['confidence']}]")
            print(f"    Module  : {m['module']}")
            print(f"    Reason  : {m['reason']}")
            print(f"    Path    : {' -> '.join(m['path'])}")
            print(f"    Change  : {m['change_type']}")
    else:
        print("\n  No affected modules found.")

    tests = result.get("impacted_tests", [])

    print(f"\n  Impacted Tests ({len(tests)}):")
    if tests:
        for t in tests:
            print(f"    - {t}")
    else:
        print("    No test files mapped to affected modules.")


def print_phase5_results(result: dict):
    matches = result.get("semantic_related_modules", [])
    changed = result.get("changed_symbols", [])

    print(f"\n  Changed Symbols ({len(changed)}):")
    for s in changed:
        print(f"    - {s}")

    print(f"\n  Semantic Matches ({result.get('total_semantic_matches', 0)}):")
    if matches:
        for m in matches:
            print(f"\n    [{m['score']}] {m['module']}")
            print(f"    Reason  : {m['reason']}")
            print(f"    Matched : {m['matched_symbol']} ({m['match_type']})")
    else:
        print("    No semantic matches above threshold.")


def print_phase6_results(result: dict):
    tests = result.get("tests_to_run", [])
    summary = result.get("selection_summary", {})
    gaps = result.get("coverage_gaps", [])

    print(f"\n  Tests To Run ({len(tests)}):")
    for test in tests:
        print(f"    - {test}")

    print("\n  Selection Summary:")
    print(f"    total_tests    : {summary.get('total_tests', 0)}")
    print(f"    static_tests   : {summary.get('static_tests', 0)}")
    print(f"    semantic_tests : {summary.get('semantic_tests', 0)}")
    print(f"    fallback_tests : {summary.get('fallback_tests', 0)}")

    print(f"\n  Coverage Gaps ({len(gaps)}):")
    if gaps:
        for module in gaps:
            print(f"    - {module}")
    else:
        print("    None")


def print_phase7_results(result: dict):
    generated = result.get("generated_tests", [])
    summary = result.get("generation_summary", {})

    print(f"\n  Generated Tests ({len(generated)}):")
    if generated:
        for item in generated:
            print(f"    - {item.get('path', 'unknown_path')} [{item.get('target', 'unknown_target')}]")
    else:
        print("    None")

    print("\n  Generation Summary:")
    print(f"    created   : {summary.get('created', 0)}")
    print(f"    validated : {summary.get('validated', 0)}")
    print(f"    failed    : {summary.get('failed', 0)}")


if __name__ == "__main__":
    config = get_runtime_config()
    ensure_runtime_directories()

    github_url = config["github_url"]
    pr_owner = config["pr_owner"]
    pr_repo = config["pr_repo"]
    pr_number = config["pr_number"]
    semantic_threshold = config["semantic_threshold"]
    semantic_top_k = config["semantic_top_k"]

    print("Runtime configuration:")
    print(f"  Repo URL      : {github_url}")
    print(f"  PR            : {pr_owner}/{pr_repo}#{pr_number}")
    print(f"  Semantic conf : threshold={semantic_threshold}, top_k={semantic_top_k}")

    try:
        # Phase 1
        print("\n" + "=" * 55)
        print("  PHASE 1: Repository Parser")
        print("=" * 55 + "\n")

        tree = fetch_repo_tree(github_url)
        repo_path = fetch_file_contents(github_url, tree)

        parser = RepositoryParser(repo_path=repo_path)
        result = parser.save()
        print_phase1_results(result)

        # Phase 2
        print("\n" + "=" * 55)
        print("  PHASE 2: Dependency Graph")
        print("=" * 55 + "\n")

        graph_builder = DependencyGraphBuilder(
            repo_structure_path="storage/repo_structure.json",
            virtual_repo_path=repo_path
        )
        graph = graph_builder.save()
        print_phase2_results(graph)

        # Phase 3
        print("\n" + "=" * 55)
        print("  PHASE 3: Pull Request Analyzer")
        print("=" * 55 + "\n")

        pr_analyzer = PRAnalyzer(
            repo_owner=pr_owner,
            repo_name=pr_repo,
            pr_number=pr_number
        )
        pr_result = pr_analyzer.save()
        print_phase3_results(pr_result)

        # Phase 4
        print("\n" + "=" * 55)
        print("  PHASE 4: Change Impact Analysis")
        print("=" * 55 + "\n")

        impact_agent = ChangeImpactAgent()
        impact_result = impact_agent.save()
        print_phase4_results(impact_result)

        # Phase 5
        print("\n" + "=" * 55)
        print("  PHASE 5: Semantic Impact Analysis")
        print("=" * 55 + "\n")

        try:
            from semantic_analysis.semantic_impact_agent import SemanticImpactAgent

            semantic_agent = SemanticImpactAgent(
                virtual_repo_path=repo_path,
                similarity_threshold=semantic_threshold,
                top_k=semantic_top_k
            )
            semantic_result = semantic_agent.save(force_reindex=True)
            print_phase5_results(semantic_result)
        except BaseException as e:
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            print("Phase 5 skipped due to runtime error.")
            print(f"Reason: {type(e).__name__}: {e}")
            print("To fix: delete storage/semantic_index and ensure chromadb and OPENROUTER_API_KEY are set correctly.")

        # Phase 6 (FINAL STEP)
        print("\n" + "=" * 55)
        print("  PHASE 6: Test Selection Engine")
        print("=" * 55 + "\n")

        phase6_result = run_test_selection()
        print_phase6_results(phase6_result)
        
        print("\n" + "=" * 55)
        print("  PHASE 7: Test Generation Agent")
        print("=" * 55 + "\n")

        phase7_result = run_test_generation()
        print_phase7_results(phase7_result)

    finally:
        if os.path.exists("datasets/virtual_repo"):
            shutil.rmtree("datasets/virtual_repo")
            print("\nCleaned up datasets/virtual_repo")

        print("\n" + "=" * 55)
        print("  RUN COMPLETE")
        print("=" * 55)
