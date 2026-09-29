"""Describes what a query returned in a comparable form, and the differences between two of them, e.g. between two
iterations of a query, or between a run and its baseline.

Selections are described by labels and codes, rather than ids, so that results from different release versions of a
dataset can still be compared.
"""

from collections import Counter
from dataclasses import dataclass

from tools.regression_tests.report_models import ConsistencyAspect, DatasetResult, QueryResult


@dataclass(frozen=True)
class DatasetOutput:
    data_set_file_id: str
    title: str
    filters: tuple[str, ...]
    """Filter item labels, including any repeated across filters, e.g. 'Total'."""
    indicators: tuple[str, ...]
    time_period: str | None
    locations: tuple[str, ...]
    """'<geographic level label>: <location code>'."""


@dataclass(frozen=True)
class OutputDifference:
    aspect: ConsistencyAspect
    message: str


def get_outputs(result: QueryResult) -> list[DatasetOutput]:
    return [_get_dataset_output(dataset) for dataset in result.datasets]


def _get_dataset_output(dataset: DatasetResult) -> DatasetOutput:
    time_period = None
    if dataset.time_period:
        start = f"{dataset.time_period.start.code} {dataset.time_period.start.year}"
        end = f"{dataset.time_period.end.code} {dataset.time_period.end.year}"
        time_period = start if start == end else f"{start} to {end}"

    return DatasetOutput(
        data_set_file_id=dataset.data_set_file_id,
        title=dataset.title,
        filters=tuple(sorted(filter_item.label for filter_item in dataset.filters)),
        indicators=tuple(sorted(indicator.label for indicator in dataset.indicators)),
        time_period=time_period,
        locations=tuple(
            sorted(
                f"{level_label}: {location.value}"
                for level_label, locations in (dataset.geographic_levels.root if dataset.geographic_levels else {}).items()
                for location in locations
            )
        ),
    )


def describe_differences(reference: list[DatasetOutput], other: list[DatasetOutput]) -> list[OutputDifference]:
    """Describes how `other` differs from `reference`."""
    differences: list[OutputDifference] = []

    if [dataset.data_set_file_id for dataset in reference] != [dataset.data_set_file_id for dataset in other]:
        differences.append(
            OutputDifference(
                ConsistencyAspect.DATASETS,
                f"Datasets {_format_titles(other)} instead of {_format_titles(reference)}",
            )
        )

    reference_by_id = {dataset.data_set_file_id: dataset for dataset in reference}
    for dataset in other:
        reference_dataset = reference_by_id.get(dataset.data_set_file_id)
        if reference_dataset is None:
            continue

        for aspect, name, reference_values, values in (
            (ConsistencyAspect.FILTERS, "Filter items", reference_dataset.filters, dataset.filters),
            (ConsistencyAspect.INDICATORS, "Indicators", reference_dataset.indicators, dataset.indicators),
            (ConsistencyAspect.LOCATIONS, "Locations", reference_dataset.locations, dataset.locations),
        ):
            change = _describe_change(reference_values, values)
            if change:
                differences.append(OutputDifference(aspect, f"{name} of '{dataset.title}': {change}"))

        if reference_dataset.time_period != dataset.time_period:
            differences.append(
                OutputDifference(
                    ConsistencyAspect.TIME_PERIOD,
                    f"Time period of '{dataset.title}': {dataset.time_period or 'none'} "
                    f"instead of {reference_dataset.time_period or 'none'}",
                )
            )
    return differences


def _describe_change(reference: tuple[str, ...], values: tuple[str, ...]) -> str | None:
    reference_counts, counts = Counter(reference), Counter(values)
    added = sorted((counts - reference_counts).elements())
    removed = sorted((reference_counts - counts).elements())
    changes = []
    if added:
        changes.append(f"added {_format_values(added)}")
    if removed:
        changes.append(f"removed {_format_values(removed)}")
    return ", ".join(changes) or None


def _format_titles(datasets: list[DatasetOutput]) -> str:
    return _format_values([dataset.title for dataset in datasets]) if datasets else "none"


def _format_values(values: list[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)
