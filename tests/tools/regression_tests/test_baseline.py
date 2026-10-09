"""Tests for comparing a run with a baseline in `tools.regression_tests.baseline`."""

import json
from pathlib import Path

import pytest

from tools.regression_tests.__main__ import main
from tools.regression_tests.baseline import BaselineError, compare_query, load_baseline
from tools.regression_tests.input_models import GoldStandardQuery
from tools.regression_tests.report_models import (
    AccuracyResult,
    ExecutionStatus,
    ExpectedDatasetAccuracy,
    QueryAccuracy,
    QueryChange,
    RegressionReport,
    SelectionAccuracy,
)
from tools.regression_tests.subject_meta import UnavailableSubjectMeta

REPORT_FILE = "reports/baseline.json"


def _accuracy(result: AccuracyResult, indicators_passed: bool | None = None) -> QueryAccuracy:
    return QueryAccuracy(
        result=result,
        datasets=[
            ExpectedDatasetAccuracy(
                data_set_file_id="data-set-file-1",
                title="Dataset 1",
                required=True,
                result=result,
                found=True,
                rank=1,
                indicators=None if indicators_passed is None else SelectionAccuracy(passed=indicators_passed),
            )
        ],
    )


def test_identical_results_are_unchanged(build_result, build_dataset_result):
    results = [build_result(datasets=[build_dataset_result()], accuracy=_accuracy(AccuracyResult.PASS))]

    comparison = compare_query("query-1", results, results)

    assert comparison.change == QueryChange.UNCHANGED
    assert comparison.differences == []
    assert (comparison.baseline_status, comparison.current_status) == (ExecutionStatus.SUCCESS, ExecutionStatus.SUCCESS)


def test_query_not_in_the_baseline_is_new(build_result):
    comparison = compare_query("query-1", [], [build_result(accuracy=_accuracy(AccuracyResult.PASS))])

    assert comparison.change == QueryChange.NEW
    assert (comparison.baseline_status, comparison.current_accuracy) == (None, AccuracyResult.PASS)


@pytest.mark.parametrize(
    "baseline_status, current_status, expected_change",
    [
        pytest.param(ExecutionStatus.SUCCESS, ExecutionStatus.SSE_ERROR, QueryChange.REGRESSED, id="failed"),
        pytest.param(
            ExecutionStatus.SUCCESS,
            ExecutionStatus.SUCCESS_WITH_VALIDATION_ERRORS,
            QueryChange.REGRESSED,
            id="validation_errors",
        ),
        pytest.param(ExecutionStatus.TIMEOUT, ExecutionStatus.SUCCESS, QueryChange.IMPROVED, id="completed"),
        pytest.param(ExecutionStatus.TIMEOUT, ExecutionStatus.SSE_ERROR, QueryChange.CHANGED, id="different_failure"),
    ],
)
def test_status_changes(build_result, baseline_status, current_status, expected_change):
    comparison = compare_query(
        "query-1", [build_result(status=baseline_status)], [build_result(status=current_status)]
    )

    assert comparison.change == expected_change
    assert comparison.differences[0] == f"Status: {baseline_status} -> {current_status}"


def test_the_worst_status_of_any_iteration_is_compared(build_result):
    comparison = compare_query(
        "query-1",
        [build_result(), build_result()],
        [build_result(), build_result(status=ExecutionStatus.TIMEOUT)],
    )

    assert comparison.change == QueryChange.REGRESSED
    assert comparison.current_status == ExecutionStatus.TIMEOUT


def test_a_check_that_now_fails_is_a_regression(build_result, build_dataset_result):
    comparison = compare_query(
        "query-1",
        [build_result(datasets=[build_dataset_result()], accuracy=_accuracy(AccuracyResult.PASS, indicators_passed=True))],
        [
            build_result(
                datasets=[build_dataset_result(indicators=("Number of sessions",))],
                accuracy=_accuracy(AccuracyResult.PARTIAL, indicators_passed=False),
            )
        ],
    )

    assert comparison.change == QueryChange.REGRESSED
    assert comparison.differences == [
        "Accuracy: pass -> partial",
        "Indicators of 'Dataset 1': passed -> failed",
        "Indicators of 'Dataset 1': added 'Number of sessions', removed 'Overall absence rate'",
    ]


