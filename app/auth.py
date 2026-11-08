import secrets

from fastapi import Header, HTTPException

from app.settings import analysis_token


def require_bearer(authorization: str | None = Header(default=None)) -> None:
    expected = analysis_token()
    if not expected:
        raise HTTPException(status_code=503, detail="Analysis token is not configured.")
    scheme, _, provided = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="A valid bearer token is required.")
