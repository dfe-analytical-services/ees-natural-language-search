"""Tests for comparing results with expected results in `tools.regression_tests.evaluator`."""

from typing import Any

import pytest

from schemas.ees_data_api.subject_meta_response import SubjectMetaResponse
from tools.regression_tests.evaluator import evaluate_query, evaluate_report
from tools.regression_tests.input_models import GoldStandardQuery
from tools.regression_tests.report_models import (
    AccuracyResult,
    DatasetResult,
    ExecutionStatus,
    IterationReport,
    QueryResult,
    RegressionReport,
    RunMetadata,
)
from tools.regression_tests.run_result import build_query_result
from tools.regression_tests.subject_meta import SubjectMetaUnavailableError, UnavailableSubjectMeta
from tools.regression_tests.summaries import summarise_queries

SUBJECT_ID = "test-subject-id"


def _subject_meta(
    filters: dict[str, list[str]] | None = None,
    indicators: list[str] | None = None,
    time_periods: list[tuple[str, int]] | None = None,
    locations: dict[str, dict[str, Any]] | None = None,
) -> SubjectMetaResponse:
    """Builds subject meta in the shape of the Data API's response. Filter item ids are '<filter label>:<item label>'.

    `locations` is keyed by geographic level, e.g. 'region', with the level's label and options as the value."""
    return SubjectMetaResponse.model_validate(
        {
            "filters": {
                filter_label: {
                    "id": filter_label,
                    "legend": filter_label,
                    "name": filter_label,
                    "options": {
                        "default": {
                            "id": f"{filter_label}-group",
                            "label": "Default",
                            "options": [
                                {"value": f"{filter_label}:{item_label}", "label": item_label}
                                for item_label in item_labels
                            ],
                        }
                    },
                }
                for filter_label, item_labels in (filters or {}).items()
            },
            "indicators": {
                "default": {
                    "id": "indicator-group",
                    "label": "Default",
                    "options": [
                        {"value": label, "label": label, "name": label} for label in indicators or []
                    ],
                }
            },
            "locations": locations or {},
            "timePeriod": {
                "options": [
                    {"code": code, "year": year, "label": f"{code} {year}"} for code, year in time_periods or []
                ]
            },
        }
    )


DEFAULT_SUBJECT_META = _subject_meta(
    filters={"School type": ["Total", "Primary", "Secondary"], "Characteristic": ["Total", "FSM eligible"]},
    indicators=["Overall absence rate", "Number of sessions"],
    time_periods=[("AY", 2023), ("AY", 2024)],
    locations={
        "country": {"legend": "National", "options": [{"id": "england", "label": "England", "value": "E92000001"}]},
        "region": {"legend": "Regional", "options": [{"id": "london", "label": "London", "value": "E12000007"}]},
        "localAuthority": {
            "legend": "Local authority",
            "options": [
                {
                    "label": "London",
                    "value": "E12000007",
                    "level": "region",
                    "options": [{"id": "camden", "label": "Camden", "value": "E09000007"}],
                }
            ],
        },
    },
)


class _FakeSubjectMeta:
    def __init__(self, subject_meta: SubjectMetaResponse = DEFAULT_SUBJECT_META):
        self.subject_meta = subject_meta

    def get(self, subject_id: str) -> SubjectMetaResponse:
        if subject_id != SUBJECT_ID:
            raise SubjectMetaUnavailableError(f"No subject meta for '{subject_id}'")
        return self.subject_meta


def _dataset(
    rank: int = 1,
    data_set_file_id: str = "data-set-file-1",
    filters: dict[str, list[str]] | None = None,
    indicators: list[str] | None = None,
    time_period: tuple[tuple[str, int], tuple[str, int]] | None = (("AY", 2024), ("AY", 2024)),
    locations: dict[str, list[str]] | None = None,
) -> DatasetResult:
    """Filters are keyed by filter label, and locations by geographic level label."""
    return DatasetResult.model_validate(
        {
            "rank": rank,
            "fileId": f"file-{rank}",
            "dataSetFileId": data_set_file_id,
            "subjectId": SUBJECT_ID,
            "title": "Test dataset",
            "isValidForTableGeneration": True,
            "filters": [
                {"id": f"{filter_label}:{item_label}", "label": item_label}
                for filter_label, item_labels in (filters or {}).items()
                for item_label in item_labels
            ],
            "indicators": [{"id": label, "label": label} for label in indicators or []],
            "timePeriod": (
                {
                    "start": {"code": time_period[0][0], "year": time_period[0][1]},
                    "end": {"code": time_period[1][0], "year": time_period[1][1]},
                }
                if time_period
                else None
            ),
            "geographicLevels": {
                level_label: [{"id": code, "label": code, "value": code} for code in codes]
                for level_label, codes in (locations or {"National": ["E92000001"]}).items()
            },
        }
    )


