import os

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT = 30

_session = None


def get_session() -> requests.Session:
    """
    Shared HTTP session with retries on transient errors
    (rate limits, 5xx) so a flaky network doesn't fail the pipeline.
    """
    global _session
    if _session is None:
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
            raise_on_status=False
        )
        session = requests.Session()
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _session = session
    return _session


def github_headers() -> dict:
    """
    API headers. Uses GITHUB_TOKEN when available - unauthenticated
    requests are limited to 60/hour and shared across CI runners.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_get(url: str, params: dict = None) -> requests.Response:
    """GET a GitHub API URL and raise a readable error on failure."""
    if url.startswith("/"):
        url = API_BASE + url

    response = get_session().get(
        url, headers=github_headers(), params=params, timeout=DEFAULT_TIMEOUT
    )

    if response.status_code != 200:
        try:
            message = response.json().get("message", response.text)
        except ValueError:
            message = response.text
        raise RuntimeError(
            f"GitHub API error {response.status_code} for {url}: {message}"
        )

    return response


def github_get_paginated(url: str, params: dict = None) -> list:
    """GET every page of a list endpoint (100 items per page)."""
    params = dict(params or {})
    params.setdefault("per_page", 100)

    items = []
    while url:
        response = github_get(url, params=params)
        items.extend(response.json())
        # The "next" URL already carries the query params
        url = response.links.get("next", {}).get("url")
        params = None

    return items


def download_raw_file(owner: str, repo: str, ref: str, path: str) -> str | None:
    """Download one file's raw contents at a given ref. Returns None if missing."""
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
    response = get_session().get(url, timeout=DEFAULT_TIMEOUT)
    if response.status_code == 200:
        return response.text
    return None
