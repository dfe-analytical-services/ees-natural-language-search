"""Looks up the subject meta of dataset results from the EES Data API, which is needed to compare their filter
selections by filter, and to check that the expected labels exist.

This calls the EES Data API only, so it doesn't use any Azure OpenAI tokens.
"""

import logging
from typing import Protocol

from clients.ees_data_api_client import EesDataApiClient
from schemas.ees_data_api.subject_meta_response import SubjectMetaResponse

logger = logging.getLogger(__name__)


class SubjectMetaUnavailableError(Exception):
    pass


class SubjectMetaSource(Protocol):
    def get(self, subject_id: str) -> SubjectMetaResponse:
        """Raises `SubjectMetaUnavailableError` if the subject meta can't be got."""
        ...


class _SubjectMetaClient(Protocol):
    def get_subject_meta(self, subject_id: str) -> SubjectMetaResponse: ...


class SubjectMetaLookup:
    """Gets subject meta from the EES Data API, caching it, and any failure to get it, by subject id."""

    def __init__(self, ees_data_api_url: str, client: _SubjectMetaClient | None = None):
        """`client` is only for replacing the EES Data API client in tests."""
        self._ees_data_api_url = ees_data_api_url
        self._client = client or EesDataApiClient(base_url=ees_data_api_url)
        self._cache: dict[str, SubjectMetaResponse | SubjectMetaUnavailableError] = {}

    def get(self, subject_id: str) -> SubjectMetaResponse:
        if subject_id not in self._cache:
            try:
                self._cache[subject_id] = self._client.get_subject_meta(subject_id=subject_id)
            except Exception as e:
                logger.warning("Unable to get the subject meta of subject '%s': %s", subject_id, e)
                self._cache[subject_id] = SubjectMetaUnavailableError(
                    f"Unable to get the subject meta of subject '{subject_id}' from {self._ees_data_api_url}: "
                    f"{type(e).__name__}: {e}"
                )

        cached = self._cache[subject_id]
        if isinstance(cached, SubjectMetaUnavailableError):
            raise cached
        return cached


class UnavailableSubjectMeta:
    """Used when there's no EES Data API to get subject meta from, e.g. when the environment has no `eesDataApiUrl`."""

    def __init__(self, reason: str):
        self._reason = reason

    def get(self, subject_id: str) -> SubjectMetaResponse:
        raise SubjectMetaUnavailableError(self._reason)
