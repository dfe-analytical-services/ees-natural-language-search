"""Compares query results with the expected results in the gold standard file.

A selection passes only on an exact match with what's expected, and anything left unset in the expected results isn't
compared. Filters are compared filter by filter, and only for the filters that are expected, as every filter of a
dataset always has a selection. Locations are compared across every geographic level, so that a location selected at
a level that isn't expected is unexpected.
"""

from collections import defaultdict
from collections.abc import Iterable

from schemas.ees_data_api.subject_meta_response import LocationOption, SubjectMetaResponse
from schemas.responses.final_dataset_response import TimePeriodRange
from tools.regression_tests.input_models import (
    ANY_FILTER_ITEMS,
    ExpectedDataset,
    ExpectedTimePeriodRange,
    GoldStandardQuery,
)
from tools.regression_tests.report_models import (
    COMPLETED_STATUSES,
    AccuracyResult,
    DatasetResult,
    ExpectedDatasetAccuracy,
    GroupedSelectionAccuracy,
    QueryAccuracy,
    QueryResult,
    RegressionReport,
    SelectionAccuracy,
    TimePeriodAccuracy,
)
from tools.regression_tests.subject_meta import SubjectMetaSource, SubjectMetaUnavailableError
from tools.regression_tests.summaries import summarise_accuracy

RATIO_DECIMAL_PLACES = 3


def evaluate_report(
    report: RegressionReport, queries: list[GoldStandardQuery], subject_meta: SubjectMetaSource
) -> None:
    """Sets the accuracy of every query result in the report, and the accuracy summaries."""
    queries_by_id = {query.id: query for query in queries}
    for iteration in report.iterations:
        for result in iteration.queries:
            query = queries_by_id.get(result.query_id)
            result.accuracy = evaluate_query(query, result, subject_meta) if query else None
        iteration.accuracy_summary = summarise_accuracy(iteration.queries)

    report.accuracy_summary = summarise_accuracy(
        [result for iteration in report.iterations for result in iteration.queries]
    )


def evaluate_query(
    query: GoldStandardQuery, result: QueryResult, subject_meta: SubjectMetaSource
) -> QueryAccuracy | None:
    """Returns None if the query has no expected results."""
    expected = query.expected
    if expected is None:
        return None

    if result.status not in COMPLETED_STATUSES:
        return QueryAccuracy(
            result=AccuracyResult.NOT_EVALUATED,
            author=expected.author,
            reason=f"The pipeline didn't complete, with the status '{result.status}'",
            min_datasets=expected.min_datasets,
        )

    min_datasets_passed = (
        None if expected.min_datasets is None else len(result.datasets) >= expected.min_datasets
    )

    datasets_by_data_set_file_id: dict[str, DatasetResult] = {}
    for dataset in result.datasets:
        datasets_by_data_set_file_id.setdefault(dataset.data_set_file_id, dataset)

    dataset_accuracies = [
        evaluate_dataset(
            expected_dataset,
            datasets_by_data_set_file_id.get(expected_dataset.data_set_file_id),
            subject_meta,
        )
        for expected_dataset in expected.datasets
    ]

    return QueryAccuracy(
        result=_get_query_result(min_datasets_passed, dataset_accuracies),
        author=expected.author,
        min_datasets=expected.min_datasets,
        min_datasets_passed=min_datasets_passed,
        datasets=dataset_accuracies,
    )


def _get_query_result(
    min_datasets_passed: bool | None, datasets: list[ExpectedDatasetAccuracy]
) -> AccuracyResult:
    if any(dataset.required and not dataset.found for dataset in datasets):
        return AccuracyResult.FAIL
    if min_datasets_passed is False and not any(dataset.found for dataset in datasets):
        return AccuracyResult.FAIL

    # A dataset that isn't required only counts if it was found
    counted = [dataset for dataset in datasets if dataset.required or dataset.found]
    if min_datasets_passed is not False and all(
        dataset.result == AccuracyResult.PASS for dataset in counted
    ):
        return AccuracyResult.PASS
    return AccuracyResult.PARTIAL


