"""Tests for loading gold standard queries in `tools.regression_tests.input_models`."""

import json
from pathlib import Path

import pytest

from tools.regression_tests.__main__ import DEFAULT_INPUT_FILE
from tools.regression_tests.input_models import GoldStandardFileError, load_gold_standard


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
