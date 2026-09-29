"""Tests for replaying the streams recorded in a previous report, in `tools.regression_tests.replay`."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from tools.regression_tests.__main__ import main
from tools.regression_tests.input_models import GoldStandardQuery
from tools.regression_tests.replay import (
    REPLAY_ENVIRONMENT,
    REPLAY_ENVIRONMENT_NAME,
    ReplayError,
    load_replay,
)
from tools.regression_tests.report_models import ExecutionStatus, RegressionReport
from tools.regression_tests.run_result import build_query_result
from tools.regression_tests.runner import RunOptions, run_regression_tests

REPORT_FILE = "reports/recorded.json"


def _query(query_id: str, user_query: str | None = None) -> GoldStandardQuery:
    return GoldStandardQuery(
        id=query_id, user_query=user_query or f"Query {query_id}", publication_id="test-publication-id"
    )


def _recorded_query(query: GoldStandardQuery, events: list, http_status: int | None = 200) -> dict:
    return {
        "queryId": query.id,
        "userQuery": query.user_query,
        "publicationId": query.publication_id,
        "httpStatus": http_status,
        "rawEvents": [{"elapsedSeconds": 1.0, "data": data} for data in events],
    }


def _recorded_report(*iterations: list[dict]) -> dict:
    """A recorded report with only the fields that replaying needs, and one iteration per list of recorded queries."""
    return {
        "run": {"startedAt": "2026-09-29T14:29:44Z", "environmentName": "dev", "baseUrl": "https://dev"},
        "iterations": [{"queries": queries} for queries in iterations],
    }


def _write_report(tmp_path: Path, report: dict | str) -> Path:
    path = tmp_path / "recorded.json"
    path.write_text(report if isinstance(report, str) else json.dumps(report), encoding="utf-8")
    return path


def _run(queries: list[GoldStandardQuery], options: RunOptions, transport: httpx.AsyncBaseTransport) -> RegressionReport:
    return asyncio.run(run_regression_tests(queries, options, transport=transport))


def _options(iterations: int = 1, **overrides) -> RunOptions:
    return RunOptions(
        **{
            "environment_name": REPLAY_ENVIRONMENT_NAME,
            "environment": REPLAY_ENVIRONMENT,
            "input_file": "queries.json",
            "input_file_sha256": "test-sha256",
            "git_commit": "test-commit",
            "iterations": iterations,
            "concurrency": 2,
            "timeout_seconds": 5,
            "max_cost": None,
            **overrides,
        }
    )


def _replay(tmp_path: Path, report: dict, queries: list[GoldStandardQuery], iterations: int = 1) -> RegressionReport:
    replay = load_replay(_write_report(tmp_path, report), REPORT_FILE, queries)
    return _run(queries, _options(iterations, replayed_from=replay.source), replay.transport)


def _statuses(report: RegressionReport) -> list[list[ExecutionStatus]]:
    return [[result.status for result in iteration.queries] for iteration in report.iterations]


def test_replaying_a_report_reproduces_its_results(tmp_path, build_final_dataset, build_pipeline_events):
    queries = [_query("query-1"), _query("query-2")]
    events_by_query = {
        "Query query-1": build_pipeline_events([build_final_dataset(file_id="file-1")]),
        "Query query-2": build_pipeline_events(include_pipeline_complete=False) + [{"error": "Failed"}],
    }

    def service(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health_check":
            return httpx.Response(200)
        events = events_by_query[json.loads(request.content)["userQuery"]]
        return httpx.Response(200, content="".join(f"data: {json.dumps(data)}\n\n" for data in events).encode())

    recorded = _run(queries, _options(iterations=2), httpx.MockTransport(service))
    replayed = _replay(
        tmp_path, json.loads(recorded.model_dump_json(by_alias=True)), queries, iterations=2
    )

    assert _statuses(replayed) == [[ExecutionStatus.SUCCESS, ExecutionStatus.SSE_ERROR]] * 2
    for recorded_iteration, replayed_iteration in zip(recorded.iterations, replayed.iterations):
        for recorded_result, replayed_result in zip(recorded_iteration.queries, replayed_iteration.queries):
            assert replayed_result.datasets == recorded_result.datasets
            assert replayed_result.token_usage == recorded_result.token_usage
            assert replayed_result.cost == recorded_result.cost
            assert [event.data for event in replayed_result.raw_events] == [
                event.data for event in recorded_result.raw_events
            ]


def test_replaying_a_real_stream_matches_classifying_it_directly(
    tmp_path, load_json_fixture, build_execution, query
):
    events = load_json_fixture("nl_search_sse_success.json")

    replayed = _replay(tmp_path, _recorded_report([_recorded_query(query, events)]), [query])

    expected = build_query_result(query, build_execution(events))
    result = replayed.iterations[0].queries[0]
    assert result.status == expected.status == ExecutionStatus.SUCCESS
    assert result.datasets == expected.datasets
    assert result.cost == expected.cost


def test_the_report_records_what_was_replayed(tmp_path, build_pipeline_events):
    query = _query("query-1")

    replayed = _replay(tmp_path, _recorded_report([_recorded_query(query, build_pipeline_events())]), [query])

    assert replayed.run.environment_name == REPLAY_ENVIRONMENT_NAME
    assert replayed.run.replayed_from.report_file == REPORT_FILE
    assert replayed.run.replayed_from.environment_name == "dev"
    assert replayed.run.replayed_from.base_url == "https://dev"


def test_each_iteration_replays_the_stream_recorded_in_that_iteration(
    tmp_path, build_final_dataset, build_pipeline_events
):
    query = _query("query-1")
    report = _recorded_report(
        [_recorded_query(query, build_pipeline_events([build_final_dataset()]))],
        [_recorded_query(query, [{"stage": "starting pipeline"}, {"error": "Failed"}])],
    )

    replayed = _replay(tmp_path, report, [query], iterations=2)

    assert _statuses(replayed) == [[ExecutionStatus.SUCCESS], [ExecutionStatus.SSE_ERROR]]


def test_a_query_not_run_in_an_iteration_is_not_replayed_in_it(tmp_path, build_pipeline_events):
    query = _query("query-1")
    report = _recorded_report([_recorded_query(query, build_pipeline_events())], [])

    replayed = _replay(tmp_path, report, [query], iterations=2)

    assert _statuses(replayed) == [[ExecutionStatus.SUCCESS], [ExecutionStatus.HTTP_ERROR]]
    assert "No recorded stream for this query in iteration 2" in replayed.iterations[1].queries[0].error_message


@pytest.mark.parametrize(
    "recorded_query",
    [
        pytest.param(_recorded_query(_query("query-1", "Old query text"), []), id="query_text_changed"),
        pytest.param(_recorded_query(_query("query-1"), [], http_status=500), id="recorded_http_error"),
        pytest.param(_recorded_query(_query("query-1"), [], http_status=None), id="recorded_request_error"),
        pytest.param(_recorded_query(_query("other-query"), []), id="other_query"),
    ],
)
def test_queries_without_a_recorded_stream_are_http_errors(tmp_path, recorded_query):
    query = _query("query-1")
    report_path = _write_report(tmp_path, _recorded_report([recorded_query]))

    replay = load_replay(report_path, REPORT_FILE, [query])
    replayed = _run([query], _options(replayed_from=replay.source), replay.transport)

    assert replay.unrecorded_query_ids == ["query-1"]
    result = replayed.iterations[0].queries[0]
    assert result.status == ExecutionStatus.HTTP_ERROR
    assert result.http_status == 404


def test_a_recorded_stream_without_events_is_still_replayed(tmp_path):
    query = _query("query-1")

    replay = load_replay(_write_report(tmp_path, _recorded_report([_recorded_query(query, [])])), REPORT_FILE, [query])
    replayed = _run([query], _options(replayed_from=replay.source), replay.transport)

    assert replay.unrecorded_query_ids == []
    assert _statuses(replayed) == [[ExecutionStatus.INCOMPLETE_STREAM]]


def test_data_that_was_not_json_is_replayed_as_received(tmp_path):
    query = _query("query-1")
    report = _recorded_report([_recorded_query(query, [{"stage": "starting pipeline"}, "not json\nover two lines"])])

    replayed = _replay(tmp_path, report, [query])

    result = replayed.iterations[0].queries[0]
    assert result.status == ExecutionStatus.CONTRACT_MISMATCH
    assert result.raw_events[1].data == "not json\nover two lines"


def test_queries_with_the_same_text_cannot_be_replayed(tmp_path, build_pipeline_events):
    queries = [_query("query-1", "Same text"), _query("query-2", "Same text")]
    report_path = _write_report(tmp_path, _recorded_report([_recorded_query(queries[0], build_pipeline_events())]))

    with pytest.raises(ReplayError, match="query-1, query-2"):
        load_replay(report_path, REPORT_FILE, queries)


@pytest.mark.parametrize(
    "report, expected_message",
    [
        pytest.param("not json", "is not a valid report", id="not_json"),
        pytest.param({"iterations": []}, "is not a valid report", id="no_run"),
        pytest.param(_recorded_report(), "has no iterations", id="no_iterations"),
    ],
)
def test_invalid_reports_cannot_be_replayed(tmp_path, report, expected_message):
    with pytest.raises(ReplayError, match=expected_message):
        load_replay(_write_report(tmp_path, report), REPORT_FILE, [_query("query-1")])


def test_missing_report_cannot_be_replayed(tmp_path):
    with pytest.raises(ReplayError, match="Unable to replay the report: Unable to read the report"):
        load_replay(tmp_path / "missing.json", REPORT_FILE, [_query("query-1")])


def _write_gold_standard(tmp_path: Path, queries: list[GoldStandardQuery]) -> Path:
    path = tmp_path / "queries.json"
    path.write_text(
        json.dumps({"queries": [query.model_dump(by_alias=True, exclude_none=True) for query in queries]}),
        encoding="utf-8",
    )
    return path


def test_cli_replays_every_recorded_iteration_by_default(tmp_path, build_pipeline_events):
    query = _query("query-1")
    recorded = [_recorded_query(query, build_pipeline_events())]
    report_path = _write_report(tmp_path, _recorded_report(recorded, recorded))
    out_dir = tmp_path / "out"

    exit_code = main(["--replay", str(report_path), "--input", str(_write_gold_standard(tmp_path, [query])), "--out", str(out_dir)])

    assert exit_code == 0
    [written] = out_dir.glob("regression-report-replay-*.json")
    report = RegressionReport.model_validate_json(written.read_bytes())
    assert report.run.iterations == 2
    assert _statuses(report) == [[ExecutionStatus.SUCCESS]] * 2


def test_cli_cannot_replay_more_iterations_than_were_recorded(tmp_path, build_pipeline_events):
    query = _query("query-1")
    report_path = _write_report(tmp_path, _recorded_report([_recorded_query(query, build_pipeline_events())]))

    exit_code = main(
        [
            "--replay", str(report_path),
            "--input", str(_write_gold_standard(tmp_path, [query])),
            "--iterations", "2",
            "--out", str(tmp_path / "out"),
        ]
    )

    assert exit_code == 2
    assert not (tmp_path / "out").exists()


def test_cli_does_not_allow_env_and_replay_together(tmp_path):
    with pytest.raises(SystemExit):
        main(["--env", "dev", "--replay", str(tmp_path / "recorded.json")])


def _run_cli_replay(tmp_path: Path, report: dict, queries: list[GoldStandardQuery], *args: str) -> tuple[int, RegressionReport | None]:
    out_dir = tmp_path / "out"
    exit_code = main(
        [
            "--replay", str(_write_report(tmp_path, report)),
            "--input", str(_write_gold_standard(tmp_path, queries)),
            "--out", str(out_dir),
            *args,
        ]
    )
    written = list(out_dir.glob("*.json"))
    return exit_code, RegressionReport.model_validate_json(written[0].read_bytes()) if written else None


def test_cli_only_replays_the_recorded_queries_by_default(tmp_path, build_pipeline_events):
    queries = [_query("query-1"), _query("query-2")]
    report = _recorded_report([_recorded_query(queries[1], build_pipeline_events())])

    exit_code, replayed = _run_cli_replay(tmp_path, report, queries)

    assert exit_code == 0
    assert replayed.run.query_ids == ["query-2"]
    assert _statuses(replayed) == [[ExecutionStatus.SUCCESS]]


def test_cli_reports_explicitly_selected_queries_that_were_not_recorded(tmp_path, build_pipeline_events):
    queries = [_query("query-1"), _query("query-2")]
    report = _recorded_report([_recorded_query(queries[1], build_pipeline_events())])

    exit_code, replayed = _run_cli_replay(tmp_path, report, queries, "--query", "query-1", "--query", "query-2")

    assert exit_code == 1
    assert _statuses(replayed) == [[ExecutionStatus.HTTP_ERROR, ExecutionStatus.SUCCESS]]


def test_cli_cannot_replay_a_report_without_any_of_the_queries(tmp_path, build_pipeline_events):
    report = _recorded_report([_recorded_query(_query("other-query"), build_pipeline_events())])

    exit_code, replayed = _run_cli_replay(tmp_path, report, [_query("query-1")])

    assert exit_code == 2
    assert replayed is None
