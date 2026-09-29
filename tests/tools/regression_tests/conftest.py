from typing import Any, Callable

import pytest

from schemas.responses.event_responses import (
    PipelineCompleteEventData,
    PipelineCompleteEventResponse,
    QueryRequirements,
    RerankerEventData,
    RerankerEventResponse,
    RetrievedDatasetsEventData,
    RetrievedDatasetsEventResponse,
    StartEventResponse,
)
from schemas.responses.final_dataset_response import FinalDatasetResponse
from schemas.responses.reranker_dataset_response import RerankerDatasetResponse
from schemas.shared.token_usage import TokenUsage
from tools.regression_tests.input_models import GoldStandardQuery
from tools.regression_tests.report_models import (
    COMPLETED_STATUSES,
    DatasetResult,
    ExecutionStatus,
    QueryAccuracy,
    QueryResult,
)
from tools.regression_tests.sse_client import SearchExecution, SseEvent

DATASET_DEFAULTS = {
    "data_set_file_id": "test-data-set-file-id",
    "file_id": "test-file-id",
    "publication_id": "test-publication-id",
    "publication_slug": "test-publication",
    "publication_title": "Test publication",
    "release_slug": "test-release",
    "release_version_id": "test-release-version-id",
    "subject_id": "test-subject-id",
    "title": "Test dataset",
    "description": "Test dataset",
}



@pytest.fixture
def query() -> GoldStandardQuery:
    return GoldStandardQuery(
        id="test-query",
        user_query="Test query",
        publication_id="test-publication-id",
        tags=["test"],
    )


@pytest.fixture
def build_final_dataset() -> Callable[..., FinalDatasetResponse]:
    """Builds a `FinalDatasetResponse` with placeholder dataset metadata. Any field can be overridden by keyword."""

    def _make(**overrides: Any) -> FinalDatasetResponse:
        return FinalDatasetResponse(**{**DATASET_DEFAULTS, **overrides})

    return _make


@pytest.fixture
def build_pipeline_events() -> Callable[..., list[dict]]:
    """Builds the event data of a pipeline, as dumped by the service.

    The reranker's datasets have the same file ids as the final datasets, with relevance scores 90, 80, 70...
    The events stop after the reranker if `include_pipeline_complete` is False."""

    def _make(
        final_datasets: list[FinalDatasetResponse] | None = None,
        *,
        include_pipeline_complete: bool = True,
    ) -> list[dict]:
        final_datasets = final_datasets or []
        reranker_datasets = [
            RerankerDatasetResponse(
                **{
                    **DATASET_DEFAULTS,
                    "file_id": dataset.file_id,
                    "relevance_reason": "Relevant",
                    "relevant_filters": [],
                    "relevance_score": 90 - index * 10,
                }
            )
            for index, dataset in enumerate(final_datasets)
        ]

        events = [
            StartEventResponse().model_dump(),
            RetrievedDatasetsEventResponse(
                data=RetrievedDatasetsEventData(datasets=[])
            ).model_dump(by_alias=True),
            RerankerEventResponse(
                data=RerankerEventData(
                    confidence="high",
                    datasets=reranker_datasets,
                    query_requirements=QueryRequirements(filters=["Secondary"]),
                    token_usage=TokenUsage(input=100, output=10),
                    cost=0.0001,
                )
            ).model_dump(by_alias=True),
        ]

        if include_pipeline_complete:
            events.append(
                PipelineCompleteEventResponse(
                    data=PipelineCompleteEventData(
                        datasets=final_datasets,
                        token_usage=TokenUsage(input=1000, output=100),
                        cost=0.001,
                    )
                ).model_dump(by_alias=True)
            )
        return events

    return _make


@pytest.fixture
def build_execution() -> Callable[..., SearchExecution]:
    """Builds a `SearchExecution` of a 200 response, with the given event data received one second apart."""

    def _make(events_data: list[Any], **overrides: Any) -> SearchExecution:
        events = [
            SseEvent(elapsed_seconds=float(index), data=data)
            for index, data in enumerate(events_data, start=1)
        ]
        return SearchExecution(
            **{
                "duration_seconds": float(len(events)),
                "http_status": 200,
                "events": events,
                **overrides,
            }
        )

    return _make


@pytest.fixture
def build_dataset_result() -> Callable[..., DatasetResult]:
    """Builds a `DatasetResult` with its selections given by label, and its locations by geographic level label."""

    def _make(
        data_set_file_id: str = "data-set-file-1",
        title: str = "Dataset 1",
        rank: int = 1,
        filters: tuple[str, ...] = ("Total",),
        indicators: tuple[str, ...] = ("Overall absence rate",),
        time_period: tuple[str, int, str, int] | None = ("AY", 2024, "AY", 2024),
        locations: dict[str, list[str]] | None = None,
    ) -> DatasetResult:
        return DatasetResult.model_validate(
            {
                "rank": rank,
                "fileId": f"file-{data_set_file_id}",
                "dataSetFileId": data_set_file_id,
                "subjectId": "test-subject-id",
                "title": title,
                "isValidForTableGeneration": True,
                "filters": [{"id": f"id-{label}", "label": label} for label in filters],
                "indicators": [{"id": f"id-{label}", "label": label} for label in indicators],
                "timePeriod": (
                    {
                        "start": {"code": time_period[0], "year": time_period[1]},
                        "end": {"code": time_period[2], "year": time_period[3]},
                    }
                    if time_period
                    else None
                ),
                "geographicLevels": {
                    level_label: [{"id": code, "label": code, "value": code} for code in codes]
                    for level_label, codes in (locations or {"National": ["E92000001"]}).items()
                },
            }
        )

    return _make


@pytest.fixture
def build_result() -> Callable[..., QueryResult]:
    """Builds a `QueryResult` of a query that completed with the given datasets, unless another status is given."""

    def _make(
        query_id: str = "query-1",
        status: ExecutionStatus = ExecutionStatus.SUCCESS,
        datasets: list[DatasetResult] | None = None,
        accuracy: QueryAccuracy | None = None,
        cost: float | None = 0.002,
        duration_seconds: float = 5,
    ) -> QueryResult:
        completed = status in COMPLETED_STATUSES
        datasets = (datasets or []) if completed else []
        return QueryResult(
            query_id=query_id,
            user_query=f"Query {query_id}",
            publication_id="test-publication-id",
            status=status,
            duration_seconds=duration_seconds,
            dataset_count=len(datasets) if completed else None,
            cost=cost,
            cost_is_partial=not completed,
            datasets=datasets,
            accuracy=accuracy,
        )

    return _make