def _query(expected: dict | None, query_id: str = "test-query") -> GoldStandardQuery:
    return GoldStandardQuery.model_validate(
        {"id": query_id, "userQuery": "Test query", "publicationId": "test-publication-id", "expected": expected}
    )


def _result(
    datasets: list[DatasetResult], status: ExecutionStatus = ExecutionStatus.SUCCESS, query_id: str = "test-query"
) -> QueryResult:
    return QueryResult(
        query_id=query_id,
        user_query="Test query",
        publication_id="test-publication-id",
        status=status,
        duration_seconds=1,
        dataset_count=len(datasets),
        cost_is_partial=False,
        datasets=datasets,
    )


def _expected_dataset(**fields) -> dict:
    return {"dataSetFileId": "data-set-file-1", **fields}


def _evaluate(expected_datasets: list[dict], datasets: list[DatasetResult], subject_meta=None, **expected_fields):
    return evaluate_query(
        _query({"datasets": expected_datasets, **expected_fields}),
        _result(datasets),
        subject_meta or _FakeSubjectMeta(),
    )


def test_query_without_expected_results_is_not_evaluated():
    assert evaluate_query(_query(None), _result([_dataset()]), _FakeSubjectMeta()) is None


@pytest.mark.parametrize("status", [ExecutionStatus.SSE_ERROR, ExecutionStatus.TIMEOUT, ExecutionStatus.HTTP_ERROR])
def test_query_whose_pipeline_did_not_complete_is_not_evaluated(status):
    accuracy = evaluate_query(
        _query({"author": "developer", "datasets": [_expected_dataset()]}), _result([], status=status), _FakeSubjectMeta()
    )

    assert accuracy.result == AccuracyResult.NOT_EVALUATED
    assert accuracy.author == "developer"
    assert f"'{status}'" in accuracy.reason
    assert accuracy.datasets == []


def test_query_passes_when_every_expected_selection_matches_exactly():
    accuracy = _evaluate(
        [
            _expected_dataset(
                maxRank=1,
                filters={"School type": ["Secondary"]},
                indicators=["Overall absence rate"],
                timePeriod={"start": {"code": "AY", "year": 2024}, "end": {"code": "AY", "year": 2024}},
                locations={"National": ["E92000001"]},
            )
        ],
        [
            _dataset(
                filters={"School type": ["Secondary"], "Characteristic": ["Total"]},
                indicators=["Overall absence rate"],
            )
        ],
        minDatasets=1,
    )

    assert accuracy.result == AccuracyResult.PASS
    assert accuracy.min_datasets_passed
    [dataset] = accuracy.datasets
    assert dataset.result == AccuracyResult.PASS
    assert (dataset.found, dataset.rank, dataset.rank_passed) == (True, 1, True)
    assert dataset.filters.passed and dataset.indicators.passed and dataset.time_period.passed and dataset.locations.passed
    assert dataset.problems == []


def test_filters_are_compared_by_filter_and_only_for_the_expected_filters():
    [dataset] = _evaluate(
        [_expected_dataset(filters={"School type": ["Secondary"], "Characteristic": ["FSM eligible"]})],
        [_dataset(filters={"School type": ["Secondary", "Primary"], "Characteristic": ["Total"]})],
    ).datasets

    assert dataset.result == AccuracyResult.PARTIAL
    assert not dataset.filters.passed
    assert list(dataset.filters.groups) == ["School type", "Characteristic"]
    school_type = dataset.filters.groups["School type"]
    assert (school_type.passed, school_type.unexpected, school_type.precision, school_type.recall) == (
        False,
        ["Primary"],
        0.5,
        1.0,
    )
    characteristic = dataset.filters.groups["Characteristic"]
    assert (characteristic.missing, characteristic.unexpected, characteristic.recall) == (["FSM eligible"], ["Total"], 0.0)
    # 1 of the 3 selected filter items was expected, and 1 of the 2 expected filter items was selected
    assert (dataset.filters.precision, dataset.filters.recall) == (0.333, 0.5)


def test_a_filter_expected_to_be_any_accepts_any_selection():
    [dataset] = _evaluate(
        [_expected_dataset(filters={"School type": "*"})],
        [_dataset(filters={"School type": ["Total", "Primary", "Secondary"]})],
    ).datasets

    assert dataset.result == AccuracyResult.PASS
    school_type = dataset.filters.groups["School type"]
    assert school_type.passed
    assert school_type.expected == ["*"]
    assert school_type.selected == ["Primary", "Secondary", "Total"]
    assert (dataset.filters.precision, dataset.filters.recall) == (None, None)


