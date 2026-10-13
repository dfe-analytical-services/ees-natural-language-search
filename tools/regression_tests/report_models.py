"""
Regression test report Pydantic models

A report is structured as run -> iterations -> queries -> datasets. Dump with `model_dump_json(by_alias=True)`.
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
    SSE_ERROR = "sse_error"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    INCOMPLETE_STREAM = "incomplete_stream"
    CONTRACT_MISMATCH = "contract_mismatch"


COMPLETED_STATUSES = frozenset({ExecutionStatus.SUCCESS, ExecutionStatus.SUCCESS_WITH_VALIDATION_ERRORS})


class RawEvent(StrictCamelModel):
    elapsed_seconds: float
    data: Any


class DatasetResult(StrictCamelModel):
    # Position in the results, where 1 is the first result
    rank: int
    file_id: str
    data_set_file_id: str
    subject_id: str
    title: str
    # From the 'reranker complete' event, as the 'pipeline complete' event doesn't include it
    relevance_score: float | None = None
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
    # Keyed by code
    validation_error_counts: dict[str, int] = Field(default_factory=dict)
    validation_warning_counts: dict[str, int] = Field(default_factory=dict)
    mean_relevance_score: float | None = None


class AccuracyResult(StrEnum):
    """Whether results match the expected results, regardless of how the query's request was executed."""

    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    NOT_EVALUATED = "not_evaluated"


class Check(StrEnum):
    """What's checked of each expected dataset."""

    FOUND = "found"
    RANK = "rank"
    FILTERS = "filters"
    INDICATORS = "indicators"
    TIME_PERIOD = "time_period"
    LOCATIONS = "locations"


CHECK_NAMES = {
    Check.FOUND: "Found",
    Check.RANK: "Rank",
    Check.FILTERS: "Filters",
    Check.INDICATORS: "Indicators",
    Check.TIME_PERIOD: "Time period",
    Check.LOCATIONS: "Locations",
}


class SelectionAccuracy(StrictCamelModel):
    """Compares the selected values with the expected values, e.g. of the indicators, or of one filter.

    Selections pass on an exact match. Precision and recall show how close a selection that doesn't pass is."""

    passed: bool
    expected: list[str] = Field(default_factory=list)
    selected: list[str] = Field(default_factory=list)
    # Expected, but not selected
    missing: list[str] = Field(default_factory=list)
    # Selected, but not expected
    unexpected: list[str] = Field(default_factory=list)
    # Unset if nothing was selected
    precision: float | None = None
    # Unset if nothing was expected
    recall: float | None = None


class GroupedSelectionAccuracy(StrictCamelModel):
    """Compares selections which are grouped, e.g. filter items by filter, or locations by geographic level."""

    passed: bool
    precision: float | None = None
    recall: float | None = None
    # Keyed by filter label, or geographic level label
    groups: dict[str, SelectionAccuracy] = Field(default_factory=dict)


class TimePeriodAccuracy(StrictCamelModel):
    passed: bool
    expected: ExpectedTimePeriodRange
    selected: TimePeriodRange | None = None


class ExpectedDatasetAccuracy(StrictCamelModel):
    data_set_file_id: str
    # The title given in the gold standard file
    title: str | None = None
    required: bool
    result: AccuracyResult
    found: bool
    rank: int | None = None
    max_rank: int | None = None
    # Unset if no maximum rank is expected
    rank_passed: bool | None = None
    # Unset if no filters are expected, or if they couldn't be compared
    filters: GroupedSelectionAccuracy | None = None
    indicators: SelectionAccuracy | None = None
    time_period: TimePeriodAccuracy | None = None
    locations: GroupedSelectionAccuracy | None = None
    # Problems comparing the dataset, e.g. expected labels that don't exist in its subject meta
    problems: list[str] = Field(default_factory=list)

    def get_check_results(self) -> dict[Check, bool | None]:
        """Whether each check passed, or None if it wasn't evaluated."""
        return {
            Check.FOUND: self.found,
            Check.RANK: self.rank_passed,
            Check.FILTERS: self.filters.passed if self.filters is not None else None,
            Check.INDICATORS: self.indicators.passed if self.indicators is not None else None,
            Check.TIME_PERIOD: self.time_period.passed if self.time_period is not None else None,
            Check.LOCATIONS: self.locations.passed if self.locations is not None else None,
        }


