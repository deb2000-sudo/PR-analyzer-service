import os

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def analysis_token() -> str:
    return os.environ.get("ANALYSIS_TOKEN", "").strip()


def github_token() -> str:
    return os.environ.get("GITHUB_TOKEN", "").strip()


def firestore_enabled() -> bool:
    return _flag("FIRESTORE_ENABLED")


def firestore_project() -> str:
    return os.environ.get("FIRESTORE_PROJECT", "").strip()


def firestore_collection() -> str:
    return os.environ.get("FIRESTORE_COLLECTION", "prAnalyses").strip() or "prAnalyses"
