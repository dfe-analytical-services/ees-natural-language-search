"""Tests for looking up subject meta in `tools.regression_tests.subject_meta`."""

import pytest

from schemas.ees_data_api.subject_meta_response import SubjectMetaResponse
from tools.regression_tests.subject_meta import (
    SubjectMetaLookup,
    SubjectMetaUnavailableError,
    UnavailableSubjectMeta,
)

EES_DATA_API_URL = "https://data.test"


class _FakeClient:
    def __init__(self, subject_meta: SubjectMetaResponse | None = None, error: Exception | None = None):
        self.subject_meta = subject_meta
        self.error = error
        self.requested_subject_ids: list[str] = []

    def get_subject_meta(self, subject_id: str) -> SubjectMetaResponse:
        self.requested_subject_ids.append(subject_id)
        if self.error:
            raise self.error
        return self.subject_meta


@pytest.fixture
def subject_meta(load_json_fixture) -> SubjectMetaResponse:
    return SubjectMetaResponse.model_validate(load_json_fixture("subject_meta_persistent_absence.json"))


def test_subject_meta_is_cached_by_subject_id(subject_meta):
    client = _FakeClient(subject_meta)
    lookup = SubjectMetaLookup(EES_DATA_API_URL, client=client)

    assert lookup.get("subject-1") is subject_meta
    assert lookup.get("subject-1") is subject_meta
    lookup.get("subject-2")

    assert client.requested_subject_ids == ["subject-1", "subject-2"]


def test_failure_to_get_subject_meta_is_cached_and_raised():
    client = _FakeClient(error=ConnectionError("Connection refused"))
    lookup = SubjectMetaLookup(EES_DATA_API_URL, client=client)

    for _ in range(2):
        with pytest.raises(SubjectMetaUnavailableError) as error:
            lookup.get("subject-1")

    assert str(error.value) == (
        "Unable to get the subject meta of subject 'subject-1' from https://data.test: "
        "ConnectionError: Connection refused"
    )
    assert client.requested_subject_ids == ["subject-1"]


def test_unavailable_subject_meta_always_raises_its_reason():
    with pytest.raises(SubjectMetaUnavailableError, match="No eesDataApiUrl"):
        UnavailableSubjectMeta("No eesDataApiUrl").get("subject-1")
