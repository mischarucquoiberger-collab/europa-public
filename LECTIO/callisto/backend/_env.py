"""Keys come from ONE file: the repo-root .env of prism-nicrron (three folders up from this package).

Real environment variables win (override=False). Never print or log the values."""
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]   # backend -> callisto -> LECTIO -> repo root
ENV_FILE = REPO_ROOT / ".env"


def load_env() -> None:
    load_dotenv(ENV_FILE, override=False)
