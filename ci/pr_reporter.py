import json
import os
import requests
from pathlib import Path


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

        lines.append("---")
        lines.append("Generated by SentinelCI")

        return "\n".join(lines)

    def post_comment(self) -> bool:
        """Post the analysis comment to the GitHub PR."""
        if not self.github_token:
            print("No GITHUB_TOKEN found — skipping PR comment.")
            print("Set GITHUB_TOKEN env variable to enable PR comments.")
            return False

        comment_body = self._build_comment()

        url = (
            f"https://api.github.com/repos/{self.repo_owner}/"
            f"{self.repo_name}/issues/{self.pr_number}/comments"
        )

        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json"
        }

        response = requests.post(
            url,
            headers=headers,
            json={"body": comment_body},
            timeout=30
        )

        if response.status_code == 201:
            comment_url = response.json().get("html_url", "")
            print(f"Posted PR comment -> {comment_url}")
            return True
        else:
            print(f"Failed to post comment: {response.status_code}")
            print(response.text)
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