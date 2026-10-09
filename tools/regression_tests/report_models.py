"""
Regression test report Pydantic models

A report is structured as run -> iterations -> queries -> datasets, with a summary at the run and iteration
levels aggregating the query results beneath them. Dump with `model_dump_json(by_alias=True)`.

Each query result has an execution status, describing how its request was executed, and separately an accuracy,
describing whether its results match the expected results in the gold standard file.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from schemas.domain.locations_response import DatasetLocations
from schemas.responses.event_responses import QueryRequirements
from schemas.responses.final_dataset_response import (
    AutoSelectedFilterItem,
    DatasetValidationError,
    DatasetValidationWarning,
    FilterSelectionItem,
    IndicatorSelectionItem,
    TimePeriodRange,
)
from schemas.shared.base_models import StrictCamelModel
from schemas.shared.token_usage import TokenUsage
from tools.regression_tests.input_models import ExpectedTimePeriodRange


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
    subject_id: str
    title: str
    relevance_score: float | None = Field(
        default=None,
        description="Taken from the dataset in the 'reranker complete' event, as the 'pipeline complete' event doesn't include it.",
    )
    is_valid_for_table_generation: bool
    validation_errors: list[DatasetValidationError] = Field(default_factory=list)
    validation_warnings: list[DatasetValidationWarning] = Field(default_factory=list)
    filters: list[FilterSelectionItem] = Field(default_factory=list)
    indicators: list[IndicatorSelectionItem] = Field(default_factory=list)
    time_period: TimePeriodRange | None = None
    geographic_levels: DatasetLocations | None = None
    auto_selected_filter_items: dict[str, AutoSelectedFilterItem] = Field(default_factory=dict)
    unfiltered_filters: list[str] = Field(default_factory=list)


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


class AccuracyResult(StrEnum):
    """Whether results match the expected results, regardless of how the query's request was executed."""

    PASS = "pass"
    PARTIAL = "partial"
    """Some, but not all, of the expected results matched."""
    FAIL = "fail"
    NOT_EVALUATED = "not_evaluated"
    """The results couldn't be compared, e.g. because the pipeline didn't complete."""


class SelectionAccuracy(StrictCamelModel):
    """Compares the selected values with the expected values, e.g. of the indicators, or of one filter.

    Selections pass on an exact match. Precision and recall show how close a selection that doesn't pass is."""

    passed: bool
    expected: list[str] = Field(default_factory=list)
    selected: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list, description="Expected, but not selected.")
    unexpected: list[str] = Field(default_factory=list, description="Selected, but not expected.")
    precision: float | None = Field(
        default=None,
        description="The proportion of the selected values that were expected. Unset if nothing was selected.",
    )
    recall: float | None = Field(
        default=None,
        description="The proportion of the expected values that were selected. Unset if nothing was expected.",
    )


class GroupedSelectionAccuracy(StrictCamelModel):
    """Compares selections which are grouped, e.g. filter items by filter, or locations by geographic level."""

    passed: bool
    precision: float | None = None
    recall: float | None = None
    groups: dict[str, SelectionAccuracy] = Field(
        default_factory=dict, description="Keyed by filter label, or geographic level label."
    )


class TimePeriodAccuracy(StrictCamelModel):
    passed: bool
    expected: ExpectedTimePeriodRange
    selected: TimePeriodRange | None = None


class ExpectedDatasetAccuracy(StrictCamelModel):
    data_set_file_id: str
    title: str | None = Field(default=None, description="The title given in the gold standard file.")
    required: bool
    result: AccuracyResult
    found: bool
    rank: int | None = None
    max_rank: int | None = None
    rank_passed: bool | None = Field(default=None, description="Unset if no maximum rank is expected.")
    filters: GroupedSelectionAccuracy | None = Field(
        default=None, description="Unset if no filters are expected, or if they couldn't be compared."
    )
    indicators: SelectionAccuracy | None = None
    time_period: TimePeriodAccuracy | None = None
    locations: GroupedSelectionAccuracy | None = None
    problems: list[str] = Field(
        default_factory=list,
        description="Problems comparing the dataset, e.g. expected labels that don't exist in its subject meta.",
    )


class QueryAccuracy(StrictCamelModel):
    result: AccuracyResult
    author: str | None = Field(default=None, description="Who wrote the expected results.")
    reason: str | None = Field(default=None, description="Why the results weren't evaluated.")
    min_datasets: int | None = None
    min_datasets_passed: bool | None = None
    datasets: list[ExpectedDatasetAccuracy] = Field(default_factory=list)


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
    accuracy: QueryAccuracy | None = Field(
        default=None, description="Unset if the query has no expected results."
    )
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


class PassRate(StrictCamelModel):
    evaluated: int
    passed: int
    pass_rate: float | None = Field(default=None, description="Unset if nothing was evaluated.")


class AccuracySummary(StrictCamelModel):
    """Aggregates the accuracy of the queries with expected results."""

    query_count: int
    result_counts: dict[AccuracyResult, int]
    result_counts_by_author: dict[str, dict[AccuracyResult, int]] = Field(
        default_factory=dict,
        description="Keyed by who wrote the expected results, or 'unspecified', so that each can be compared separately.",
    )
    required_datasets_found: PassRate
    rank: PassRate
    filters: PassRate
    indicators: PassRate
    time_period: PassRate
    locations: PassRate
    mean_reciprocal_rank: float | None = Field(
        default=None,
        description="The mean over evaluated queries of 1 / the rank of the highest ranked expected dataset found, "
        "or 0 if none were found.",
    )
    problem_count: int = Field(
        description="The number of problems comparing datasets, e.g. expected labels that don't exist."
    )


