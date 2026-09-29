"""Aggregates query and dataset results into the summaries included in the report."""

import math
from collections import Counter
from collections.abc import Iterable
from statistics import mean

from schemas.shared.token_usage import TokenUsage
from tools.regression_tests.report_models import (
    COMPLETED_STATUSES,
    DatasetResult,
    DatasetResultsSummary,
    DurationSummary,
    ExecutionStatus,
    ExecutionSummary,
    QueryResult,
)

COST_DECIMAL_PLACES = 6
DURATION_DECIMAL_PLACES = 3


def summarise_datasets(datasets: Iterable[DatasetResult]) -> DatasetResultsSummary:
    datasets = list(datasets)
    relevance_scores = [
        dataset.relevance_score
        for dataset in datasets
        if dataset.relevance_score is not None
    ]

    return DatasetResultsSummary(
        dataset_count=len(datasets),
        valid_for_table_generation_count=sum(
            dataset.is_valid_for_table_generation for dataset in datasets
        ),
        with_validation_warnings_count=sum(
            bool(dataset.validation_warnings) for dataset in datasets
        ),
        validation_error_counts=_count_codes(
            error.code for dataset in datasets for error in dataset.validation_errors
        ),
        validation_warning_counts=_count_codes(
            warning.code
            for dataset in datasets
            for warning in dataset.validation_warnings
        ),
        mean_relevance_score=round(mean(relevance_scores), 2) if relevance_scores else None,
    )


def summarise_queries(query_results: list[QueryResult]) -> ExecutionSummary:
    status_counts = Counter(result.status for result in query_results)
    completed_durations = [
        result.duration_seconds
        for result in query_results
        if result.status in COMPLETED_STATUSES
    ]

    return ExecutionSummary(
        query_count=len(query_results),
        # Include every status, so that summaries can be compared status by status
        status_counts={status: status_counts[status] for status in ExecutionStatus},
        completed_query_durations=summarise_durations(completed_durations),
        token_usage=TokenUsage(
            input=sum(result.token_usage.input for result in query_results if result.token_usage),
            output=sum(result.token_usage.output for result in query_results if result.token_usage),
        ),
        cost=round(sum(result.cost or 0 for result in query_results), COST_DECIMAL_PLACES),
        queries_with_partial_cost=sum(result.cost_is_partial for result in query_results),
        datasets=summarise_datasets(
            dataset for result in query_results for dataset in result.datasets
        ),
    )


def summarise_durations(durations: list[float]) -> DurationSummary | None:
    if not durations:
        return None

    return DurationSummary(
        mean_seconds=round(mean(durations), DURATION_DECIMAL_PLACES),
        p95_seconds=round(percentile(durations, 95), DURATION_DECIMAL_PLACES),
        max_seconds=round(max(durations), DURATION_DECIMAL_PLACES),
    )


def percentile(values: list[float], percent: float) -> float:
    """The nearest-rank percentile, which is always one of the values, as the sample sizes are small."""
    ordered = sorted(values)
    rank = math.ceil(percent / 100 * len(ordered))
    return ordered[max(rank, 1) - 1]


def _count_codes(codes: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(str(code) for code in codes).items()))
