"""
Regression test report Pydantic models

A report is structured as run -> iterations -> queries -> datasets, with a summary at the run and iteration
levels aggregating the query results beneath them. Dump with `model_dump_json(by_alias=True)`.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from schemas.responses.event_responses import QueryRequirements
from schemas.responses.final_dataset_response import (
    DatasetValidationError,
    DatasetValidationWarning,
)
from schemas.shared.base_models import StrictCamelModel
from schemas.shared.token_usage import TokenUsage


class ExecutionStatus(StrEnum):
    """How a query's request was executed, regardless of whether its results were as expected."""

    SUCCESS = "success"
    SUCCESS_WITH_VALIDATION_ERRORS = "success_with_validation_errors"
    """The pipeline completed, but at least one dataset result has validation errors."""
    SSE_ERROR = "sse_error"
    """The service streamed an error event."""
    HTTP_ERROR = "http_error"
    """The request failed, or the response status wasn't 200."""
    TIMEOUT = "timeout"
    INCOMPLETE_STREAM = "incomplete_stream"
    """The stream ended without a 'pipeline complete' or error event."""
    CONTRACT_MISMATCH = "contract_mismatch"
    """An event didn't match the response schemas, so the service and this script have diverged."""


COMPLETED_STATUSES = frozenset(
    {ExecutionStatus.SUCCESS, ExecutionStatus.SUCCESS_WITH_VALIDATION_ERRORS}
)


class RawEvent(StrictCamelModel):
    elapsed_seconds: float
    data: Any


class DatasetResult(StrictCamelModel):
    rank: int = Field(description="Position in the results, where 1 is the first result.")
    file_id: str
    data_set_file_id: str
    title: str
    relevance_score: float | None = Field(
        default=None,
        description="Taken from the dataset in the 'reranker complete' event, as the 'pipeline complete' event doesn't include it.",
    )
    is_valid_for_table_generation: bool
    validation_errors: list[DatasetValidationError] = Field(default_factory=list)
    validation_warnings: list[DatasetValidationWarning] = Field(default_factory=list)


class DatasetResultsSummary(StrictCamelModel):
    dataset_count: int
    valid_for_table_generation_count: int
    with_validation_warnings_count: int
    validation_error_counts: dict[str, int] = Field(
        default_factory=dict, description="Keyed by validation error code."
    )
    validation_warning_counts: dict[str, int] = Field(
        default_factory=dict, description="Keyed by validation warning code."
    )
    mean_relevance_score: float | None = None


class QueryResult(StrictCamelModel):
    query_id: str
    user_query: str
    publication_id: str
    tags: list[str] = Field(default_factory=list)
    status: ExecutionStatus
    error_message: str | None = None
    last_stage: str | None = Field(
        default=None, description="The stage of the last event received before the stream ended."
    )
    http_status: int | None = None
    duration_seconds: float
    stage_timings: dict[str, float] = Field(
        default_factory=dict,
        description="Keyed by stage. The value is the time from sending the request to receiving that stage's event.",
    )
    confidence: str | None = None
    query_requirements: QueryRequirements | None = None
    dataset_count: int | None = Field(
        default=None, description="Unset if the pipeline didn't complete."
    )
    token_usage: TokenUsage | None = None
    cost: float | None = None
    cost_is_partial: bool = Field(
        description="Whether the token usage and cost are from an earlier stage, as the pipeline didn't complete. "
        "Tokens used by any later stages are not known."
    )
    dataset_summary: DatasetResultsSummary | None = None
    datasets: list[DatasetResult] = Field(default_factory=list)
    raw_events: list[RawEvent] = Field(default_factory=list)


class DurationSummary(StrictCamelModel):
    mean_seconds: float
    p95_seconds: float
    max_seconds: float


class ExecutionSummary(StrictCamelModel):
    query_count: int
    status_counts: dict[ExecutionStatus, int]
    completed_query_durations: DurationSummary | None = Field(
        default=None,
        description="Durations of queries which completed the pipeline, so that quick failures don't skew them.",
    )
    token_usage: TokenUsage
    cost: float
    queries_with_partial_cost: int
    datasets: DatasetResultsSummary


class IterationReport(StrictCamelModel):
    iteration: int
    duration_seconds: float
    summary: ExecutionSummary
    skipped_query_ids: list[str] = Field(
        default_factory=list,
        description="Queries that were not run because the maximum cost of the run had been reached.",
    )
    queries: list[QueryResult] = Field(default_factory=list)


class RunMetadata(StrictCamelModel):
    started_at: datetime
    finished_at: datetime
    environment_name: str
    base_url: str
    input_file: str
    input_file_sha256: str
    git_commit: str | None = None
    query_ids: list[str] = Field(description="The queries selected to run.")
    iterations: int = Field(description="The number of iterations requested.")
    concurrency: int
    timeout_seconds: float
    max_cost: float | None = None
    budget_exceeded: bool = Field(
        description="Whether the maximum cost was reached, after which no further queries are started."
    )


class RegressionReport(StrictCamelModel):
    run: RunMetadata
    summary: ExecutionSummary
    iterations: list[IterationReport] = Field(default_factory=list)