class QueryAccuracy(StrictCamelModel):
    result: AccuracyResult
    author: str | None = None
    # Why the results weren't evaluated
    reason: str | None = None
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
    # The stage of the last event received
    last_stage: str | None = None
    http_status: int | None = None
    duration_seconds: float
    # Seconds from sending the request to receiving each stage's event, keyed by stage
    stage_timings: dict[str, float] = Field(default_factory=dict)
    confidence: str | None = None
    query_requirements: QueryRequirements | None = None
    # Unset if the pipeline didn't complete
    dataset_count: int | None = None
    token_usage: TokenUsage | None = None
    cost: float | None = None
    # Whether the token usage and cost are from an earlier stage, as the pipeline didn't complete
    cost_is_partial: bool
    dataset_summary: DatasetResultsSummary | None = None
    datasets: list[DatasetResult] = Field(default_factory=list)
    # Unset if the query has no expected results
    accuracy: QueryAccuracy | None = None
    raw_events: list[RawEvent] = Field(default_factory=list)


class DurationSummary(StrictCamelModel):
    mean_seconds: float
    p95_seconds: float
    max_seconds: float


class ExecutionSummary(StrictCamelModel):
    query_count: int
    status_counts: dict[ExecutionStatus, int]
    # Only queries which completed the pipeline, so that quick failures don't skew the durations
    completed_query_durations: DurationSummary | None = None
    token_usage: TokenUsage
    cost: float
    queries_with_partial_cost: int
    datasets: DatasetResultsSummary


class PassRate(StrictCamelModel):
    evaluated: int
    passed: int
    # Unset if nothing was evaluated
    pass_rate: float | None = None


class AccuracySummary(StrictCamelModel):
    """Aggregates the accuracy of the queries with expected results."""

    query_count: int
    result_counts: dict[AccuracyResult, int]
    # Keyed by who wrote the expected results, or 'unspecified'
    result_counts_by_author: dict[str, dict[AccuracyResult, int]] = Field(default_factory=dict)
    # Whether datasets were found is only evaluated for required datasets
    checks: dict[Check, PassRate]
    # Mean over evaluated queries of 1 / the rank of the highest ranked expected dataset found, or 0 if none were
    mean_reciprocal_rank: float | None = None
    problem_count: int


class IterationReport(StrictCamelModel):
    iteration: int
    duration_seconds: float
    summary: ExecutionSummary
    # Unset if none of the queries have expected results
    accuracy_summary: AccuracySummary | None = None
    # Queries not run because the maximum cost had been reached
    skipped_query_ids: list[str] = Field(default_factory=list)
    queries: list[QueryResult] = Field(default_factory=list)


class OutputAspect(StrEnum):
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
    inconsistent_aspects: list[OutputAspect] = Field(default_factory=list)
    # How each iteration differs from the first iteration that completed
    differences: list[str] = Field(default_factory=list)


class ConsistencySummary(StrictCamelModel):
    # Queries that ran in more than one iteration
    query_count: int
    consistent_count: int
    consistency_rate: float | None = None
    # Inconsistent queries, by what was inconsistent
    inconsistent_counts: dict[OutputAspect, int] = Field(default_factory=dict)


class RunConsistency(StrictCamelModel):
    summary: ConsistencySummary
    queries: list[QueryConsistency] = Field(default_factory=list)


class QueryChange(StrEnum):
    """How a query's results changed from the baseline."""

    REGRESSED = "regressed"
    IMPROVED = "improved"
    MIXED = "mixed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    NEW = "new"


class QueryComparison(StrictCamelModel):
    query_id: str
    change: QueryChange
    # The worst status and accuracy of the query in any iteration
    baseline_status: ExecutionStatus | None = None
    current_status: ExecutionStatus | None = None
    baseline_accuracy: AccuracyResult | None = None
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
    baseline: BaselineSource
    change_counts: dict[QueryChange, int]
    # Queries in both the run and the baseline, which the metrics are compared over
    metrics_query_count: int
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
    query_ids: list[str]
    # Requested, so more than ran if the maximum cost was reached
    iterations: int
    concurrency: int
    timeout_seconds: float
    max_cost: float | None = None
    budget_exceeded: bool
    # Set when the run replayed a previous report, so no tokens were used, and durations are meaningless
    replayed_from: ReplaySource | None = None


class RegressionReport(StrictCamelModel):
    run: RunMetadata
    summary: ExecutionSummary
    # Unset if none of the queries have expected results
    accuracy_summary: AccuracySummary | None = None
    # Unset unless a query ran in more than one iteration
    consistency: RunConsistency | None = None
    # Unset unless the run was compared with a baseline
    baseline_comparison: BaselineComparison | None = None
    iterations: list[IterationReport] = Field(default_factory=list)
