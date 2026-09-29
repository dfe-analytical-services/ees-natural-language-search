"""Assesses whether each query returned the same results in every iteration of a run.

The service calls Azure OpenAI with a temperature of 0 and a fixed seed, but that isn't fully deterministic, so the same
query can return different results from one iteration to the next.
"""

from collections import defaultdict

from tools.regression_tests.outputs import describe_differences, get_outputs
from tools.regression_tests.report_models import (
    COMPLETED_STATUSES,
    ConsistencyAspect,
    ConsistencySummary,
    QueryConsistency,
    QueryResult,
    RegressionReport,
    RunConsistency,
)

RATIO_DECIMAL_PLACES = 3


def assess_consistency(report: RegressionReport) -> RunConsistency | None:
    """Returns None unless a query ran in more than one iteration."""
    runs_by_query_id: dict[str, list[tuple[int, QueryResult]]] = defaultdict(list)
    for iteration in report.iterations:
        for result in iteration.queries:
            runs_by_query_id[result.query_id].append((iteration.iteration, result))

    queries = [
        assess_query_consistency(query_id, runs) for query_id, runs in runs_by_query_id.items() if len(runs) > 1
    ]
    if not queries:
        return None

    consistent_count = sum(query.consistent for query in queries)
    return RunConsistency(
        summary=ConsistencySummary(
            query_count=len(queries),
            consistent_count=consistent_count,
            consistency_rate=round(consistent_count / len(queries), RATIO_DECIMAL_PLACES),
            inconsistent_counts={
                aspect: sum(aspect in query.inconsistent_aspects for query in queries)
                for aspect in ConsistencyAspect
            },
        ),
        queries=queries,
    )


def assess_query_consistency(query_id: str, runs: list[tuple[int, QueryResult]]) -> QueryConsistency:
    """`runs` holds the result of the query in each iteration it ran in, with the iteration number."""
    aspects: set[ConsistencyAspect] = set()
    differences: list[str] = []

    statuses = [(iteration, result.status) for iteration, result in runs]
    if len({status for _, status in statuses}) > 1:
        aspects.add(ConsistencyAspect.STATUS)
        differences.append(f"Statuses: {_format_by_iteration(statuses)}")

    accuracies = [(iteration, result.accuracy.result) for iteration, result in runs if result.accuracy]
    if len({accuracy for _, accuracy in accuracies}) > 1:
        aspects.add(ConsistencyAspect.ACCURACY)
        differences.append(f"Accuracy: {_format_by_iteration(accuracies)}")

    # Results can only be compared between iterations where the pipeline completed
    completed = [(iteration, result) for iteration, result in runs if result.status in COMPLETED_STATUSES]
    if len(completed) > 1:
        reference_iteration, reference_result = completed[0]
        reference = get_outputs(reference_result)
        for iteration, result in completed[1:]:
            for difference in describe_differences(reference, get_outputs(result)):
                aspects.add(difference.aspect)
                differences.append(
                    f"Iteration {iteration}, compared with iteration {reference_iteration}: {difference.message}"
                )

    return QueryConsistency(
        query_id=query_id,
        iterations=len(runs),
        consistent=not aspects,
        inconsistent_aspects=[aspect for aspect in ConsistencyAspect if aspect in aspects],
        differences=differences,
    )


def _format_by_iteration(values: list[tuple[int, str]]) -> str:
    return ", ".join(f"iteration {iteration} {value}" for iteration, value in values)
