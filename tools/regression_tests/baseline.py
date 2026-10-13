"""Compares a run with a previous run, the baseline.

The baseline's results are rebuilt from its recorded events, so they're scored exactly like the run's.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tools.regression_tests.evaluator import evaluate_query
from tools.regression_tests.input_models import GoldStandardQuery
from tools.regression_tests.outputs import describe_differences, get_outputs
from tools.regression_tests.recorded_report import (
    RecordedReportError,
    get_query_key,
    get_recorded_queries,
    load_recorded_report,
    to_search_execution,
)
from tools.regression_tests.report_models import (
    CHECK_NAMES,
    COMPLETED_STATUSES,
    AccuracyResult,
    AccuracySummary,
    BaselineComparison,
    BaselineSource,
    Check,
    ExecutionStatus,
    ExecutionSummary,
    MetricComparison,
    QueryChange,
    QueryComparison,
    QueryResult,
    RegressionReport,
)
from tools.regression_tests.run_result import build_query_result
from tools.regression_tests.subject_meta import SubjectMetaSource
from tools.regression_tests.summaries import ratio, summarise_accuracy, summarise_queries

# Lower is better. Statuses where the pipeline didn't complete are all equally bad.
_STATUS_LEVELS = {ExecutionStatus.SUCCESS: 0, ExecutionStatus.SUCCESS_WITH_VALIDATION_ERRORS: 1}
_FAILED_STATUS_LEVEL = 2
# Not evaluated isn't better or worse than anything, so it isn't compared
_ACCURACY_LEVELS = {AccuracyResult.PASS: 0, AccuracyResult.PARTIAL: 1, AccuracyResult.FAIL: 2}


class BaselineError(Exception):
    pass


@dataclass
class Baseline:
    source: BaselineSource
    results_by_query_id: dict[str, list[QueryResult]]
    """The query's result in each iteration of the baseline that it ran in. Empty if it isn't in the baseline."""


def load_baseline(
    report_path: Path,
    report_file: str,
    queries: list[GoldStandardQuery],
    get_subject_meta: Callable[[str], SubjectMetaSource],
) -> Baseline:
    """`get_subject_meta` gets the subject meta source of an environment by name, to compare the baseline's results
    with the expected results."""
    try:
        recorded = load_recorded_report(report_path)
    except RecordedReportError as e:
        raise BaselineError(f"Unable to compare with the baseline: {e}") from e

    subject_meta = get_subject_meta(recorded.run.source_environment_name)
    recorded_queries = get_recorded_queries(recorded)

    results_by_query_id: dict[str, list[QueryResult]] = {}
    for query in queries:
        results = []
        for recorded_query in recorded_queries.get(get_query_key(query), []):
            if recorded_query is None:
                continue
            result = build_query_result(query, to_search_execution(recorded_query))
            result.accuracy = evaluate_query(query, result, subject_meta)
            results.append(result)
        results_by_query_id[query.id] = results

    return Baseline(
        source=BaselineSource(
            report_file=report_file,
            environment_name=recorded.run.source_environment_name,
            started_at=recorded.run.started_at,
        ),
        results_by_query_id=results_by_query_id,
    )


def compare_with_baseline(report: RegressionReport, baseline: Baseline) -> BaselineComparison:
    current_results_by_query_id: dict[str, list[QueryResult]] = {query_id: [] for query_id in report.run.query_ids}
    for iteration in report.iterations:
        for result in iteration.queries:
            current_results_by_query_id.setdefault(result.query_id, []).append(result)

    queries = [
        compare_query(query_id, baseline.results_by_query_id.get(query_id, []), results)
        for query_id, results in current_results_by_query_id.items()
        if results
    ]
    change_counts = Counter(query.change for query in queries)

    # Metrics are only compared over the queries in both, so that they aren't skewed by queries that are only in one
    common_query_ids = [
        query_id
        for query_id, results in current_results_by_query_id.items()
        if results and baseline.results_by_query_id.get(query_id)
    ]
    baseline_results = [result for query_id in common_query_ids for result in baseline.results_by_query_id[query_id]]
    current_results = [result for query_id in common_query_ids for result in current_results_by_query_id[query_id]]
    return BaselineComparison(
        baseline=baseline.source,
        change_counts={change: change_counts[change] for change in QueryChange},
        metrics_query_count=len(common_query_ids),
        metrics=_compare_metrics(
            summarise_queries(baseline_results),
            summarise_accuracy(baseline_results),
            summarise_queries(current_results),
            summarise_accuracy(current_results),
        ),
        queries=queries,
    )


def compare_query(
    query_id: str, baseline_results: list[QueryResult], current_results: list[QueryResult]
) -> QueryComparison:
    current_status = _get_worst_status(current_results)
    current_accuracy = _get_worst_accuracy(current_results)
    if not baseline_results:
        return QueryComparison(
            query_id=query_id,
            change=QueryChange.NEW,
            current_status=current_status,
            current_accuracy=current_accuracy,
        )

    baseline_status = _get_worst_status(baseline_results)
    baseline_accuracy = _get_worst_accuracy(baseline_results)
    worse = better = False
    differences: list[str] = []

    if baseline_status != current_status:
        differences.append(f"Status: {baseline_status} -> {current_status}")
        worse |= _get_status_level(current_status) > _get_status_level(baseline_status)
        better |= _get_status_level(current_status) < _get_status_level(baseline_status)

    if (
        baseline_accuracy in _ACCURACY_LEVELS
        and current_accuracy in _ACCURACY_LEVELS
        and baseline_accuracy != current_accuracy
    ):
        differences.append(f"Accuracy: {baseline_accuracy} -> {current_accuracy}")
        worse |= _ACCURACY_LEVELS[current_accuracy] > _ACCURACY_LEVELS[baseline_accuracy]
        better |= _ACCURACY_LEVELS[current_accuracy] < _ACCURACY_LEVELS[baseline_accuracy]

    baseline_checks, current_checks = _get_check_outcomes(baseline_results), _get_check_outcomes(current_results)
    for key, (title, current_passed) in current_checks.items():
        if key not in baseline_checks or baseline_checks[key][1] == current_passed:
            continue
        _, check = key
        differences.append(
            f"{CHECK_NAMES[check]} of '{title}': "
            f"{_format_passed(baseline_checks[key][1])} -> {_format_passed(current_passed)}"
        )
        worse |= not current_passed
        better |= current_passed

    # Different datasets or selections are only worse or better if they changed the outcome of a check
    baseline_completed = _get_first_completed(baseline_results)
    current_completed = _get_first_completed(current_results)
    if baseline_completed and current_completed:
        for difference in describe_differences(get_outputs(baseline_completed), get_outputs(current_completed)):
            differences.append(difference.message)

    if worse and better:
        change = QueryChange.MIXED
    elif worse:
        change = QueryChange.REGRESSED
    elif better:
        change = QueryChange.IMPROVED
    elif differences:
        change = QueryChange.CHANGED
    else:
        change = QueryChange.UNCHANGED

    return QueryComparison(
        query_id=query_id,
        change=change,
        baseline_status=baseline_status,
        current_status=current_status,
        baseline_accuracy=baseline_accuracy,
        current_accuracy=current_accuracy,
        differences=differences,
    )


def _get_status_level(status: ExecutionStatus) -> int:
    return _STATUS_LEVELS.get(status, _FAILED_STATUS_LEVEL)


def _get_worst_status(results: list[QueryResult]) -> ExecutionStatus:
    return max((result.status for result in results), key=_get_status_level)


def _get_worst_accuracy(results: list[QueryResult]) -> AccuracyResult | None:
    accuracies = [result.accuracy.result for result in results if result.accuracy]
    evaluated = [accuracy for accuracy in accuracies if accuracy in _ACCURACY_LEVELS]
    if evaluated:
        return max(evaluated, key=_ACCURACY_LEVELS.__getitem__)
    return accuracies[0] if accuracies else None


def _get_check_outcomes(results: list[QueryResult]) -> dict[tuple[str, Check], tuple[str, bool]]:
    """Keyed by (data set file id, check). The value is the dataset's title, and whether the check passed in every
    iteration it was evaluated in."""
    outcomes: dict[tuple[str, Check], tuple[str, bool]] = {}
    for result in results:
        if not result.accuracy:
            continue
        for dataset in result.accuracy.datasets:
            for check, passed in dataset.get_check_results().items():
                if passed is None:
                    continue
                key = (dataset.data_set_file_id, check)
                previously_passed = outcomes[key][1] if key in outcomes else True
                outcomes[key] = (dataset.title or dataset.data_set_file_id, previously_passed and passed)
    return outcomes


def _get_first_completed(results: list[QueryResult]) -> QueryResult | None:
    return next((result for result in results if result.status in COMPLETED_STATUSES), None)


def _compare_metrics(
    baseline_summary: ExecutionSummary,
    baseline_accuracy: AccuracySummary | None,
    current_summary: ExecutionSummary,
    current_accuracy: AccuracySummary | None,
) -> list[MetricComparison]:
    def completed_rate(summary: ExecutionSummary) -> float | None:
        completed = sum(summary.status_counts[status] for status in COMPLETED_STATUSES)
        return ratio(completed, summary.query_count)

    def accuracy_pass_rate(accuracy: AccuracySummary | None) -> float | None:
        if accuracy is None:
            return None
        evaluated = accuracy.query_count - accuracy.result_counts[AccuracyResult.NOT_EVALUATED]
        return ratio(accuracy.result_counts[AccuracyResult.PASS], evaluated)

    def check_pass_rate(accuracy: AccuracySummary | None, check: Check) -> float | None:
        return accuracy.checks[check].pass_rate if accuracy else None

    def mean_cost(summary: ExecutionSummary) -> float | None:
        return round(summary.cost / summary.query_count, 6) if summary.query_count else None

    def mean_duration(summary: ExecutionSummary) -> float | None:
        return summary.completed_query_durations.mean_seconds if summary.completed_query_durations else None

    metrics = [
        MetricComparison(
            name="Queries completed",
            unit="rate",
            baseline=completed_rate(baseline_summary),
            current=completed_rate(current_summary),
        ),
        MetricComparison(
            name="Queries passing accuracy",
            unit="rate",
            baseline=accuracy_pass_rate(baseline_accuracy),
            current=accuracy_pass_rate(current_accuracy),
        ),
    ]
    for check in Check:
        metrics.append(
            MetricComparison(
                name=f"{CHECK_NAMES[check]} pass rate",
                unit="rate",
                baseline=check_pass_rate(baseline_accuracy, check),
                current=check_pass_rate(current_accuracy, check),
            )
        )
    metrics += [
        MetricComparison(
            name="Mean cost per query",
            unit="cost",
            baseline=mean_cost(baseline_summary),
            current=mean_cost(current_summary),
        ),
        MetricComparison(
            name="Mean duration of completed queries",
            unit="seconds",
            baseline=mean_duration(baseline_summary),
            current=mean_duration(current_summary),
        ),
    ]
    return metrics


def _format_passed(passed: bool) -> str:
    return "passed" if passed else "failed"
