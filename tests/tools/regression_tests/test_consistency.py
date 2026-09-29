"""Tests for assessing consistency across iterations in `tools.regression_tests.consistency`, and describing
differences between results in `tools.regression_tests.outputs`."""

from tools.regression_tests.consistency import assess_consistency, assess_query_consistency
from tools.regression_tests.outputs import describe_differences, get_outputs
from tools.regression_tests.report_models import (
    AccuracyResult,
    ConsistencyAspect,
    ExecutionStatus,
    IterationReport,
    QueryAccuracy,
    RegressionReport,
    RunMetadata,
)
from tools.regression_tests.summaries import summarise_queries


def _report(*iterations: list) -> RegressionReport:
    return RegressionReport(
        run=RunMetadata(
            started_at="2026-09-29T14:29:44Z",
            finished_at="2026-09-29T14:29:44Z",
            environment_name="dev",
            base_url="https://dev",
            input_file="queries.json",
            input_file_sha256="test-sha256",
            query_ids=[],
            iterations=len(iterations),
            concurrency=1,
            timeout_seconds=5,
            budget_exceeded=False,
        ),
        summary=summarise_queries([]),
        iterations=[
            IterationReport(iteration=number, duration_seconds=1, summary=summarise_queries(results), queries=results)
            for number, results in enumerate(iterations, start=1)
        ],
    )


def test_a_single_iteration_has_no_consistency(build_result):
    assert assess_consistency(_report([build_result()])) is None


def test_identical_iterations_are_consistent(build_result, build_dataset_result):
    report = _report(
        [build_result(datasets=[build_dataset_result()])],
        [build_result(datasets=[build_dataset_result()])],
        [build_result(datasets=[build_dataset_result()])],
    )

    consistency = assess_consistency(report)

    [query] = consistency.queries
    assert (query.query_id, query.iterations, query.consistent, query.differences) == ("query-1", 3, True, [])
    assert (consistency.summary.query_count, consistency.summary.consistent_count) == (1, 1)
    assert consistency.summary.consistency_rate == 1.0
    assert set(consistency.summary.inconsistent_counts.values()) == {0}


def test_differences_in_selections_are_described_by_iteration(build_result, build_dataset_result):
    runs = [
        (1, build_result(datasets=[build_dataset_result()])),
        (2, build_result(datasets=[build_dataset_result(indicators=("Overall absence rate", "Number of sessions"))])),
        (3, build_result(datasets=[build_dataset_result(time_period=("AY", 2023, "AY", 2024))])),
    ]

    consistency = assess_query_consistency("query-1", runs)

    assert not consistency.consistent
    assert consistency.inconsistent_aspects == [ConsistencyAspect.INDICATORS, ConsistencyAspect.TIME_PERIOD]
    assert consistency.differences == [
        "Iteration 2, compared with iteration 1: Indicators of 'Dataset 1': added 'Number of sessions'",
        "Iteration 3, compared with iteration 1: Time period of 'Dataset 1': AY 2023 to AY 2024 instead of AY 2024",
    ]


def test_differences_in_status_and_accuracy_are_described(build_result, build_dataset_result):
    runs = [
        (1, build_result(accuracy=QueryAccuracy(result=AccuracyResult.PASS))),
        (2, build_result(status=ExecutionStatus.SSE_ERROR, accuracy=QueryAccuracy(result=AccuracyResult.NOT_EVALUATED))),
    ]

    consistency = assess_query_consistency("query-1", runs)

    assert consistency.inconsistent_aspects == [ConsistencyAspect.STATUS, ConsistencyAspect.ACCURACY]
    assert consistency.differences == [
        "Statuses: iteration 1 success, iteration 2 sse_error",
        "Accuracy: iteration 1 pass, iteration 2 not_evaluated",
    ]


def test_results_are_only_compared_between_iterations_that_completed(build_result, build_dataset_result):
    runs = [
        (1, build_result(status=ExecutionStatus.TIMEOUT)),
        (2, build_result(datasets=[build_dataset_result()])),
        (3, build_result(datasets=[build_dataset_result(filters=("Primary",))])),
    ]

    consistency = assess_query_consistency("query-1", runs)

    assert consistency.inconsistent_aspects == [ConsistencyAspect.STATUS, ConsistencyAspect.FILTERS]
    assert (
        "Iteration 3, compared with iteration 2: Filter items of 'Dataset 1': added 'Primary', removed 'Total'"
        in consistency.differences
    )


def test_summary_counts_inconsistent_queries_by_aspect(build_result, build_dataset_result):
    report = _report(
        [
            build_result("query-1", datasets=[build_dataset_result()]),
            build_result("query-2", datasets=[build_dataset_result()]),
        ],
        [
            build_result("query-1", datasets=[build_dataset_result()]),
            build_result("query-2", datasets=[build_dataset_result(locations={"Regional": ["E12000007"]})]),
        ],
    )

    summary = assess_consistency(report).summary

    assert (summary.query_count, summary.consistent_count, summary.consistency_rate) == (2, 1, 0.5)
    assert summary.inconsistent_counts[ConsistencyAspect.LOCATIONS] == 1
    assert summary.inconsistent_counts[ConsistencyAspect.FILTERS] == 0


def test_different_datasets_are_described_by_title(build_result, build_dataset_result):
    reference = get_outputs(build_result(datasets=[build_dataset_result()]))
    other = get_outputs(
        build_result(
            datasets=[
                build_dataset_result("data-set-file-2", "Dataset 2"),
                build_dataset_result(rank=2),
            ]
        )
    )

    differences = describe_differences(reference, other)

    assert [(difference.aspect, difference.message) for difference in differences] == [
        (ConsistencyAspect.DATASETS, "Datasets 'Dataset 2', 'Dataset 1' instead of 'Dataset 1'"),
    ]


def test_filter_items_repeated_across_filters_are_counted(build_result, build_dataset_result):
    reference = get_outputs(build_result(datasets=[build_dataset_result(filters=("Total", "Total"))]))
    other = get_outputs(build_result(datasets=[build_dataset_result(filters=("Total",))]))

    [difference] = describe_differences(reference, other)

    assert difference.message == "Filter items of 'Dataset 1': removed 'Total'"


def test_no_datasets_are_described_as_none(build_result, build_dataset_result):
    reference = get_outputs(build_result(datasets=[build_dataset_result()]))

    [difference] = describe_differences(reference, [])

    assert difference.message == "Datasets none instead of 'Dataset 1'"
