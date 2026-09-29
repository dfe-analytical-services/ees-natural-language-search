"""Tests for loading and selecting gold standard queries in `tools.regression_tests.input_models`."""

import json
from pathlib import Path

import pytest

from tools.regression_tests.__main__ import DEFAULT_INPUT_FILE
from tools.regression_tests.input_models import (
    GoldStandard,
    GoldStandardFileError,
    load_gold_standard,
)


def _query(query_id: str, **fields) -> dict:
    return {"id": query_id, "userQuery": "Test query", "publicationId": "test-publication-id", **fields}


def _write_gold_standard(tmp_path: Path, content: dict | str) -> Path:
    path = tmp_path / "queries.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return path


def _load_problems(tmp_path: Path, content: dict | str) -> list[str]:
    with pytest.raises(GoldStandardFileError) as error:
        load_gold_standard(_write_gold_standard(tmp_path, content))
    return error.value.problems


def test_default_gold_standard_file_is_valid():
    assert load_gold_standard(DEFAULT_INPUT_FILE).queries


def test_expected_results_are_loaded(tmp_path):
    gold_standard = load_gold_standard(
        _write_gold_standard(
            tmp_path,
            {
                "queries": [
                    _query(
                        "query-1",
                        expected={
                            "minDatasets": 1,
                            "datasets": [
                                {
                                    "dataSetFileId": "data-set-file-1",
                                    "maxRank": 2,
                                    "filters": {"School type": ["State-funded secondary"], "Reason": "*"},
                                    "indicators": ["Overall absence rate"],
                                    "timePeriod": {
                                        "start": {"code": "AY", "year": 2023},
                                        "end": {"code": "AY", "year": 2023},
                                    },
                                    "locations": {"Regional": ["E12000007"]},
                                }
                            ],
                        },
                    )
                ]
            },
        )
    )

    expected_dataset = gold_standard.queries[0].expected.datasets[0]
    assert expected_dataset.required
    assert expected_dataset.filters == {"School type": ["State-funded secondary"], "Reason": "*"}
    assert expected_dataset.time_period.start.year == 2023


def test_invalid_json_reports_where_it_is_invalid(tmp_path):
    problems = _load_problems(tmp_path, '{"queries": [}')

    assert problems == ["Invalid JSON at line 1, column 14: Expecting value"]


def test_unknown_field_is_reported_with_the_query_id(tmp_path):
    problems = _load_problems(
        tmp_path,
        {"queries": [_query("query-1", expected={"datasets": [{"dataSetFileId": "a", "indicatiors": []}]})]},
    )

    assert problems == [
        "Query 'query-1', field 'expected.datasets.0.indicatiors': Extra inputs are not permitted"
    ]


def test_query_without_an_id_is_reported_by_index(tmp_path):
    problems = _load_problems(tmp_path, {"queries": [{"userQuery": "Test query", "publicationId": "p"}]})

    assert problems == ["Query at index 0, field 'id': Field required"]


def test_filter_items_must_be_a_list_or_any(tmp_path):
    problems = _load_problems(
        tmp_path,
        {"queries": [_query("query-1", expected={"datasets": [{"dataSetFileId": "a", "filters": {"Reason": "all"}}]})]},
    )

    assert problems
    assert all(problem.startswith("Query 'query-1', field 'expected.datasets.0.filters.Reason") for problem in problems)


def test_duplicate_query_ids_are_reported(tmp_path):
    problems = _load_problems(tmp_path, {"queries": [_query("query-1"), _query("query-1")]})

    assert problems == ["Value error, Query ids must be unique, duplicated query ids: query-1"]


def test_duplicate_expected_datasets_are_reported(tmp_path):
    problems = _load_problems(
        tmp_path,
        {"queries": [_query("query-1", expected={"datasets": [{"dataSetFileId": "a"}, {"dataSetFileId": "a"}]})]},
    )

    assert problems == [
        "Query 'query-1', field 'expected': Value error, Expected datasets must be unique, duplicated data set file ids: a"
    ]


GOLD_STANDARD = GoldStandard.model_validate(
    {
        "queries": [
            _query("query-1", tags=["attendance"]),
            _query("query-2", tags=["absence"]),
            _query("query-3", tags=["attendance", "geography"]),
        ]
    }
)


@pytest.mark.parametrize(
    "query_ids, tags, expected_query_ids",
    [
        pytest.param([], [], ["query-1", "query-2", "query-3"], id="everything"),
        pytest.param(["query-2"], [], ["query-2"], id="by_id"),
        pytest.param([], ["attendance"], ["query-1", "query-3"], id="by_tag"),
        pytest.param(["query-2"], ["geography"], ["query-2", "query-3"], id="by_id_or_tag"),
    ],
)
def test_select_queries(query_ids, tags, expected_query_ids):
    selected = GOLD_STANDARD.select(query_ids=query_ids, tags=tags)

    assert [query.id for query in selected] == expected_query_ids


def test_select_unknown_query_id_raises():
    with pytest.raises(ValueError, match="Unknown query ids: query-4"):
        GOLD_STANDARD.select(query_ids=["query-1", "query-4"], tags=[])


def test_select_with_no_matches_raises():
    with pytest.raises(ValueError, match="No queries match"):
        GOLD_STANDARD.select(query_ids=[], tags=["unknown"])
