import json
from typing import Any, Callable

import pytest

from schemas.domain.dataset_with_subject_meta import DatasetWithSubjectMeta
from schemas.ees_data_api.subject_meta_response import SubjectMetaResponse

DATASET_DEFAULTS = {
    "file_id": "test-file-id",
    "dataset_file_id": "test-dataset-file-id",
    "description": "Test dataset",
    "publication_id": "test-publication-id",
    "publication_slug": "test-publication",
    "publication_title": "Test publication",
    "release_slug": "test-release",
    "release_version_id": "test-release-version-id",
    "subject_id": "test-subject-id",
    "title": "Test dataset",
}


@pytest.fixture
def load_json_fixture(request: pytest.FixtureRequest) -> Callable[[str], Any]:
    """Loads a JSON file from the `fixtures` directory next to the requesting test module."""
    fixtures_dir = request.path.parent / "fixtures"

    def _load(filename: str) -> Any:
        return json.loads((fixtures_dir / filename).read_text())

    return _load


@pytest.fixture
def build_dataset() -> Callable[..., DatasetWithSubjectMeta]:
    """Builds a `DatasetWithSubjectMeta` with placeholder dataset metadata, so that tests
    only need to specify the parts of the subject meta they are concerned with.

    Any dataset field can be overridden by keyword, e.g. `build_dataset(file_id="other-file-id")`.
    """

    def _make(
        *,
        filters: dict | None = None,
        indicators: dict | None = None,
        locations: dict | None = None,
        time_period: dict | None = None,
        **overrides: Any,
    ) -> DatasetWithSubjectMeta:
        subject_meta = SubjectMetaResponse.model_validate(
            {
                "filters": filters or {},
                "indicators": indicators or {},
                "locations": locations or {},
                "timePeriod": time_period or {"options": []},
            }
        )

        return DatasetWithSubjectMeta(**{**DATASET_DEFAULTS, **overrides, "subject_meta": subject_meta})

    return _make
