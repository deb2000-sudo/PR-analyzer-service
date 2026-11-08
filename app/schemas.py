from typing import Literal

from pydantic import BaseModel, Field


class PullRequestSubject(BaseModel):
    url: str
    repository: str
    number: int = Field(ge=1)
    title: str = ""
    body: str = ""
    state: str = ""
    merged: bool = False
    draft: bool = False
    authorLogin: str = ""
    additions: int | None = None
    deletions: int | None = None
    changedFiles: int | None = None
    commits: int | None = None


class AnalysisAspects(BaseModel):
    quality: bool = True
    mergeReadiness: bool = True
    checks: bool = True
    coaching: bool = True


class AnalysisWeights(BaseModel):
    issueMatch: int = Field(default=4, ge=0, le=10)
    fileMatch: int = Field(default=4, ge=0, le=10)
    description: int = Field(default=2, ge=0, le=10)
    checks: int = Field(default=6, ge=0, le=10)
    size: int = Field(default=4, ge=0, le=10)


class AnalysisConfig(BaseModel):
    aspects: AnalysisAspects = Field(default_factory=AnalysisAspects)
    suggestScores: bool = True
    weights: AnalysisWeights = Field(default_factory=AnalysisWeights)


class ReviewRequest(BaseModel):
    pullRequest: PullRequestSubject
    config: AnalysisConfig = Field(default_factory=AnalysisConfig)


class Insight(BaseModel):
    metric: Literal["clarity", "scope", "evidence", "outcome", "general"]
    title: str
    detail: str


class SuggestedScores(BaseModel):
    clarity: int = Field(ge=0, le=10)
    scope: int = Field(ge=0, le=10)
    evidence: int = Field(ge=0, le=10)
    outcome: int = Field(ge=0, le=10)


class ReviewResponse(BaseModel):
    summary: str
    insights: list[Insight]
    suggestedScores: SuggestedScores | None = None