def evaluate_dataset(
    expected: ExpectedDataset, dataset: DatasetResult | None, subject_meta: SubjectMetaSource
) -> ExpectedDatasetAccuracy:
    accuracy = ExpectedDatasetAccuracy(
        data_set_file_id=expected.data_set_file_id,
        title=expected.title,
        required=expected.required,
        result=AccuracyResult.FAIL,
        found=dataset is not None,
        max_rank=expected.max_rank,
    )
    if dataset is None:
        return accuracy

    accuracy.rank = dataset.rank
    if expected.max_rank is not None:
        accuracy.rank_passed = dataset.rank <= expected.max_rank

    meta: SubjectMetaResponse | None = None
    try:
        meta = subject_meta.get(dataset.subject_id)
    except SubjectMetaUnavailableError as e:
        accuracy.problems.append(str(e))

    filters_not_compared = False
    if expected.filters:
        if meta is None:
            accuracy.problems.append("The filters couldn't be compared without the subject meta")
            filters_not_compared = True
        else:
            accuracy.filters, unknown_filter_item_problems = _compare_filters(expected.filters, dataset, meta)
            accuracy.problems.extend(unknown_filter_item_problems)

    if expected.indicators:
        accuracy.indicators = compare_selections(
            expected.indicators, [indicator.label for indicator in dataset.indicators]
        )

    if expected.time_period is not None:
        accuracy.time_period = TimePeriodAccuracy(
            passed=_time_periods_match(expected.time_period, dataset.time_period),
            expected=expected.time_period,
            selected=dataset.time_period,
        )

    if expected.locations:
        accuracy.locations = compare_grouped_selections(
            expected.locations, _get_selected_locations(dataset), compare_unexpected_groups=True
        )

    if meta is not None:
        accuracy.problems.extend(find_unknown_expected_values(expected, meta))

    checks = [
        accuracy.rank_passed,
        *(
            aspect.passed
            for aspect in (accuracy.filters, accuracy.indicators, accuracy.time_period, accuracy.locations)
            if aspect is not None
        ),
    ]
    if not all(check for check in checks if check is not None):
        accuracy.result = AccuracyResult.PARTIAL
    elif filters_not_compared:
        accuracy.result = AccuracyResult.NOT_EVALUATED
    else:
        accuracy.result = AccuracyResult.PASS
    return accuracy


def compare_selections(expected: Iterable[str], selected: Iterable[str]) -> SelectionAccuracy:
    expected_values, selected_values = set(expected), set(selected)
    matched = expected_values & selected_values
    return SelectionAccuracy(
        passed=expected_values == selected_values,
        expected=sorted(expected_values),
        selected=sorted(selected_values),
        missing=sorted(expected_values - selected_values),
        unexpected=sorted(selected_values - expected_values),
        precision=_ratio(len(matched), len(selected_values)),
        recall=_ratio(len(matched), len(expected_values)),
    )


def compare_grouped_selections(
    expected: dict[str, list[str] | str],
    selected: dict[str, list[str]],
    compare_unexpected_groups: bool,
) -> GroupedSelectionAccuracy:
    """An expected group of '*' accepts any selection. Groups that are selected but not expected are only compared
    if `compare_unexpected_groups` is set, in which case nothing is expected of them."""
    labels = list(expected)
    if compare_unexpected_groups:
        labels += [label for label in selected if label not in expected]

    groups: dict[str, SelectionAccuracy] = {}
    compared: list[SelectionAccuracy] = []
    for label in labels:
        expected_values = expected.get(label, [])
        selected_values = selected.get(label, [])
        if expected_values == ANY_FILTER_ITEMS:
            groups[label] = SelectionAccuracy(
                passed=True, expected=[ANY_FILTER_ITEMS], selected=sorted(set(selected_values))
            )
        else:
            groups[label] = compare_selections(expected_values, selected_values)
            compared.append(groups[label])

    matched = sum(len(set(group.expected) & set(group.selected)) for group in compared)
    return GroupedSelectionAccuracy(
        passed=all(group.passed for group in groups.values()),
        precision=_ratio(matched, sum(len(group.selected) for group in compared)),
        recall=_ratio(matched, sum(len(group.expected) for group in compared)),
        groups=groups,
    )


