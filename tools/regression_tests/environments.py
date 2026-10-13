"""The environments that the regression tests can be run against, configured in `environments.json`."""

import json
from pathlib import Path

from pydantic import field_validator

from schemas.shared.base_models import StrictCamelModel

ENVIRONMENTS_FILE = Path(__file__).parent / "environments.json"


class Environment(StrictCamelModel):
    # The function app's host, without any path. Empty if not configured yet.
    base_url: str
    # The environment's `EES_URL_API_DATA` setting, without `/api`, for looking up subject meta
    ees_data_api_url: str | None = None

    @field_validator("ees_data_api_url", mode="before")
    @classmethod
    def _empty_as_unset(cls, value: str | None) -> str | None:
        return value or None

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

    @property
    def search_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/natural_language_search_function"

    @property
    def health_check_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/health_check"


def load_environments(path: Path = ENVIRONMENTS_FILE) -> dict[str, Environment]:
    """Keyed by environment name. Empty if the file hasn't been created from `environments.json.example` yet."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {name: Environment.model_validate(value) for name, value in raw.items()}
