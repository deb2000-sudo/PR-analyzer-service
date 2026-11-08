import logging

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from app.auth import require_bearer
from app.github_client import GitHubClient
from app.rubric import build_review
from app.schemas import ReviewRequest, ReviewResponse
from app.settings import github_token
from app.store import save_review

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

app = FastAPI(title="PR Analyzer Service", docs_url=None, redoc_url=None)


def github_client() -> GitHubClient:
    return GitHubClient(github_token())


@app.get("/", include_in_schema=False)
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/", response_model=ReviewResponse, response_model_exclude_none=True)
@app.post("/review", response_model=ReviewResponse, response_model_exclude_none=True)
async def review(
    request: ReviewRequest,
    _: None = Depends(require_bearer),
    github: GitHubClient = Depends(github_client),
) -> ReviewResponse | JSONResponse:
    try:
        snapshot = await github.load(request.pullRequest)
        result = build_review(request.pullRequest, snapshot, request.config)
    except Exception:
        logging.getLogger("pr-analyzer").warning("review_failed")
        return JSONResponse(status_code=503, content={"detail": "The pull request could not be analyzed."})
    save_review(request, result)
    return result