def test_selected_filter_items_not_in_the_subject_meta_are_a_problem():
    dataset_result = _dataset(filters={"School type": ["Secondary"]})
    dataset_result.filters[0].id = "unknown-filter-item-id"

    [dataset] = _evaluate([_expected_dataset(filters={"School type": ["Secondary"]})], [dataset_result]).datasets

    assert not dataset.filters.passed
    assert dataset.filters.groups["School type"].missing == ["Secondary"]
    assert dataset.problems == [
        "The selected filter items 'Secondary' don't exist in the subject meta, e.g. because it has changed since the results were recorded"
    ]


def test_indicators_are_compared_exactly():
    [dataset] = _evaluate(
        [_expected_dataset(indicators=["Overall absence rate"])],
        [_dataset(indicators=["Overall absence rate", "Number of sessions"])],
    ).datasets

    assert dataset.result == AccuracyResult.PARTIAL
    indicators = dataset.indicators
    assert (indicators.passed, indicators.unexpected, indicators.precision, indicators.recall) == (
        False,
        ["Number of sessions"],
        0.5,
        1.0,
    )


def test_no_selected_indicators_has_no_precision():
    [dataset] = _evaluate([_expected_dataset(indicators=["Overall absence rate"])], [_dataset()]).datasets

    assert (dataset.indicators.passed, dataset.indicators.precision, dataset.indicators.recall) == (False, None, 0.0)


@pytest.mark.parametrize(
    "selected_time_period",
    [
        pytest.param((("AY", 2023), ("AY", 2024)), id="different_start"),
        pytest.param((("AY", 2024), ("CY", 2024)), id="different_code"),
        pytest.param(None, id="none_selected"),
    ],
)
def test_time_period_must_match_exactly(selected_time_period):
    [dataset] = _evaluate(
        [_expected_dataset(timePeriod={"start": {"code": "AY", "year": 2024}, "end": {"code": "AY", "year": 2024}})],
        [_dataset(time_period=selected_time_period)],
    ).datasets

    assert dataset.result == AccuracyResult.PARTIAL
    assert not dataset.time_period.passed


def test_locations_are_compared_across_every_selected_level_ignoring_empty_levels():
    [dataset] = _evaluate(
        [_expected_dataset(locations={"Regional": ["E12000007"]})],
        [_dataset(locations={"Regional": ["E12000007"], "Local authority": ["E09000001"], "National": []})],
    ).datasets

    assert not dataset.locations.passed
    assert list(dataset.locations.groups) == ["Regional", "Local authority"]
    assert dataset.locations.groups["Regional"].passed
    assert dataset.locations.groups["Local authority"].unexpected == ["E09000001"]
    assert (dataset.locations.precision, dataset.locations.recall) == (0.5, 1.0)


def test_expected_dataset_ranked_too_low_is_partial():
    [dataset] = _evaluate(
        [_expected_dataset(maxRank=1)],
        [_dataset(rank=1, data_set_file_id="other"), _dataset(rank=2)],
    ).datasets

    assert (dataset.rank, dataset.rank_passed, dataset.result) == (2, False, AccuracyResult.PARTIAL)


def test_missing_required_dataset_fails_the_query():
    accuracy = _evaluate([_expected_dataset(), _expected_dataset(dataSetFileId="missing")], [_dataset()])

    assert accuracy.result == AccuracyResult.FAIL
    assert [(dataset.found, dataset.result) for dataset in accuracy.datasets] == [
        (True, AccuracyResult.PASS),
        (False, AccuracyResult.FAIL),
    ]


def test_missing_dataset_that_is_not_required_is_ignored():
    accuracy = _evaluate([_expected_dataset(), _expected_dataset(dataSetFileId="optional", required=False)], [_dataset()])

    assert accuracy.result == AccuracyResult.PASS


def test_dataset_that_is_not_required_still_counts_when_found():
    accuracy = _evaluate(
        [_expected_dataset(), _expected_dataset(dataSetFileId="optional", required=False, indicators=["Overall absence rate"])],
        [_dataset(), _dataset(rank=2, data_set_file_id="optional")],
    )

    assert accuracy.result == AccuracyResult.PARTIAL


def test_too_few_datasets_without_any_expected_found_fails():
    accuracy = _evaluate([], [], minDatasets=1)

    assert (accuracy.min_datasets_passed, accuracy.result) == (False, AccuracyResult.FAIL)


def test_too_few_datasets_with_the_expected_found_is_partial():
    accuracy = _evaluate([_expected_dataset()], [_dataset()], minDatasets=2)

    assert (accuracy.min_datasets_passed, accuracy.result) == (False, AccuracyResult.PARTIAL)