def test_a_check_that_only_sometimes_passes_is_treated_as_failing(build_result):
    passing = build_result(accuracy=_accuracy(AccuracyResult.PASS, indicators_passed=True))
    failing = build_result(accuracy=_accuracy(AccuracyResult.PARTIAL, indicators_passed=False))

    comparison = compare_query("query-1", [passing, failing], [passing, passing])

    assert comparison.change == QueryChange.IMPROVED
    assert "Indicators of 'Dataset 1': failed -> passed" in comparison.differences


def test_better_and_worse_is_mixed(build_result):
    comparison = compare_query(
        "query-1",
        [build_result(status=ExecutionStatus.SUCCESS_WITH_VALIDATION_ERRORS, accuracy=_accuracy(AccuracyResult.PASS))],
        [build_result(accuracy=_accuracy(AccuracyResult.PARTIAL))],
    )

    assert comparison.change == QueryChange.MIXED


def test_different_selections_without_a_check_changing_are_changed(build_result, build_dataset_result):
    comparison = compare_query(
        "query-1",
        [build_result(datasets=[build_dataset_result()])],
        [build_result(datasets=[build_dataset_result(filters=("Primary",))])],
    )

    assert comparison.change == QueryChange.CHANGED
    assert comparison.differences == ["Filter items of 'Dataset 1': added 'Primary', removed 'Total'"]


def _gold_standard_query(query_id: str = "query-1", user_query: str | None = None, expected: dict | None = None):
    return GoldStandardQuery.model_validate(
        {
            "id": query_id,
            "userQuery": user_query or f"Query {query_id}",
            "publicationId": "test-publication-id",
            "expected": expected,
        }
    )


def _recorded_query(query: GoldStandardQuery, events: list, status: str = "success", http_status: int | None = 200, **fields) -> dict:
    return {
        "queryId": query.id,
        "userQuery": query.user_query,
        "publicationId": query.publication_id,
        "status": status,
        "httpStatus": http_status,
        "durationSeconds": 5.0,
        "rawEvents": [{"elapsedSeconds": 1.0, "data": data} for data in events],
        **fields,
    }


