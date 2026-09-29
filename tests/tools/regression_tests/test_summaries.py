"""Tests for aggregating results in `tools.regression_tests.summaries`."""

import pytest

from schemas.responses.final_dataset_response import (
    DatasetValidationError,
    DatasetValidationErrorCode,
    DatasetValidationWarning,
    DatasetValidationWarningCode,
)
from schemas.shared.token_usage import TokenUsage
from tools.regression_tests.report_models import (
    AccuracyResult,
    DatasetResult,
    ExecutionStatus,
    ExpectedDatasetAccuracy,
    QueryAccuracy,
    QueryResult,
    SelectionAccuracy,
)
from tools.regression_tests.summaries import (
    percentile,
    summarise_accuracy,
    summarise_datasets,
    summarise_queries,
)


def _dataset(
    relevance_score: float | None = 50,
    error_codes: list[DatasetValidationErrorCode] | None = None,
    warning_codes: list[DatasetValidationWarningCode] | None = None,
) -> DatasetResult:
    return DatasetResult(
        rank=1,
        file_id="file-id",
        data_set_file_id="data-set-file-id",
        subject_id="subject-id",
        title="Test dataset",
        relevance_score=relevance_score,
        is_valid_for_table_generation=not error_codes,
        validation_errors=[DatasetValidationError(code=code, message="") for code in error_codes or []],
        validation_warnings=[DatasetValidationWarning(code=code, message="") for code in warning_codes or []],
    )


def _query_result(
    status: ExecutionStatus = ExecutionStatus.SUCCESS,
    duration_seconds: float = 10,
    token_usage: TokenUsage | None = None,
    cost: float | None = 0.01,
    cost_is_partial: bool = False,
    datasets: list[DatasetResult] | None = None,
) -> QueryResult:
    return QueryResult(
        query_id="test-query",
        user_query="Test query",
        publication_id="test-publication-id",
        status=status,
        duration_seconds=duration_seconds,
        token_usage=token_usage or TokenUsage(input=1000, output=100),
        cost=cost,
        cost_is_partial=cost_is_partial,
        datasets=datasets or [],
    )


def test_summarise_datasets_counts_validity_and_codes():
    summary = summarise_datasets(
        [
            _dataset(relevance_score=90),
            _dataset(
                relevance_score=60,
                error_codes=[DatasetValidationErrorCode.NO_INDICATORS, DatasetValidationErrorCode.NO_LOCATION],
                warning_codes=[DatasetValidationWarningCode.UNFILTERED_FILTERS],
            ),
            _dataset(
                relevance_score=None,
                error_codes=[DatasetValidationErrorCode.NO_INDICATORS],
            ),
        ]
    )

    assert summary.dataset_count == 3
    assert summary.valid_for_table_generation_count == 1
    assert summary.with_validation_warnings_count == 1
    assert summary.validation_error_counts == {"no_indicators": 2, "no_location": 1}
    assert summary.validation_warning_counts == {"unfiltered_filters": 1}
    assert summary.mean_relevance_score == 75


def test_summarise_no_datasets():
    summary = summarise_datasets([])

    assert summary.dataset_count == 0
    assert summary.mean_relevance_score is None


def test_summarise_queries_counts_every_status():
    summary = summarise_queries(
        [
            _query_result(ExecutionStatus.SUCCESS),
            _query_result(ExecutionStatus.SUCCESS),
            _query_result(ExecutionStatus.TIMEOUT),
        ]
    )

    assert summary.query_count == 3
    assert summary.status_counts[ExecutionStatus.SUCCESS] == 2
    assert summary.status_counts[ExecutionStatus.TIMEOUT] == 1
    assert set(summary.status_counts) == set(ExecutionStatus)
    assert sum(summary.status_counts.values()) == 3


def test_summarise_queries_totals_tokens_and_cost_including_partial_costs():
    summary = summarise_queries(
        [
            _query_result(token_usage=TokenUsage(input=1000, output=100), cost=0.01),
            _query_result(
                ExecutionStatus.SSE_ERROR,
                token_usage=TokenUsage(input=200, output=20),
                cost=0.002,
                cost_is_partial=True,
            ),
            _query_result(ExecutionStatus.HTTP_ERROR, cost=None, cost_is_partial=True),
        ]
    )

    assert summary.token_usage == TokenUsage(input=2200, output=220)
    assert summary.cost == pytest.approx(0.012)
    assert summary.queries_with_partial_cost == 2


def test_summarise_queries_durations_only_include_completed_queries():
    summary = summarise_queries(
        [
            _query_result(ExecutionStatus.SUCCESS, duration_seconds=10),
            _query_result(ExecutionStatus.SUCCESS_WITH_VALIDATION_ERRORS, duration_seconds=20),
            _query_result(ExecutionStatus.HTTP_ERROR, duration_seconds=0.1),
        ]
    )

    assert summary.completed_query_durations.mean_seconds == 15
    assert summary.completed_query_durations.max_seconds == 20


def test_summarise_queries_without_completed_queries_has_no_durations():
    summary = summarise_queries([_query_result(ExecutionStatus.TIMEOUT)])

    assert summary.completed_query_durations is None


