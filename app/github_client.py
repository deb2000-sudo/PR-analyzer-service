import re
from dataclasses import dataclass

import httpx

from app.schemas import PullRequestSubject

# A closing keyword must sit immediately before the reference. A bare "#160"
# in the same description is a mention, not the issue this pull request closes.
_CLOSING_REFERENCE = re.compile(
    r"\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s*:?\s*"
    r"(?:\[)?(?:#(?P<hash>\d+)"
    r"|https?://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/issues/(?P<url_number>\d+)"
    r"|(?P<qowner>[A-Za-z0-9_.-]+)/(?P<qrepo>[A-Za-z0-9_.-]+)#(?P<qualified>\d+))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    conclusion: str | None

    @property
    def failing(self) -> bool:
        return (self.conclusion or "").lower() in {"failure", "cancelled", "timed_out", "action_required", "error"}


@dataclass(frozen=True)
class Snapshot:
    fetched: bool
    issue_number: int | None
    issue_title: str
    issue_body: str
    files: tuple[str, ...]
    mergeable: bool | None
    checks: tuple[CheckResult, ...]
    issue_state: str = ""
    issue_url: str = ""


def linked_issue_number(repository: str, body: str) -> int | None:
    """Return the issue a closing keyword points at.

    GitHub treats `Fixes #136.` as a link. The period, a markdown bracket,
    and a full issue URL all stay attached to that reference in real
    descriptions, so the number is read from the digits only. A mention such
    as "the fix from #160" has no closing keyword and is left alone.
    """
    expected = repository.strip().lower()
    for match in _CLOSING_REFERENCE.finditer(body):
        if match.group("hash"):
            return int(match.group("hash"))
        owner = (match.group("owner") or match.group("qowner") or "").lower()
        repo = (match.group("repo") or match.group("qrepo") or "").lower()
        number = match.group("url_number") or match.group("qualified")
        if number and f"{owner}/{repo}" == expected:
            return int(number)
    return None


class GitHubClient:
    def __init__(self, token: str, transport: httpx.AsyncBaseTransport | None = None):
        self._token = token
        self._transport = transport

    async def load(self, pull_request: PullRequestSubject) -> Snapshot:
        owner_repo = pull_request.repository.split("/", 1)
        submitted = f"{pull_request.title}\n{pull_request.body}"
        issue_number = linked_issue_number(pull_request.repository, submitted)
        if len(owner_repo) != 2:
            return Snapshot(False, issue_number, "", "", (), None, ())

        owner, repo = owner_repo
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "pr-analyzer-service",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=8.0, headers=headers) as client:
                pull = await self._json(client, f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_request.number}")
                if pull is None:
                    return Snapshot(False, issue_number, "", "", (), None, ())
                live_body = pull.get("body")
                body = live_body if isinstance(live_body, str) and live_body.strip() else pull_request.body
                title = str(pull.get("title") or pull_request.title)
                issue_number = linked_issue_number(pull_request.repository, f"{title}\n{body}") or issue_number
                files = await self._json(client, f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_request.number}/files?per_page=100")
                issue = None
                if issue_number is not None:
                    issue = await self._json(client, f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}")
                sha = str((pull.get("head") or {}).get("sha") or "")
                checks = await self._checks(client, owner, repo, sha) if sha else ()
        except httpx.HTTPError:
            return Snapshot(False, issue_number, "", "", (), None, ())

        filenames = tuple(
            str(item.get("filename"))
            for item in files or []
            if isinstance(item, dict) and item.get("filename")
        )
        issue_data = issue if isinstance(issue, dict) else {}
        return Snapshot(
            fetched=True,
            issue_number=issue_number,
            issue_title=str(issue_data.get("title") or ""),
            issue_body=str(issue_data.get("body") or ""),
            files=filenames,
            mergeable=pull.get("mergeable") if isinstance(pull.get("mergeable"), bool) else None,
            checks=tuple(checks),
            issue_state=str(issue_data.get("state") or ""),
            issue_url=str(issue_data.get("html_url") or ""),
        )

    async def _checks(self, client: httpx.AsyncClient, owner: str, repo: str, sha: str) -> list[CheckResult]:
        runs = await self._json(client, f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}/check-runs?per_page=100")
        statuses = await self._json(client, f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}/status")
        found: list[CheckResult] = []
        for run in (runs or {}).get("check_runs", []) if isinstance(runs, dict) else []:
            found.append(CheckResult(str(run.get("name") or "check"), run.get("conclusion")))
        for status in (statuses or {}).get("statuses", []) if isinstance(statuses, dict) else []:
            state = str(status.get("state") or "")
            conclusion = "success" if state == "success" else "failure" if state in {"failure", "error"} else state or None
            found.append(CheckResult(str(status.get("context") or "status"), conclusion))
        return found

    async def _json(self, client: httpx.AsyncClient, url: str) -> dict | list | None:
        response = await client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = response.json()
        if isinstance(body, (dict, list)):
            return body
        return None
