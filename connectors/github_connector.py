"""
GitHub connector.

Pulls PRs and Issues (+ their comments) from public repos using the REST API.
Works with just a personal access token, no special scopes needed for public repos.

Design notes:
- One RawItem per PR/Issue: title + body + all comments concatenated as one
  logical conversation. Diffs are intentionally left OUT of this RawItem —
  they get pulled separately and chunked per-file later in the chunker,
  because mixing prose discussion and code diff in one embedding is a
  known way to degrade retrieval quality for both.
- permission_scope = the repo's full_name ("owner/repo"). In a real company
  this would map to actual repo-level access; here it's what we filter on.
"""

import os
import time
from datetime import datetime, timezone
from typing import Iterator, Optional

import requests

from connectors.base import BaseConnector, RawItem
from dotenv import load_dotenv
load_dotenv()

GITHUB_API = "https://api.github.com"


class GitHubConnector(BaseConnector):
    source_name = "github"

    def __init__(self, token: str, repos: list[str]):
        """
        token: GitHub personal access token
        repos: list of "owner/repo" strings, e.g. ["psf/requests", "pallets/flask"]
        """
        self.token = token
        self.repos = repos
        self.session = requests.Session()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            # GitHub's API rejects requests with no User-Agent (403), unlike most REST APIs
            "User-Agent": "knowledge-assistant-connector",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.session.headers.update(headers)
        self._latest_seen: Optional[str] = None  # tracks max updated_at across this run

    def fetch_since(self, cursor: Optional[str]) -> Iterator[RawItem]:
        for repo in self.repos:
            yield from self._fetch_repo_issues_and_prs(repo, cursor)

    def _fetch_repo_issues_and_prs(self, repo: str, cursor: Optional[str]) -> Iterator[RawItem]:
        # GitHub's /issues endpoint returns BOTH issues and PRs (PRs have a "pull_request" key)
        url = f"{GITHUB_API}/repos/{repo}/issues"
        params = {
            "state": "all",
            "sort": "updated",
            "direction": "desc",
            "per_page": 50,
        }
        if cursor:
            params["since"] = cursor  # ISO 8601 timestamp

        page = 1
        while True:
            params["page"] = page
            resp = self.session.get(url, params=params)
            self._handle_rate_limit(resp)
            resp.raise_for_status()
            items = resp.json()
            if not items:
                break

            for item in items:
                raw = self._normalize_issue_or_pr(repo, item)
                if raw is not None:
                    self._track_cursor(raw.updated_at)
                    yield raw

            page += 1
            if len(items) < params["per_page"]:
                break

    def _normalize_issue_or_pr(self, repo: str, item: dict) -> Optional[RawItem]:
        number = item["number"]
        is_pr = "pull_request" in item
        kind = "pr" if is_pr else "issue"

        comments = self._fetch_comments(repo, number) if item.get("comments", 0) > 0 else []

        body_parts = [item.get("body") or "(no description)"]
        for c in comments:
            author = c.get("user", {}).get("login", "unknown")
            body_parts.append(f"[comment by {author}]: {c.get('body', '')}")

        content = "\n\n".join(body_parts)

        created_at = self._parse_ts(item["created_at"])
        updated_at = self._parse_ts(item["updated_at"])

        return RawItem(
            source="github",
            source_id=f"{repo}#{number}",
            title=f"[{kind.upper()}] {repo}#{number}: {item['title']}",
            content=content,
            permission_scope=repo,
            created_at=created_at,
            updated_at=updated_at,
            metadata={
                "kind": kind,
                "repo": repo,
                "number": number,
                "state": item.get("state"),
                "author": item.get("user", {}).get("login"),
                "url": item.get("html_url"),
                "labels": [l["name"] for l in item.get("labels", [])],
            },
        )

    def _fetch_comments(self, repo: str, number: int) -> list[dict]:
        url = f"{GITHUB_API}/repos/{repo}/issues/{number}/comments"
        resp = self.session.get(url, params={"per_page": 100})
        self._handle_rate_limit(resp)
        resp.raise_for_status()
        return resp.json()

    def _handle_rate_limit(self, resp: requests.Response):
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining is not None and int(remaining) == 0:
            reset_at = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            sleep_for = max(reset_at - time.time(), 1)
            print(f"[github_connector] rate limited, sleeping {sleep_for:.0f}s")
            time.sleep(sleep_for)

    def _track_cursor(self, updated_at: datetime):
        iso = updated_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        if self._latest_seen is None or iso > self._latest_seen:
            self._latest_seen = iso

    @staticmethod
    def _parse_ts(ts: str) -> datetime:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    def get_next_cursor(self) -> str:
        return self._latest_seen or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    # Quick manual test — run this file directly to sanity check the connector
    # before wiring it into the full pipeline.
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("Set GITHUB_TOKEN env var first (see .env.example)")

    repos = os.environ.get("GITHUB_REPOS", "psf/requests").split(",")
    connector = GitHubConnector(token=token, repos=repos)

    count = 0
    for raw_item in connector.fetch_since(cursor=None):
        count += 1
        print(f"--- {raw_item.title}")
        print(f"    scope={raw_item.permission_scope} updated={raw_item.updated_at}")
        print(f"    content preview: {raw_item.content[:150]!r}")
        print()
        if count >= 5:
            print("... stopping preview at 5 items ...")
            break

    print(f"\nNext cursor would be: {connector.get_next_cursor()}")