class IterationReport(StrictCamelModel):
    iteration: int
    duration_seconds: float
    summary: ExecutionSummary
    accuracy_summary: AccuracySummary | None = Field(
        default=None, description="Unset if none of the queries have expected results."
    )
    skipped_query_ids: list[str] = Field(
        default_factory=list,
        description="Queries that were not run because the maximum cost of the run had been reached.",
    )
    queries: list[QueryResult] = Field(default_factory=list)


class ConsistencyAspect(StrEnum):
    """What can differ between iterations of a query, or between a run and its baseline."""

    STATUS = "status"
    ACCURACY = "accuracy"
    DATASETS = "datasets"
    FILTERS = "filters"
    INDICATORS = "indicators"
    TIME_PERIOD = "time_period"
    LOCATIONS = "locations"


class QueryConsistency(StrictCamelModel):
    """Whether a query returned the same results in every iteration it ran in."""

    query_id: str
    iterations: int
    consistent: bool
    inconsistent_aspects: list[ConsistencyAspect] = Field(default_factory=list)
    differences: list[str] = Field(
        default_factory=list, description="How each iteration differs from the first iteration that completed."
    )


class ConsistencySummary(StrictCamelModel):
    query_count: int = Field(description="The number of queries that ran in more than one iteration.")
    consistent_count: int
    consistency_rate: float | None = None
    inconsistent_counts: dict[ConsistencyAspect, int] = Field(
        default_factory=dict, description="The number of inconsistent queries, by what was inconsistent."
    )


class RunConsistency(StrictCamelModel):
    summary: ConsistencySummary
    queries: list[QueryConsistency] = Field(default_factory=list)


class QueryChange(StrEnum):
    """How a query's results changed from the baseline."""

    REGRESSED = "regressed"
    """Something got worse, e.g. its status, its accuracy, or a check that passed now fails, and nothing got better."""
    IMPROVED = "improved"
    """Something got better, and nothing got worse."""
    MIXED = "mixed"
    """Some things got better, and some got worse."""
    CHANGED = "changed"
    """The results changed, e.g. different datasets or selections, but nothing got better or worse."""
    UNCHANGED = "unchanged"
    NEW = "new"
    """The query isn't in the baseline, e.g. because it's new, or its text has changed."""


class QueryComparison(StrictCamelModel):
    query_id: str
    change: QueryChange
    baseline_status: ExecutionStatus | None = Field(
        default=None, description="The worst status of the query in any iteration of the baseline."
    )
    current_status: ExecutionStatus | None = None
    baseline_accuracy: AccuracyResult | None = Field(
        default=None, description="The worst accuracy of the query in any iteration of the baseline."
    )
    current_accuracy: AccuracyResult | None = None
    differences: list[str] = Field(default_factory=list)


class MetricComparison(StrictCamelModel):
    name: str
    unit: Literal["rate", "cost", "seconds"]
    baseline: float | None = None
    current: float | None = None


class BaselineSource(StrictCamelModel):
    report_file: str
    environment_name: str
    started_at: datetime


class BaselineComparison(StrictCamelModel):
    """Compares the run with a previous run.

    The baseline's results are rebuilt from its recorded events and compared with the current expected results, so
    that differences come from the service, rather than from changes to the expected results or to this script."""

    baseline: BaselineSource
    change_counts: dict[QueryChange, int]
    metrics_query_count: int = Field(
        description="The number of queries in both the run and the baseline, which the metrics are compared over."
    )
    metrics: list[MetricComparison] = Field(default_factory=list)
    queries: list[QueryComparison] = Field(default_factory=list)


class ReplaySource(StrictCamelModel):
    """The report whose recorded events were replayed, instead of calling the service."""

    report_file: str
    environment_name: str
    base_url: str
    started_at: datetime


class RunMetadata(StrictCamelModel):
    started_at: datetime
    finished_at: datetime
    environment_name: str
    base_url: str
    input_file: str
    query_ids: list[str] = Field(description="The queries selected to run.")
    iterations: int = Field(description="The number of iterations requested.")
    concurrency: int
    timeout_seconds: float
    max_cost: float | None = None
    budget_exceeded: bool = Field(
        description="Whether the maximum cost was reached, after which no further queries are started."
    )
    replayed_from: ReplaySource | None = Field(
        default=None,
        description="Set when the run replayed a previous report's recorded events. The token usage and cost are "
        "then the recorded ones, and no tokens were used. Durations are meaningless, as the events are replayed "
        "without any delay.",
    )


class RegressionReport(StrictCamelModel):
    run: RunMetadata
    summary: ExecutionSummary
    accuracy_summary: AccuracySummary | None = Field(
        default=None, description="Unset if none of the queries have expected results."
    )
    consistency: RunConsistency | None = Field(
        default=None, description="Unset unless a query ran in more than one iteration."
    )
    baseline_comparison: BaselineComparison | None = Field(
        default=None, description="Unset unless the run was compared with a baseline."
    )
    iterations: list[IterationReport] = Field(default_factory=list)
