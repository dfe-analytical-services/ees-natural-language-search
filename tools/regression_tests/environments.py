"""The environments that the regression tests can be run against, configured in `environments.json`."""

import json
from pathlib import Path

from schemas.shared.base_models import StrictCamelModel

ENVIRONMENTS_FILE = Path(__file__).parent / "environments.json"


class Environment(StrictCamelModel):
    base_url: str

    @property
    def search_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/natural_language_search_function"

    @property
    def health_check_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/health_check"


def load_environments(path: Path = ENVIRONMENTS_FILE) -> dict[str, Environment]:
    """Keyed by environment name."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {name: Environment.model_validate(value) for name, value in raw.items()}
