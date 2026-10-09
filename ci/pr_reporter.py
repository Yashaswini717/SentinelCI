import json
import os
import requests
from pathlib import Path

# Hidden marker used to find (and update) SentinelCI's own comment on a PR
COMMENT_MARKER = "<!-- sentinelci-report -->"

# GitHub rejects comment bodies longer than 65536 characters
MAX_COMMENT_LENGTH = 65000


class PRReporter:
    """
    Phase 9 - PR Reporter

    Posts a formatted summary comment to the GitHub PR
    with risk score, affected modules, selected tests,
    and merge recommendation.
    """

    def __init__(
        self,
        repo_owner: str,
        repo_name: str,
        pr_number: int,
        github_token: str = None
    ):
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.pr_number = pr_number
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")

    def _load_json(self, path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _risk_emoji(self, risk_level: str) -> str:
        return {
            "low": "🟢",
            "medium": "🟡",
            "high": "🔴",
            "critical": "🚨"
        }.get(risk_level, "⚪")

    def _status_emoji(self, pipeline_status: str) -> str:
        return {
            "ready": "✅",
            "warning": "⚠️",
            "blocked": "🚫"
        }.get(pipeline_status, "⚪")

    def _build_comment(self) -> str:
        """Build the full PR comment markdown."""
        ci_decision = self._load_json("storage/ci_decision.json")
        impact = self._load_json("storage/impact_analysis.json")
        pr_analysis = self._load_json("storage/pr_analysis.json")

        risk_score = ci_decision.get("risk_score", 0)
        risk_level = ci_decision.get("risk_level", "unknown")
        ci_action = ci_decision.get("ci_action", "unknown")
        pipeline_status = ci_decision.get("pipeline_status", "unknown")
        message = ci_decision.get("message", "")
        tests_to_run = ci_decision.get("tests_to_run", [])
        generated_tests = ci_decision.get("generated_tests", [])
        coverage_gaps = ci_decision.get("coverage_gaps", [])
        top_drivers = ci_decision.get("top_drivers", [])
        test_commands = ci_decision.get("test_commands", [])

        affected_modules = impact.get("affected_modules", [])
        changed_modules = pr_analysis.get("changed_modules", [])
        changed_functions = pr_analysis.get("changed_functions", [])

        risk_emoji = self._risk_emoji(risk_level)
        status_emoji = self._status_emoji(pipeline_status)

        lines = [
            "## 🤖 SentinelCI Analysis Report",
            "",
            f"### {risk_emoji} Risk Assessment",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Risk Score | **{risk_score} / 100** |",
            f"| Risk Level | **{risk_level.upper()}** |",
            f"| Pipeline Status | {status_emoji} **{pipeline_status.upper()}** |",
            f"| Action | `{ci_action}` |",
            "",
            f"_{message}_",
            "",
        ]

        # Changed modules
        if changed_modules:
            lines.append("### 📝 Changed Modules")
            for m in changed_modules:
                lines.append(f"- `{m}`")
            lines.append("")

        # Changed functions
        if changed_functions:
            lines.append("### 🔧 Changed Functions")
            for f in changed_functions:
                lines.append(f"- `{f}`")
            lines.append("")

        # Affected modules
        if affected_modules:
            lines.append("### 💥 Blast Radius")
            summary = impact.get("impact_summary", {})
            lines.append(
                f"**{summary.get('total_affected', 0)}** modules affected "
                f"({summary.get('direct_impact', 0)} direct, "
                f"{summary.get('indirect_impact', 0)} indirect)"
            )
            lines.append("")
            for m in affected_modules[:5]:
                impact_type = m.get("impact_type", "unknown")
                depth = m.get("depth", 0)
                confidence = m.get("confidence", 0)
                lines.append(
                    f"- `{m.get('module')}` "
                    f"— {impact_type}, depth {depth}, "
                    f"confidence {confidence}"
                )
            if len(affected_modules) > 5:
                lines.append(f"- _...and {len(affected_modules) - 5} more_")
            lines.append("")

        # Risk drivers
        if top_drivers:
            lines.append("### ⚠️ Top Risk Drivers")
            for d in top_drivers:
                lines.append(f"- {d}")
            lines.append("")

        # Tests to run
        if tests_to_run:
            lines.append("### 🧪 Selected Tests")
            for t in tests_to_run:
                lines.append(f"- `{t}`")
            lines.append("")

        # Generated tests
        if generated_tests:
            lines.append("### 🤖 Generated Tests")
            for t in generated_tests:
                lines.append(f"- `{t}` _(auto-generated for coverage gap)_")
            lines.append("")

        # Coverage gaps
        if coverage_gaps:
            lines.append("### 🕳️ Coverage Gaps")
            for g in coverage_gaps:
                lines.append(f"- `{g}` — no existing tests found")
            lines.append("")

        # Test commands
        if test_commands:
            lines.append("### 💻 Test Commands")
            lines.append("```bash")
            for cmd in test_commands:
                lines.append(cmd)
            lines.append("```")
            lines.append("")

        # Test execution results (written by the CI workflow, if tests ran)
        test_execution = self._load_json("storage/test_execution.json")
        results = test_execution.get("results", [])
        if results:
            passed = sum(1 for r in results if r.get("passed"))
            lines.append("### ▶️ Test Execution")
            lines.append(f"**{passed} / {len(results)}** test commands passed")
            lines.append("")
            for r in results:
                mark = "✅" if r.get("passed") else "❌"
                lines.append(f"- {mark} `{r.get('command')}`")
            lines.append("")

        run_url = self._run_url()

        lines.append("---")
        if run_url:
            lines.append(
                f"Generated by SentinelCI · [workflow run & full reports]({run_url})"
            )
        else:
            lines.append("Generated by SentinelCI")

        body = COMMENT_MARKER + "\n" + "\n".join(lines)

        if len(body) > MAX_COMMENT_LENGTH:
            notice = "\n\n_…report truncated. See the workflow artifacts for the full report._"
            body = body[:MAX_COMMENT_LENGTH - len(notice)] + notice

        return body

    def _run_url(self) -> str:
        """Link to the current GitHub Actions run, when running in CI."""
        server = os.getenv("GITHUB_SERVER_URL")
        repo = os.getenv("GITHUB_REPOSITORY")
        run_id = os.getenv("GITHUB_RUN_ID")
        if server and repo and run_id:
            return f"{server}/{repo}/actions/runs/{run_id}"
        return ""

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _find_existing_comment(self) -> int | None:
        """Return the id of a previous SentinelCI bot comment on this PR, if any."""
        url = (
            f"https://api.github.com/repos/{self.repo_owner}/"
            f"{self.repo_name}/issues/{self.pr_number}/comments"
        )
        params = {"per_page": 100}

        while url:
            response = requests.get(
                url, headers=self._headers(), params=params, timeout=30
            )
            if response.status_code != 200:
                return None

            for comment in response.json():
                user = comment.get("user") or {}
                if (
                    COMMENT_MARKER in (comment.get("body") or "")
                    and user.get("type") == "Bot"
                ):
                    return comment.get("id")

            # Follow pagination; the "next" URL already carries the query params
            url = response.links.get("next", {}).get("url")
            params = None

        return None

    def post_comment(self) -> bool:
        """
        Post the analysis comment to the GitHub PR.

        Updates the previous SentinelCI comment if one exists, so pushing
        new commits to a PR doesn't stack up duplicate reports.
        """
        if not self.github_token:
            print("No GITHUB_TOKEN found — skipping PR comment.")
            print("Set GITHUB_TOKEN env variable to enable PR comments.")
            return False

        comment_body = self._build_comment()
        existing_id = self._find_existing_comment()

        if existing_id:
            url = (
                f"https://api.github.com/repos/{self.repo_owner}/"
                f"{self.repo_name}/issues/comments/{existing_id}"
            )
            response = requests.patch(
                url, headers=self._headers(),
                json={"body": comment_body}, timeout=30
            )
            expected_status = 200
        else:
            url = (
                f"https://api.github.com/repos/{self.repo_owner}/"
                f"{self.repo_name}/issues/{self.pr_number}/comments"
            )
            response = requests.post(
                url, headers=self._headers(),
                json={"body": comment_body}, timeout=30
            )
            expected_status = 201

        if response.status_code == expected_status:
            comment_url = response.json().get("html_url", "")
            action = "Updated" if existing_id else "Posted"
            print(f"{action} PR comment -> {comment_url}")
            return True

        # Surface the failure as a GitHub Actions warning so it isn't silent
        print(f"::warning::SentinelCI failed to post PR comment (HTTP {response.status_code})")
        print(response.text)
        if response.status_code in (401, 403, 404):
            print(
                "Hint: the token needs 'pull-requests: write' permission. "
                "Check the 'permissions:' block in the workflow. PRs opened "
                "from forks always get a read-only token."
            )
        return False

    def save_report(
        self, output_path: str = "storage/pr_report.md"
    ) -> str:
        """Save the comment as a markdown file (useful without GitHub token)."""
        comment = self._build_comment()
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w", encoding="utf-8") as f:
            f.write(comment)

        print(f"Saved PR report -> {output_path}")
        return comment