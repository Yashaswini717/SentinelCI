from utils.github_api import github_get, github_get_paginated


class PRFetcher:

    def __init__(self, repo_owner: str, repo_name: str, pr_number: int):
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.pr_number = pr_number

    def fetch_pr_info(self) -> dict:
        """
        Fetch PR metadata: head commit sha and the repo it lives in
        (which differs from the base repo for PRs opened from forks).
        """
        url = f"/repos/{self.repo_owner}/{self.repo_name}/pulls/{self.pr_number}"
        data = github_get(url).json()

        head = data.get("head") or {}
        head_repo = head.get("repo") or {}

        return {
            "head_sha": head.get("sha"),
            # head.repo is null when the fork was deleted - fall back to base
            "head_owner": (head_repo.get("owner") or {}).get("login", self.repo_owner),
            "head_repo": head_repo.get("name", self.repo_name),
            "state": data.get("state")
        }

    def fetch_pr_files(self) -> tuple[list[str], dict[str, str], dict[str, int]]:
        url = f"/repos/{self.repo_owner}/{self.repo_name}/pulls/{self.pr_number}/files"

        # Paginate - the API returns only 30 files per page by default
        data = github_get_paginated(url)

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
