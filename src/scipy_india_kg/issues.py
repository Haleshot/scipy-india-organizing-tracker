"""GitHub issues as a second source.

Meeting notes record what a room decided. Issues record what someone is doing
about it, and the two drift apart within a week. Reading both puts them in one
graph, so "what did we agree to do about sponsorship, and is anyone actually on
it" is a single question.

Set ``ISSUE_SOURCE=github`` and ``GITHUB_REPOS=scipy-india/planning`` to turn
this on. A planning repository usually outlives any one thing being planned, so
``GITHUB_ISSUE_LABELS`` and ``GITHUB_ISSUE_SINCE`` narrow it to the issues that
belong to this conference. Public repositories need no token; GitHub allows 60 unauthenticated
requests an hour from one address, which is plenty for a repo this size but not
for a CI job that runs often. Set ``GITHUB_TOKEN`` to raise that to 5000, and it
is required for private repositories.

Only what a repository shows publicly is read: number, title, state, labels,
assignees, milestone and timestamps. Issue bodies are skipped, both because they
are long and because they are where people paste things that should not end up
in a published graph.
"""

from __future__ import annotations

import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .workgroups import WorkgroupRegistry

API_ROOT = "https://api.github.com"
USER_AGENT = "scipy-india-kg"
PAGE_SIZE = 100
MAX_PAGES = 20  # 2000 issues, far past anything this project will have


@dataclass
class IssueRecord:
    """One issue, as the graph wants it."""

    repo: str
    number: int
    title: str
    url: str
    state: str  # "open" | "closed"
    state_reason: str  # "completed" | "not_planned" | "reopened" | ""
    labels: list[str] = field(default_factory=list)
    assignee_logins: list[str] = field(default_factory=list)
    author_login: str = ""
    milestone: str = ""
    comment_count: int = 0
    created_at: datetime.date = datetime.date.min
    updated_at: datetime.date = datetime.date.min
    closed_at: datetime.date | None = None

    @property
    def key(self) -> str:
        """``owner/repo#number``. Stable, and what a person would write."""
        return f"{self.repo}#{self.number}"


class GitHubIssueSource:
    """Reads issues from one or more repositories.

    ``labels`` and ``since`` are passed to GitHub rather than applied here, so a
    filtered read costs one request instead of forty. A planning repo that
    predates the thing you are planning holds a lot of issues you do not want in
    the graph, and these are how you leave them out.
    """

    def __init__(
        self,
        repos: list[str],
        *,
        token: str = "",
        state: str = "all",
        labels: list[str] | None = None,
        since: str = "",
    ) -> None:
        self._repos = repos
        self._token = token
        self._state = state
        self._labels = labels or []
        self._since = since

    def _get(self, url: str) -> tuple[list[dict[str, Any]], str | None]:
        request = urllib.request.Request(url)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("User-Agent", USER_AGENT)
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
                link = response.headers.get("Link", "")
        except urllib.error.HTTPError as error:
            raise _explain(error, url, bool(self._token)) from error

        next_url = None
        for part in link.split(","):
            if 'rel="next"' in part and "<" in part:
                next_url = part[part.index("<") + 1 : part.index(">")]
        return payload, next_url

    def issues(self) -> list[IssueRecord]:
        records: list[IssueRecord] = []
        query = f"state={self._state}&per_page={PAGE_SIZE}"
        if self._labels:
            # GitHub treats this as AND across labels, so one label per read is
            # the sane way to use it. Several here means "carries all of these".
            query += "&labels=" + urllib.parse.quote(",".join(self._labels))
        if self._since:
            query += "&since=" + urllib.parse.quote(self._since)
        for repo in self._repos:
            url = f"{API_ROOT}/repos/{repo}/issues?{query}"
            for _ in range(MAX_PAGES):
                payload, url = self._get(url)  # type: ignore[assignment]
                for raw in payload:
                    # The issues endpoint returns pull requests too. They are a
                    # different kind of thing and would double-count the work.
                    if "pull_request" in raw:
                        continue
                    records.append(_to_record(repo, raw))
                if not url:
                    break
        return records


