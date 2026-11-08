import hashlib
import logging

from app.schemas import ReviewRequest, ReviewResponse
from app.settings import firestore_collection, firestore_enabled, firestore_project

logger = logging.getLogger("pr-analyzer")


def document_id(request: ReviewRequest) -> str:
    pull_request = request.pullRequest
    identity = "|".join(
        [
            pull_request.repository.lower(),
            str(pull_request.number),
            pull_request.state.lower(),
            str(pull_request.merged),
            str(pull_request.draft),
            str(pull_request.additions),
            str(pull_request.deletions),
            str(pull_request.changedFiles),
            str(pull_request.commits),
        ]
    )
    return hashlib.sha256(identity.encode()).hexdigest()[:40]


def save_review(request: ReviewRequest, review: ReviewResponse) -> None:
    if not firestore_enabled():
        return
    payload = {
        "repository": request.pullRequest.repository,
        "number": request.pullRequest.number,
        "summary": review.summary,
        "insights": [item.model_dump() for item in review.insights],
        "suggestedScores": review.suggestedScores.model_dump() if review.suggestedScores else None,
        "rubricVersion": "1",
    }
    try:
        from google.cloud import firestore

        client = firestore.Client(project=firestore_project() or None)
        client.collection(firestore_collection()).document(document_id(request)).set(payload)
    except Exception:
        logger.warning("firestore_write_failed")