def test_without_subject_meta_filters_are_not_compared():
    subject_meta = UnavailableSubjectMeta("No eesDataApiUrl")

    [dataset] = _evaluate(
        [_expected_dataset(filters={"School type": ["Secondary"]}, indicators=["Overall absence rate"])],
        [_dataset(filters={"School type": ["Secondary"]}, indicators=["Overall absence rate"])],
        subject_meta=subject_meta,
    ).datasets

    assert dataset.result == AccuracyResult.NOT_EVALUATED
    assert dataset.filters is None
    assert dataset.indicators.passed
    assert dataset.problems == ["No eesDataApiUrl", "The filters couldn't be compared without the subject meta"]


def test_without_subject_meta_other_failures_are_still_partial():
    [dataset] = _evaluate(
        [_expected_dataset(filters={"School type": ["Secondary"]}, indicators=["Overall absence rate"])],
        [_dataset()],
        subject_meta=UnavailableSubjectMeta("No eesDataApiUrl"),
    ).datasets

    assert dataset.result == AccuracyResult.PARTIAL


def test_expected_values_not_in_the_subject_meta_are_problems():
    [dataset] = _evaluate(
        [
            _expected_dataset(
                filters={"School type": ["Secondary", "Academy"], "Region": "*"},
                indicators=["Overall absence rate", "Absence rate"],
                timePeriod={"start": {"code": "AY", "year": 2020}, "end": {"code": "AY", "year": 2024}},
                locations={"Local authority": ["E09000007", "E09000001"], "Ward": ["X"]},
            )
        ],
        [_dataset()],
    ).datasets

    assert dataset.problems == [
        "The expected filter items 'Academy' don't exist in the filter 'School type'",
        "The expected filter 'Region' doesn't exist in the subject meta",
        "The expected indicators 'Absence rate' don't exist in the subject meta",
        "The expected start time period AY 2020 doesn't exist in the subject meta",
        "The expected locations 'E09000001' don't exist at the level 'Local authority'",
        "The expected geographic level 'Ward' doesn't exist in the subject meta",
    ]


def test_real_stream_against_real_subject_meta(query, load_json_fixture, build_execution):
    """The London query recorded in dev selects the City of London local authority, as well as the London region."""
    result = build_query_result(query, build_execution(load_json_fixture("nl_search_sse_success.json")))
    [dataset_result] = result.datasets
    subject_meta = SubjectMetaResponse.model_validate(load_json_fixture("subject_meta_persistent_absence.json"))
    dataset_result.subject_id = SUBJECT_ID

    accuracy = evaluate_query(
        _query(
            {
                "datasets": [
                    {
                        "dataSetFileId": dataset_result.data_set_file_id,
                        "maxRank": 1,
                        "filters": {"Education phase": ["Secondary"]},
                        "indicators": ["Persistent absence rate"],
                        "locations": {"Regional": ["E12000007"]},
                    }
                ]
            },
            query_id=query.id,
        ),
        result,
        _FakeSubjectMeta(subject_meta),
    )

    assert accuracy.result == AccuracyResult.PARTIAL
    [dataset] = accuracy.datasets
    assert dataset.filters.passed
    assert dataset.indicators.passed
    assert not dataset.locations.passed
    assert dataset.locations.groups["Local authority"].unexpected == ["E09000001"]
    assert dataset.problems == []


def test_evaluate_report_sets_the_accuracy_of_each_query_and_the_summaries():
    queries = [
        _query({"author": "developer", "datasets": [_expected_dataset()]}, query_id="query-1"),
        _query(None, query_id="query-2"),
    ]
    iterations = [
        IterationReport(
            iteration=iteration,
            duration_seconds=1,
            summary=summarise_queries(results),
            queries=results,
        )
        for iteration, results in (
            (1, [_result([_dataset()], query_id="query-1"), _result([_dataset()], query_id="query-2")]),
            (2, [_result([], query_id="query-1"), _result([_dataset()], query_id="query-2")]),
        )
    ]
    report = RegressionReport(
        run=RunMetadata(
            started_at="2026-09-29T14:29:44Z",
            finished_at="2026-09-29T14:29:44Z",
            environment_name="dev",
            base_url="https://dev",
            input_file="queries.json",
            input_file_sha256="test-sha256",
            query_ids=["query-1", "query-2"],
            iterations=2,
            concurrency=1,
            timeout_seconds=5,
            budget_exceeded=False,
        ),
        summary=summarise_queries([]),
        iterations=iterations,
    )

    evaluate_report(report, queries, _FakeSubjectMeta())

    assert [[result.accuracy and result.accuracy.result for result in it.queries] for it in report.iterations] == [
        [AccuracyResult.PASS, None],
        [AccuracyResult.FAIL, None],
    ]
    assert report.iterations[0].accuracy_summary.result_counts[AccuracyResult.PASS] == 1
    assert report.accuracy_summary.query_count == 2
    assert report.accuracy_summary.result_counts_by_author["developer"][AccuracyResult.FAIL] == 1