def _to_record(repo: str, raw: dict[str, Any]) -> IssueRecord:
    def date(value: str | None) -> datetime.date | None:
        return datetime.date.fromisoformat(value[:10]) if value else None

    return IssueRecord(
        repo=repo,
        number=int(raw["number"]),
        title=str(raw.get("title") or "").strip(),
        url=str(raw.get("html_url") or ""),
        state=str(raw.get("state") or "open"),
        state_reason=str(raw.get("state_reason") or ""),
        labels=[str(label["name"]) for label in raw.get("labels") or []],
        assignee_logins=[str(user["login"]) for user in raw.get("assignees") or []],
        author_login=str((raw.get("user") or {}).get("login") or ""),
        milestone=str((raw.get("milestone") or {}).get("title") or ""),
        comment_count=int(raw.get("comments") or 0),
        created_at=date(raw.get("created_at")) or datetime.date.min,
        updated_at=date(raw.get("updated_at")) or datetime.date.min,
        closed_at=date(raw.get("closed_at")),
    )


def _explain(error: urllib.error.HTTPError, url: str, authenticated: bool) -> ValueError:
    """Turn GitHub's status codes into the thing you actually need to do."""
    repo = url.split("/repos/", 1)[-1].split("?")[0]
    if error.code == 404:
        return ValueError(
            f"GitHub returned 404 for {repo}. Either the name is wrong, or the "
            "repository is private and needs GITHUB_TOKEN set to a token that "
            "can read it. A private repo looks like a missing one without a token."
        )
    if error.code == 403 and not authenticated:
        return ValueError(
            "GitHub rate-limited this address (60 requests an hour without a "
            "token). Set GITHUB_TOKEN to a personal access token, or wait an hour."
        )
    if error.code == 401:
        return ValueError("GITHUB_TOKEN was rejected. It is wrong or it has expired.")
    return ValueError(f"GitHub returned {error.code} for {repo}: {error.reason}")


def workgroup_for(issue: IssueRecord, registry: WorkgroupRegistry) -> str | None:
    """The workgroup an issue belongs to, from its labels.

    A label counts only when it names a workgroup in the registry. Everything
    else is left alone rather than guessed at from the title, which is the same
    rule the notes extractor follows.
    """
    for label in issue.labels:
        slug = registry.resolve(label)
        if slug:
            return slug
    return None


def issue_source(*, repos: list[str] | None = None) -> GitHubIssueSource | None:
    """Build the configured issue source, or None when issues are switched off."""
    kind = os.environ.get("ISSUE_SOURCE", "none").strip().lower()
    if kind in ("", "none", "off"):
        return None
    if kind != "github":
        raise ValueError(f"Unknown ISSUE_SOURCE={kind!r}. Use 'none' or 'github'.")

    if repos is None:
        repos = [r.strip() for r in os.environ.get("GITHUB_REPOS", "").split(",") if r.strip()]
    if not repos:
        raise ValueError(
            "ISSUE_SOURCE=github needs GITHUB_REPOS, for example GITHUB_REPOS=scipy-india/planning"
        )
    for repo in repos:
        if repo.count("/") != 1:
            raise ValueError(f"GITHUB_REPOS entry {repo!r} should look like owner/name.")

    since = os.environ.get("GITHUB_ISSUE_SINCE", "").strip()
    if since:
        # GitHub wants ISO 8601. A plain date is the useful thing to type, so
        # accept that and fill in the rest.
        try:
            datetime.date.fromisoformat(since[:10])
        except ValueError as error:
            raise ValueError(
                f"GITHUB_ISSUE_SINCE={since!r} is not a date. Use YYYY-MM-DD."
            ) from error
        if len(since) == 10:
            since = f"{since}T00:00:00Z"

    return GitHubIssueSource(
        repos,
        token=os.environ.get("GITHUB_TOKEN", "").strip(),
        state=os.environ.get("GITHUB_ISSUE_STATE", "all").strip().lower(),
        labels=[
            label.strip()
            for label in os.environ.get("GITHUB_ISSUE_LABELS", "").split(",")
            if label.strip()
        ],
        since=since,
    )
