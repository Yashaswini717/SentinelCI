import json

import pytest

import ci.pr_reporter as pr_reporter
from ci.pr_reporter import COMMENT_MARKER, MAX_COMMENT_LENGTH, PRReporter


class FakeResponse:
    def __init__(self, status_code, data=None, links=None):
        self.status_code = status_code
        self._data = data
        self.links = links or {}
        self.text = json.dumps(data)

    def json(self):
        return self._data


@pytest.fixture
def api(monkeypatch):
    """Records GitHub API calls; tests queue up the GET responses."""
    calls = []
    get_responses = []

    def fake_get(url, **kwargs):
        calls.append(("GET", url))
        return get_responses.pop(0)

    def fake_post(url, **kwargs):
        calls.append(("POST", url))
        return FakeResponse(201, {"html_url": "posted"})

    def fake_patch(url, **kwargs):
        calls.append(("PATCH", url))
        return FakeResponse(200, {"html_url": "updated"})

    monkeypatch.setattr(pr_reporter.requests, "get", fake_get)
    monkeypatch.setattr(pr_reporter.requests, "post", fake_post)
    monkeypatch.setattr(pr_reporter.requests, "patch", fake_patch)
    return calls, get_responses


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "storage").mkdir()
    return tmp_path


@pytest.mark.smoke
def test_posts_new_comment_when_none_exists(api, in_tmp):
    calls, get_responses = api
    get_responses.append(FakeResponse(200, [
        {"id": 1, "body": COMMENT_MARKER, "user": {"type": "User"}}
    ]))

    assert PRReporter("o", "r", 5, "token").post_comment()
    assert calls[-1] == ("POST", "https://api.github.com/repos/o/r/issues/5/comments")


def test_updates_existing_bot_comment_across_pages(api, in_tmp):
    calls, get_responses = api
    get_responses.append(FakeResponse(200, [], links={"next": {"url": "page2"}}))
    get_responses.append(FakeResponse(200, [
        {"id": 9, "body": COMMENT_MARKER + "old", "user": {"type": "Bot"}}
    ]))

    assert PRReporter("o", "r", 5, "token").post_comment()
    assert calls[-1] == ("PATCH", "https://api.github.com/repos/o/r/issues/comments/9")


def test_missing_decision_produces_failure_comment(in_tmp):
    body = PRReporter("o", "r", 5)._build_comment()

    assert body.startswith(COMMENT_MARKER)
    assert "Analysis failed" in body


def test_report_includes_test_execution(in_tmp):
    (in_tmp / "storage" / "ci_decision.json").write_text(json.dumps({
        "risk_score": 10, "risk_level": "low", "pipeline_status": "ready"
    }), encoding="utf-8")
    (in_tmp / "storage" / "test_execution.json").write_text(json.dumps({
        "results": [
            {"name": "selected_tests", "command": "python -m pytest t.py", "status": "passed", "blocking": True},
            {"name": "generated_tests", "command": "python -m pytest g.py", "status": "failed", "blocking": False},
        ]
    }), encoding="utf-8")

    body = PRReporter("o", "r", 5)._build_comment()

    assert "**1 / 2** test runs passed" in body
    assert "non-blocking" in body


def test_long_report_is_truncated(in_tmp):
    (in_tmp / "storage" / "ci_decision.json").write_text(json.dumps({
        "risk_level": "low",
        "top_drivers": ["x" * 1000] * 100
    }), encoding="utf-8")

    body = PRReporter("o", "r", 5)._build_comment()

    assert len(body) <= MAX_COMMENT_LENGTH
    assert "truncated" in body