def test_summarise_queries_aggregates_datasets_across_queries():
    summary = summarise_queries(
        [
            _query_result(datasets=[_dataset(), _dataset()]),
            _query_result(datasets=[_dataset(error_codes=[DatasetValidationErrorCode.NO_TIME_PERIOD])]),
        ]
    )

    assert summary.datasets.dataset_count == 3
    assert summary.datasets.validation_error_counts == {"no_time_period": 1}


@pytest.mark.parametrize(
    "values, percent, expected",
    [
        pytest.param([5], 95, 5, id="single_value"),
        pytest.param([1, 2, 3, 4], 50, 2, id="median_of_even_count"),
        pytest.param(list(range(1, 21)), 95, 19, id="p95_of_20"),
        pytest.param([3, 1, 2], 100, 3, id="unordered_max"),
    ],
)
def test_percentile_is_nearest_rank(values, percent, expected):
    assert percentile(values, percent) == expected


def _accuracy(
    result: AccuracyResult,
    author: str | None = "developer",
    datasets: list[ExpectedDatasetAccuracy] | None = None,
) -> QueryAccuracy:
    return QueryAccuracy(result=result, author=author, datasets=datasets or [])


def _expected_dataset_accuracy(
    found: bool = True, rank: int | None = 1, required: bool = True, **aspects
) -> ExpectedDatasetAccuracy:
    return ExpectedDatasetAccuracy(
        data_set_file_id="data-set-file-id",
        required=required,
        result=AccuracyResult.PASS if found else AccuracyResult.FAIL,
        found=found,
        rank=rank if found else None,
        **aspects,
    )


def _with_accuracy(accuracy: QueryAccuracy | None) -> QueryResult:
    result = _query_result()
    result.accuracy = accuracy
    return result


def test_summarise_accuracy_without_expected_results_is_none():
    assert summarise_accuracy([_with_accuracy(None)]) is None


def test_summarise_accuracy_counts_results_overall_and_by_author():
    summary = summarise_accuracy(
        [
            _with_accuracy(_accuracy(AccuracyResult.PASS)),
            _with_accuracy(_accuracy(AccuracyResult.PARTIAL)),
            _with_accuracy(_accuracy(AccuracyResult.FAIL, author="product-owner")),
            _with_accuracy(_accuracy(AccuracyResult.NOT_EVALUATED, author=None)),
            _with_accuracy(None),
        ]
    )

    assert summary.query_count == 4
    assert summary.result_counts == {
        AccuracyResult.PASS: 1,
        AccuracyResult.PARTIAL: 1,
        AccuracyResult.FAIL: 1,
        AccuracyResult.NOT_EVALUATED: 1,
    }
    assert list(summary.result_counts_by_author) == ["developer", "product-owner", "unspecified"]
    assert summary.result_counts_by_author["developer"][AccuracyResult.PARTIAL] == 1
    assert summary.result_counts_by_author["unspecified"][AccuracyResult.NOT_EVALUATED] == 1


def test_summarise_accuracy_pass_rates_only_count_what_was_evaluated():
    passed_indicators = SelectionAccuracy(passed=True)
    failed_indicators = SelectionAccuracy(passed=False)
    summary = summarise_accuracy(
        [
            _with_accuracy(
                _accuracy(
                    AccuracyResult.PARTIAL,
                    datasets=[
                        _expected_dataset_accuracy(rank_passed=True, indicators=passed_indicators),
                        _expected_dataset_accuracy(rank=3, rank_passed=False, indicators=failed_indicators),
                        _expected_dataset_accuracy(found=False),
                        _expected_dataset_accuracy(found=False, required=False),
                    ],
                )
            )
        ]
    )

    assert (summary.required_datasets_found.passed, summary.required_datasets_found.evaluated) == (2, 3)
    assert summary.required_datasets_found.pass_rate == pytest.approx(0.667)
    assert (summary.rank.passed, summary.rank.evaluated) == (1, 2)
    assert (summary.indicators.passed, summary.indicators.evaluated, summary.indicators.pass_rate) == (1, 2, 0.5)
    assert (summary.filters.evaluated, summary.filters.pass_rate) == (0, None)


def test_summarise_accuracy_mean_reciprocal_rank_uses_the_highest_ranked_expected_dataset():
    summary = summarise_accuracy(
        [
            _with_accuracy(_accuracy(AccuracyResult.PASS, datasets=[_expected_dataset_accuracy(rank=1)])),
            _with_accuracy(
                _accuracy(
                    AccuracyResult.PARTIAL,
                    datasets=[_expected_dataset_accuracy(rank=4), _expected_dataset_accuracy(rank=2)],
                )
            ),
            _with_accuracy(_accuracy(AccuracyResult.FAIL, datasets=[_expected_dataset_accuracy(found=False)])),
            # Not evaluated, so not included
            _with_accuracy(_accuracy(AccuracyResult.NOT_EVALUATED)),
        ]
    )

    assert summary.mean_reciprocal_rank == pytest.approx((1 + 0.5 + 0) / 3, abs=0.001)


def test_summarise_accuracy_counts_problems():
    summary = summarise_accuracy(
        [
            _with_accuracy(
                _accuracy(
                    AccuracyResult.PARTIAL,
                    datasets=[_expected_dataset_accuracy(problems=["Problem 1", "Problem 2"])],
                )
            )
        ]
    )

    assert summary.problem_count == 2
