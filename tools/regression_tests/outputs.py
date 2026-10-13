"""Describes what a query returned in a comparable form, and the differences between two of them, e.g. between two
iterations of a query, or between a run and its baseline.

Selections are described by labels and codes, rather than ids, so that results from different release versions of a
dataset can still be compared.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from schemas.responses.final_dataset_response import TimePeriodRange
from tools.regression_tests.input_models import ExpectedTimePeriodRange
from tools.regression_tests.report_models import DatasetResult, OutputAspect, QueryResult


@dataclass(frozen=True)
class DatasetOutput:
    data_set_file_id: str
    title: str
    filters: tuple[str, ...]
    """Filter item labels, including any repeated across filters, e.g. 'Total'."""
    indicators: tuple[str, ...]
    time_period: str
    locations: tuple[str, ...]
    """'<geographic level label>: <location code>'."""


@dataclass(frozen=True)
class OutputDifference:
    aspect: OutputAspect
    message: str


def get_outputs(result: QueryResult) -> list[DatasetOutput]:
    return [_get_dataset_output(dataset) for dataset in result.datasets]


def _get_dataset_output(dataset: DatasetResult) -> DatasetOutput:
    return DatasetOutput(
        data_set_file_id=dataset.data_set_file_id,
        title=dataset.title,
        filters=tuple(sorted(filter_item.label for filter_item in dataset.filters)),
        indicators=tuple(sorted(indicator.label for indicator in dataset.indicators)),
        time_period=format_time_period(dataset.time_period),
        locations=tuple(
            sorted(
                f"{level_label}: {location.value}"
                for level_label, locations in (
                    dataset.geographic_levels.root if dataset.geographic_levels else {}
                ).items()
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
                OutputAspect.DATASETS,
                f"Datasets {format_values(dataset.title for dataset in other)} "
                f"instead of {format_values(dataset.title for dataset in reference)}",
            )
        )

    reference_by_id = {dataset.data_set_file_id: dataset for dataset in reference}
    for dataset in other:
        reference_dataset = reference_by_id.get(dataset.data_set_file_id)
        if reference_dataset is None:
            continue

        for aspect, name, reference_values, values in (
            (OutputAspect.FILTERS, "Filter items", reference_dataset.filters, dataset.filters),
            (OutputAspect.INDICATORS, "Indicators", reference_dataset.indicators, dataset.indicators),
            (OutputAspect.LOCATIONS, "Locations", reference_dataset.locations, dataset.locations),
        ):
            change = _describe_change(reference_values, values)
            if change:
                differences.append(OutputDifference(aspect, f"{name} of '{dataset.title}': {change}"))

        if reference_dataset.time_period != dataset.time_period:
            differences.append(
                OutputDifference(
                    OutputAspect.TIME_PERIOD,
                    f"Time period of '{dataset.title}': {dataset.time_period} "
                    f"instead of {reference_dataset.time_period}",
                )
            )
    return differences


def _describe_change(reference: tuple[str, ...], values: tuple[str, ...]) -> str | None:
    reference_counts, counts = Counter(reference), Counter(values)
    added = sorted((counts - reference_counts).elements())
    removed = sorted((reference_counts - counts).elements())
    changes = []
    if added:
        changes.append(f"added {format_values(added)}")
    if removed:
        changes.append(f"removed {format_values(removed)}")
    return ", ".join(changes) or None


def format_time_period(time_period: TimePeriodRange | ExpectedTimePeriodRange | None) -> str:
    if time_period is None:
        return "none"
    start = f"{time_period.start.code} {time_period.start.year}"
    end = f"{time_period.end.code} {time_period.end.year}"
    return start if start == end else f"{start} to {end}"


def format_values(values: Iterable[str]) -> str:
    return ", ".join(f"'{value}'" for value in values) or "none"
