import re
from typing import Literal

from app.github_client import Snapshot
from app.schemas import AnalysisConfig, Insight, PullRequestSubject, ReviewResponse, SuggestedScores

Metric = Literal["clarity", "scope", "evidence", "outcome", "general"]

_SECRET = re.compile(r"(ghp_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}|AKIA[0-9A-Z]{16})")
_WORDS = re.compile(r"[a-z0-9]{3,}")


def redact(value: str) -> str:
    return _SECRET.sub("[redacted]", value)


def _clip(value: str, limit: int) -> str:
    text = redact(value).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _clamp(value: int) -> int:
    return max(0, min(10, value))


def _overlap(left: str, right: str) -> float:
    left_words = set(_WORDS.findall(left.lower()))
    right_words = set(_WORDS.findall(right.lower()))
    if not left_words or not right_words:
        return 0
    return len(left_words & right_words) / len(left_words)


def _mentioned(issue_text: str, files: tuple[str, ...]) -> list[str]:
    lowered = issue_text.lower()
    hits = []
    for name in files:
        base = name.split("/")[-1].lower()
        if (len(base) >= 4 and base in lowered) or name.lower() in lowered:
            hits.append(name)
    return hits


def _sentence(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    cut = compact[:limit].rsplit(" ", 1)[0]
    period = cut.rfind(". ")
    if period >= limit // 2:
        return cut[: period + 1]
    return cut.rstrip(" ,;:") + "…"


def _issue_excerpt(body: str) -> str:
    text = body.replace("\r\n", "\n")
    match = re.search(r"(?ims)^##\s*problem\s*\n+(.*?)(?=^##\s|\Z)", text)
    chunk = match.group(1).strip() if match else ""
    if not chunk:
        for block in re.split(r"\n\s*\n", text):
            cleaned = block.strip()
            if cleaned and not cleaned.startswith("#"):
                chunk = cleaned
                break
    chunk = re.sub(r"`([^`]*)`", r"\1", chunk)
    return _sentence(chunk, 420)


def _issue_asks(body: str) -> str:
    items = re.findall(r"(?m)^\s*-\s+\[[ xX]\]\s+(.+)$", body)
    if not items:
        return ""
    short = []
    for item in items[:3]:
        item = re.sub(r"`([^`]*)`", r"\1", item)
        short.append(_sentence(item, 140))
    sentence = "The issue asks that " + "; ".join(short)
    remaining = len(items) - len(short)
    if remaining:
        sentence += f"; and {remaining} more"
    return sentence + "."


def _file_alignment(snapshot: Snapshot, file_hits: list[str]) -> str:
    if not snapshot.fetched:
        return "GitHub did not return the changed files, so they were not compared with the issue."
    if not snapshot.files:
        return "The pull request reports no changed files to compare with the issue."
    if not file_hits:
        return "None of the changed file names appear in the issue."
    shown = ", ".join(name.split("/")[-1] for name in file_hits[:4])
    extra = len(file_hits) - 4
    if extra > 0:
        shown += f", and {extra} more"
    noun = "file is" if len(file_hits) == 1 else "files are"
    return f"{len(file_hits)} changed {noun} named in the issue: {shown}."


def _linked_issue_detail(snapshot: Snapshot, file_hits: list[str]) -> str:
    number = snapshot.issue_number
    if not snapshot.issue_title:
        return (
            f"The description links issue #{number} with a closing keyword, "
            "but GitHub did not return that issue, so its request could not be compared with this pull request."
        )
    state = snapshot.issue_state or "unknown"
    location = snapshot.issue_url or f"#{number}"
    parts = [f"Fixes #{number} links {location}, “{snapshot.issue_title}” ({state})."]
    excerpt = _issue_excerpt(snapshot.issue_body)
    if excerpt:
        parts.append(excerpt)
    asks = _issue_asks(snapshot.issue_body)
    alignment = _file_alignment(snapshot, file_hits)
    if asks and len(" ".join(parts + [asks, alignment])) <= 980:
        parts.append(asks)
    parts.append(alignment)
    return " ".join(parts)


def _guideline(name: str) -> str:
    lowered = name.lower()
    if "lint" in lowered:
        return "Lint must pass before this pull request is ready."
    if "format" in lowered or "prettier" in lowered:
        return "Formatting must match the repository style."
    if "type" in lowered or "mypy" in lowered or "tsc" in lowered:
        return "Type checks must pass."
    if "test" in lowered or "pytest" in lowered or "jest" in lowered:
        return "Tests must pass."
    if "build" in lowered or "compile" in lowered:
        return "The project must build."
    if "coverage" in lowered:
        return "Coverage must meet the repository threshold."
    return "This check must pass before the pull request is ready."


def _insight(metric: Metric, title: str, detail: str) -> Insight:
    return Insight(metric=metric, title=_clip(title, 120), detail=_clip(detail, 1000))


def build_review(pull_request: PullRequestSubject, snapshot: Snapshot, config: AnalysisConfig) -> ReviewResponse:
    aspects = config.aspects
    issue_text = f"{snapshot.issue_title}\n{snapshot.issue_body}"
    overlap = _overlap(snapshot.issue_title, pull_request.title) if snapshot.issue_title else 0
    file_hits = _mentioned(issue_text, snapshot.files) if snapshot.issue_number else []
    failing = [check for check in snapshot.checks if check.failing]
    looked_up_checks = snapshot.fetched and aspects.checks

    quality = 0
    if snapshot.issue_number and snapshot.issue_title:
        quality += 4
    elif snapshot.issue_number:
        quality += 2
    quality += 3 if overlap >= 0.34 else 1 if overlap > 0 else 0
    if file_hits:
        quality += 3
    elif snapshot.issue_number and snapshot.files:
        quality += 1
    quality = _clamp(quality)

    merge = 10 if pull_request.merged else 6
    if not pull_request.merged:
        if pull_request.draft:
            merge -= 3
        if pull_request.state.lower() == "closed":
            merge -= 4
        if snapshot.mergeable is False:
            merge -= 3
        if failing and aspects.checks:
            merge -= min(4, len(failing))
        if (pull_request.additions or 0) > 400:
            merge -= 2
        if len(pull_request.body.strip()) < 20:
            merge -= 2
    merge = _clamp(merge)

    if not looked_up_checks:
        evidence = 5
    elif not snapshot.checks:
        evidence = 5
    elif not failing:
        evidence = 9
    else:
        evidence = _clamp(8 - 2 * len(failing))

    clarity = 2
    if len(pull_request.body.strip()) >= 80:
        clarity += 4
    elif len(pull_request.body.strip()) >= 20:
        clarity += 2
    if snapshot.issue_number:
        clarity += 2
    if overlap >= 0.34:
        clarity += 2
    clarity = _clamp(clarity)

    scope = 8
    file_count = len(snapshot.files) or pull_request.changedFiles or 0
    if file_count > 20:
        scope -= 3
    elif file_count > 8:
        scope -= 1
    if snapshot.issue_number and snapshot.files and not file_hits:
        scope -= 2
    if (pull_request.additions or 0) > 800:
        scope -= 2
    if file_hits:
        scope += 1
    scope = _clamp(scope)

    insights: list[Insight] = []
    if aspects.quality:
        if snapshot.issue_number:
            insights.append(
                _insight(
                    "clarity",
                    f"Linked issue #{snapshot.issue_number}",
                    _linked_issue_detail(snapshot, file_hits),
                )
            )
        else:
            insights.append(
                _insight(
                    "clarity",
                    "No linked issue",
                    "The description does not use Fixes, Closes, or Resolves with an issue number, so the file changes cannot be checked against an issue.",
                )
            )
    if aspects.mergeReadiness:
        if pull_request.merged:
            detail = "The pull request is already merged."
        elif pull_request.draft:
            detail = "The pull request is still a draft."
        elif failing and aspects.checks:
            detail = f"{len(failing)} check is failing, which lowers the chance it can merge."
        else:
            detail = "Readiness uses draft state, conflicts, size, and checks. This is a rubric, not a historical prediction."
        insights.append(_insight("outcome", f"Merge readiness {merge} / 10", detail))
    if aspects.checks:
        if not snapshot.fetched:
            insights.append(
                _insight(
                    "evidence",
                    "Checks were not loaded",
                    "GitHub checks could not be read. Set GITHUB_TOKEN on the analysis service to report CI guidelines.",
                )
            )
        elif not snapshot.checks:
            insights.append(
                _insight(
                    "evidence",
                    "No checks reported",
                    "This repository did not report commit checks or statuses. That is not the same as a failed test.",
                )
            )
        else:
            for check in failing[:4]:
                insights.append(_insight("evidence", f"{check.name} failed", _guideline(check.name)))
            if not failing:
                insights.append(_insight("evidence", "Checks passed", "The reported checks and statuses succeeded."))
    if aspects.coaching:
        steps = []
        if not snapshot.issue_number:
            steps.append("Link the issue with Fixes #number so the change can be checked against it.")
        if len(pull_request.body.strip()) < 20:
            steps.append("Add a description that explains the change and how it was verified.")
        if failing and aspects.checks:
            steps.append(f"Fix the failing check {failing[0].name} before asking for review.")
        elif (pull_request.additions or 0) > 400:
            steps.append("Split unrelated files into a smaller pull request.")
        for index, step in enumerate(steps[:3], start=1):
            insights.append(_insight("general", f"Next step {index}", step))

    summary_parts = [f"Quality {quality}/10.", f"Merge readiness {merge}/10."]
    if snapshot.issue_number and snapshot.issue_title:
        summary_parts.append(f"Linked issue #{snapshot.issue_number}: {snapshot.issue_title}.")
    elif snapshot.issue_number:
        summary_parts.append(f"Linked issue #{snapshot.issue_number}.")
    if aspects.checks and failing:
        summary_parts.append(f"{len(failing)} check failed.")
    elif aspects.checks and snapshot.fetched and snapshot.checks:
        summary_parts.append("Reported checks passed.")
    summary = _clip(" ".join(summary_parts), 2000)

    suggested = None
    if config.suggestScores:
        suggested = SuggestedScores(clarity=clarity, scope=scope, evidence=evidence, outcome=merge)
    return ReviewResponse(summary=summary, insights=insights[:12], suggestedScores=suggested)
