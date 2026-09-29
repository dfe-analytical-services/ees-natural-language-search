"""Tests for running iterations of queries in `tools.regression_tests.runner`, against a mock transport."""

import asyncio
import json

import httpx
import pytest

from tools.regression_tests.environments import Environment
from tools.regression_tests.input_models import GoldStandardQuery
from tools.regression_tests.report_models import ExecutionStatus
from tools.regression_tests.runner import HealthCheckError, RunOptions, run_regression_tests

BASE_URL = "https://test"


def _options(**overrides) -> RunOptions:
    return RunOptions(
        **{
            "environment_name": "test",
            "environment": Environment(base_url=BASE_URL),
            "input_file": "queries.json",
            "input_file_sha256": "test-sha256",
            "git_commit": "test-commit",
            "iterations": 1,
            "concurrency": 2,
            "timeout_seconds": 5,
            "max_cost": None,
            **overrides,
        }
    )


def _queries(*query_ids: str) -> list[GoldStandardQuery]:
    return [
        GoldStandardQuery(id=query_id, user_query=f"Query {query_id}", publication_id="test-publication-id")
        for query_id in query_ids
    ]


class _MockService:
    """Responds to the health check, and to searches with the given events, or an HTTP 500 for a failing query."""

    def __init__(self, events: list[dict], failing_query: str | None = None, health_status: int = 200):
        self.events = events
        self.failing_query = failing_query
        self.health_status = health_status
        self.searched_queries: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health_check":
            return httpx.Response(self.health_status, json={"message": "API working"})

        user_query = json.loads(request.content)["userQuery"]
        self.searched_queries.append(user_query)
        if user_query == self.failing_query:
            return httpx.Response(500, content=b"Internal Server Error")

        body = "".join(f"data: {json.dumps(event)}\n\n" for event in self.events)
        return httpx.Response(200, content=body.encode())


def _run(service: _MockService, queries: list[GoldStandardQuery], options: RunOptions):
    return asyncio.run(run_regression_tests(queries, options, transport=httpx.MockTransport(service.handle)))


def test_runs_every_query_in_every_iteration(build_final_dataset, build_pipeline_events):
    service = _MockService(build_pipeline_events([build_final_dataset()]), failing_query="Query query-2")

    report = _run(service, _queries("query-1", "query-2", "query-3"), _options(iterations=2))

    assert len(service.searched_queries) == 6
    assert [iteration.iteration for iteration in report.iterations] == [1, 2]
    for iteration in report.iterations:
        assert [result.query_id for result in iteration.queries] == ["query-1", "query-2", "query-3"]
        assert [result.status for result in iteration.queries] == [
            ExecutionStatus.SUCCESS,
            ExecutionStatus.HTTP_ERROR,
            ExecutionStatus.SUCCESS,
        ]
        assert iteration.summary.query_count == 3

    assert report.summary.query_count == 6
    assert report.summary.status_counts[ExecutionStatus.SUCCESS] == 4
    assert report.summary.status_counts[ExecutionStatus.HTTP_ERROR] == 2
    assert report.run.query_ids == ["query-1", "query-2", "query-3"]
    assert report.run.base_url == BASE_URL
    assert not report.run.budget_exceeded
    assert report.run.finished_at >= report.run.started_at


def test_failed_health_check_raises_without_running_queries(build_pipeline_events):
    service = _MockService(build_pipeline_events(), health_status=503)

    with pytest.raises(HealthCheckError, match="returned HTTP 503"):
        _run(service, _queries("query-1"), _options())

    assert service.searched_queries == []


def test_reaching_the_max_cost_skips_the_remaining_queries_and_iterations(build_final_dataset, build_pipeline_events):
    # Each query costs 0.001, so the maximum cost is reached by the first query
    service = _MockService(build_pipeline_events([build_final_dataset()]))

    report = _run(
        service,
        _queries("query-1", "query-2", "query-3"),
        _options(iterations=2, concurrency=1, max_cost=0.001),
    )

    assert service.searched_queries == ["Query query-1"]
    assert len(report.iterations) == 1
    assert [result.query_id for result in report.iterations[0].queries] == ["query-1"]
    assert report.iterations[0].skipped_query_ids == ["query-2", "query-3"]
    assert report.run.budget_exceeded
    assert report.run.iterations == 2