def _compare_filters(
    expected_filters: dict[str, list[str] | str], dataset: DatasetResult, meta: SubjectMetaResponse
) -> tuple[GroupedSelectionAccuracy, list[str]]:
    # The selected filter items don't say which filter they belong to, so that's looked up in the subject meta
    filter_label_by_filter_item_id = {
        filter_item.id: filter_.label
        for filter_ in meta.filters.values()
        for filter_item_group in filter_.filter_item_groups.values()
        for filter_item in filter_item_group.filter_items
    }

    selected_by_filter: dict[str, list[str]] = defaultdict(list)
    unknown_filter_items: list[str] = []
    for filter_item in dataset.filters:
        filter_label = filter_label_by_filter_item_id.get(filter_item.id)
        if filter_label is None:
            unknown_filter_items.append(filter_item.label)
        else:
            selected_by_filter[filter_label].append(filter_item.label)

    problems = (
        [
            f"The selected filter items {_quote(unknown_filter_items)} don't exist in the subject meta, "
            "e.g. because it has changed since the results were recorded"
        ]
        if unknown_filter_items
        else []
    )
    return (
        compare_grouped_selections(expected_filters, selected_by_filter, compare_unexpected_groups=False),
        problems,
    )


def _get_selected_locations(dataset: DatasetResult) -> dict[str, list[str]]:
    """Location codes keyed by geographic level label, leaving out levels without any selected locations."""
    if dataset.geographic_levels is None:
        return {}
    return {
        level_label: [location.value for location in locations]
        for level_label, locations in dataset.geographic_levels.root.items()
        if locations
    }


def _time_periods_match(expected: ExpectedTimePeriodRange, selected: TimePeriodRange | None) -> bool:
    return (
        selected is not None
        and (selected.start.code, selected.start.year) == (expected.start.code, expected.start.year)
        and (selected.end.code, selected.end.year) == (expected.end.code, expected.end.year)
    )


def find_unknown_expected_values(expected: ExpectedDataset, meta: SubjectMetaResponse) -> list[str]:
    """Describes any expected values that don't exist in the dataset's subject meta, e.g. because they're misspelt,
    or because they changed with a new release, as they can never be selected."""
    problems: list[str] = []

    filter_item_labels_by_filter = {
        filter_.label: {
            filter_item.label
            for filter_item_group in filter_.filter_item_groups.values()
            for filter_item in filter_item_group.filter_items
        }
        for filter_ in meta.filters.values()
    }
    for filter_label, filter_item_labels in expected.filters.items():
        if filter_label not in filter_item_labels_by_filter:
            problems.append(f"The expected filter '{filter_label}' doesn't exist in the subject meta")
        elif filter_item_labels != ANY_FILTER_ITEMS:
            unknown = _unknown(filter_item_labels, filter_item_labels_by_filter[filter_label])
            if unknown:
                problems.append(f"The expected filter items {_quote(unknown)} don't exist in the filter '{filter_label}'")

    indicator_labels = {
        indicator.label for indicator_group in meta.indicators.values() for indicator in indicator_group.indicators
    }
    unknown_indicators = _unknown(expected.indicators, indicator_labels)
    if unknown_indicators:
        problems.append(f"The expected indicators {_quote(unknown_indicators)} don't exist in the subject meta")

    if expected.time_period is not None:
        time_periods = {(time_period.code, time_period.year) for time_period in meta.time_period.options}
        for name, time_period in (("start", expected.time_period.start), ("end", expected.time_period.end)):
            if (time_period.code, time_period.year) not in time_periods:
                problems.append(
                    f"The expected {name} time period {time_period.code} {time_period.year} doesn't exist in the subject meta"
                )

    location_codes_by_level = {
        location_level.label: _get_location_codes(location_level.options)
        for location_level in meta.locations.values()
    }
    for level_label, location_codes in expected.locations.items():
        if level_label not in location_codes_by_level:
            problems.append(f"The expected geographic level '{level_label}' doesn't exist in the subject meta")
        else:
            unknown = _unknown(location_codes, location_codes_by_level[level_label])
            if unknown:
                problems.append(f"The expected locations {_quote(unknown)} don't exist at the level '{level_label}'")

    return problems


def _get_location_codes(options: list[LocationOption]) -> set[str]:
    """Options that group other locations, e.g. local authorities by region, aren't themselves selectable."""
    codes: set[str] = set()
    for option in options:
        if option.options:
            codes |= _get_location_codes(option.options)
        else:
            codes.add(option.value)
    return codes


def _unknown(values: Iterable[str], known: set[str]) -> list[str]:
    return sorted(set(values) - known)


def _quote(values: Iterable[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, RATIO_DECIMAL_PLACES) if denominator else None