def _write_report(tmp_path: Path, *iterations: list[dict], name: str = "baseline.json") -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {
                "run": {"startedAt": "2026-09-29T14:29:44Z", "environmentName": "dev", "baseUrl": "https://dev"},
                "iterations": [{"queries": queries} for queries in iterations],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_baseline_results_are_rebuilt_and_compared_with_the_current_expected_results(tmp_path, load_json_fixture):
    events = load_json_fixture("nl_search_sse_success.json")
    data_set_file_id = events[-1]["data"]["datasets"][0]["dataSetFileId"]
    query = _gold_standard_query(expected={"author": "developer", "datasets": [{"dataSetFileId": data_set_file_id}]})
    requested_environments = []

    def get_subject_meta(environment_name: str):
        requested_environments.append(environment_name)
        return UnavailableSubjectMeta("Not needed")

    baseline = load_baseline(
        _write_report(tmp_path, [_recorded_query(query, events)]), REPORT_FILE, [query], get_subject_meta
    )

    assert requested_environments == ["dev"]
    assert (baseline.source.report_file, baseline.source.environment_name) == (REPORT_FILE, "dev")
    [result] = baseline.results_by_query_id["query-1"]
    assert result.status == ExecutionStatus.SUCCESS
    assert result.datasets[0].data_set_file_id == data_set_file_id
    assert result.accuracy.result == AccuracyResult.PASS


def test_baseline_of_a_query_whose_text_changed_is_empty(tmp_path, load_json_fixture):
    recorded = _recorded_query(_gold_standard_query(user_query="Old text"), load_json_fixture("nl_search_sse_success.json"))

    baseline = load_baseline(
        _write_report(tmp_path, [recorded]),
        REPORT_FILE,
        [_gold_standard_query(user_query="New text")],
        lambda _: UnavailableSubjectMeta("Not needed"),
    )

    assert baseline.results_by_query_id == {"query-1": []}


@pytest.mark.parametrize(
    "recorded_fields, expected_status, expected_message",
    [
        pytest.param(
            {"status": "http_error", "httpStatus": 500, "errorMessage": "HTTP 500: Internal Server Error"},
            ExecutionStatus.HTTP_ERROR,
            "HTTP 500: Internal Server Error",
            id="http_error",
        ),
        pytest.param(
            {"status": "http_error", "httpStatus": None, "errorMessage": "ConnectError: refused"},
            ExecutionStatus.HTTP_ERROR,
            "ConnectError: refused",
            id="request_error",
        ),
        pytest.param(
            {"status": "timeout", "httpStatus": 200, "errorMessage": "Timed out after 180.0s"},
            ExecutionStatus.TIMEOUT,
            "Timed out after 5.0s",
            id="timeout",
        ),
    ],
)
def test_baseline_failures_are_rebuilt(tmp_path, recorded_fields, expected_status, expected_message):
    query = _gold_standard_query()
    recorded = _recorded_query(query, [], **recorded_fields)

    baseline = load_baseline(
        _write_report(tmp_path, [recorded]), REPORT_FILE, [query], lambda _: UnavailableSubjectMeta("Not needed")
    )

    [result] = baseline.results_by_query_id["query-1"]
    assert (result.status, result.error_message) == (expected_status, expected_message)


def test_invalid_baseline_raises(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(BaselineError, match="Unable to compare with the baseline"):
        load_baseline(path, REPORT_FILE, [_gold_standard_query()], lambda _: UnavailableSubjectMeta("Not needed"))


def _write_gold_standard(tmp_path: Path, queries: list[GoldStandardQuery]) -> Path:
    path = tmp_path / "queries.json"
    path.write_text(
        json.dumps({"queries": [query.model_dump(by_alias=True, exclude_none=True) for query in queries]}),
        encoding="utf-8",
    )
    return path


def test_cli_exits_with_regressions_when_a_query_got_worse(tmp_path, build_pipeline_events, build_final_dataset):
    query = _gold_standard_query()
    baseline_path = _write_report(tmp_path, [_recorded_query(query, build_pipeline_events([build_final_dataset()]))])
    replay_path = _write_report(
        tmp_path,
        [_recorded_query(query, [{"stage": "starting pipeline"}, {"error": "Failed"}], status="sse_error")],
        name="current.json",
    )
    out_dir = tmp_path / "out"

    exit_code = main(
        [
            "--replay", str(replay_path),
            "--baseline", str(baseline_path),
            "--input", str(_write_gold_standard(tmp_path, [query])),
            "--out", str(out_dir),
        ]
    )

    assert exit_code == 3
    [written] = out_dir.glob("*.json")
    comparison = RegressionReport.model_validate_json(written.read_bytes()).baseline_comparison
    assert comparison.change_counts[QueryChange.REGRESSED] == 1
    assert comparison.queries[0].differences[0] == "Status: success -> sse_error"
    metrics = {metric.name: (metric.baseline, metric.current) for metric in comparison.metrics}
    assert metrics["Queries completed"] == (1.0, 0.0)
    assert "## Compared with the baseline" in written.with_suffix(".md").read_text(encoding="utf-8")


def test_cli_rejects_an_invalid_baseline_before_running_any_queries(tmp_path, build_pipeline_events):
    query = _gold_standard_query()
    replay_path = _write_report(tmp_path, [_recorded_query(query, build_pipeline_events())], name="current.json")
    baseline_path = tmp_path / "missing.json"

    exit_code = main(
        [
            "--replay", str(replay_path),
            "--baseline", str(baseline_path),
            "--input", str(_write_gold_standard(tmp_path, [query])),
            "--out", str(tmp_path / "out"),
        ]
    )

    assert exit_code == 2
    assert not (tmp_path / "out").exists()


def test_metrics_are_only_compared_over_the_queries_in_both(tmp_path, build_pipeline_events, build_final_dataset):
    queries = [_gold_standard_query("query-1"), _gold_standard_query("query-2")]
    success = build_pipeline_events([build_final_dataset()])
    failure = [{"stage": "starting pipeline"}, {"error": "Failed"}]
    baseline_path = _write_report(tmp_path, [_recorded_query(queries[0], success)])
    replay_path = _write_report(
        tmp_path,
        [_recorded_query(queries[0], success), _recorded_query(queries[1], failure, status="sse_error")],
        name="current.json",
    )
    out_dir = tmp_path / "out"

    exit_code = main(
        [
            "--replay", str(replay_path),
            "--baseline", str(baseline_path),
            "--input", str(_write_gold_standard(tmp_path, queries)),
            "--out", str(out_dir),
        ]
    )

    assert exit_code == 1
    [written] = out_dir.glob("*.json")
    comparison = RegressionReport.model_validate_json(written.read_bytes()).baseline_comparison
    assert [(query.query_id, query.change) for query in comparison.queries] == [
        ("query-1", QueryChange.UNCHANGED),
        ("query-2", QueryChange.NEW),
    ]
    assert comparison.metrics_query_count == 1
    metrics = {metric.name: (metric.baseline, metric.current) for metric in comparison.metrics}
    assert metrics["Queries completed"] == (1.0, 1.0)
