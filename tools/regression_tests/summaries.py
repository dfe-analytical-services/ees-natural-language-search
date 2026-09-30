"""Aggregates query and dataset results into the summaries included in the report."""

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from statistics import mean

from schemas.shared.token_usage import TokenUsage
from tools.regression_tests.report_models import (
    COMPLETED_STATUSES,
    AccuracyResult,
    AccuracySummary,
    DatasetResult,
    DatasetResultsSummary,
    DurationSummary,
    ExecutionStatus,
    ExecutionSummary,
    PassRate,
    QueryAccuracy,
    QueryResult,
)

COST_DECIMAL_PLACES = 6
DURATION_DECIMAL_PLACES = 3
RATIO_DECIMAL_PLACES = 3
UNSPECIFIED_AUTHOR = "unspecified"


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


def summarise_accuracy(query_results: list[QueryResult]) -> AccuracySummary | None:
    """Returns None if none of the queries have expected results."""
    accuracies = [result.accuracy for result in query_results if result.accuracy is not None]
    if not accuracies:
        return None

    counts_by_author: dict[str, Counter] = defaultdict(Counter)
    for accuracy in accuracies:
        counts_by_author[accuracy.author or UNSPECIFIED_AUTHOR][accuracy.result] += 1

    datasets = [dataset for accuracy in accuracies for dataset in accuracy.datasets]
    found = [dataset for dataset in datasets if dataset.found]

    return AccuracySummary(
        query_count=len(accuracies),
        result_counts=_count_results(accuracy.result for accuracy in accuracies),
        result_counts_by_author={
            author: {result: counts[result] for result in AccuracyResult}
            for author, counts in sorted(counts_by_author.items())
        },
        required_datasets_found=_pass_rate(dataset.found for dataset in datasets if dataset.required),
        rank=_pass_rate(dataset.rank_passed for dataset in found if dataset.rank_passed is not None),
        filters=_pass_rate(dataset.filters.passed for dataset in found if dataset.filters is not None),
        indicators=_pass_rate(dataset.indicators.passed for dataset in found if dataset.indicators is not None),
        time_period=_pass_rate(dataset.time_period.passed for dataset in found if dataset.time_period is not None),
        locations=_pass_rate(dataset.locations.passed for dataset in found if dataset.locations is not None),
        mean_reciprocal_rank=_mean_reciprocal_rank(
            accuracy
            for accuracy in accuracies
            if accuracy.result != AccuracyResult.NOT_EVALUATED and accuracy.datasets
        ),
        problem_count=sum(len(dataset.problems) for dataset in datasets),
    )


def percentile(values: list[float], percent: float) -> float:
    """The nearest-rank percentile, which is always one of the values, as the sample sizes are small."""
    ordered = sorted(values)
    rank = math.ceil(percent / 100 * len(ordered))
    return ordered[max(rank, 1) - 1]


def _count_codes(codes: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(str(code) for code in codes).items()))


def _count_results(results: Iterable[AccuracyResult]) -> dict[AccuracyResult, int]:
    # Include every result, so that summaries can be compared result by result
    counts = Counter(results)
    return {result: counts[result] for result in AccuracyResult}


def _pass_rate(passed: Iterable[bool]) -> PassRate:
    passed = list(passed)
    return PassRate(
        evaluated=len(passed),
        passed=sum(passed),
        pass_rate=round(sum(passed) / len(passed), RATIO_DECIMAL_PLACES) if passed else None,
    )


def _mean_reciprocal_rank(accuracies: Iterable[QueryAccuracy]) -> float | None:
    reciprocal_ranks = [
        1 / min(ranks) if (ranks := [dataset.rank for dataset in accuracy.datasets if dataset.rank is not None]) else 0
        for accuracy in accuracies
    ]
    return round(mean(reciprocal_ranks), RATIO_DECIMAL_PLACES) if reciprocal_ranks else None
