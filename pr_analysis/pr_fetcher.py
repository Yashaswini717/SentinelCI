import requests


class PRFetcher:

    def __init__(self, repo_owner: str, repo_name: str, pr_number: int):
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.pr_number = pr_number

    def fetch_pr_files(self) -> tuple[list[str], dict[str, str], dict[str, int]]:
        url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/pulls/{self.pr_number}/files"

        response = requests.get(url)

        if response.status_code != 200:
            raise Exception(
                f"GitHub API error: {response.status_code} {response.text}"
            )

        data = response.json()

        changed_files = []
        patches = {}
        metrics = {
            "files_changed": 0,
            "lines_added": 0,
            "lines_deleted": 0
        }

        for file in data:
            filename = file.get("filename")
            patch = file.get("patch", "")

            changed_files.append(filename)
            patches[filename] = patch
            metrics["lines_added"] += file.get("additions", 0)
            metrics["lines_deleted"] += file.get("deletions", 0)

        metrics["files_changed"] = len(changed_files)

        return changed_files, patches, metrics
