"""Replays the SSE events recorded in a previous report instead of calling the service, so that the script can be
developed and run without using any Azure OpenAI tokens.

The recorded events are served through an HTTP transport, so everything after the network, e.g. parsing the stream,
classifying each query's status and summarising the results, runs exactly as it does against a real environment.
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from tools.regression_tests.environments import Environment
from tools.regression_tests.input_models import GoldStandardQuery
from tools.regression_tests.recorded_report import (
    QueryKey,
    RecordedReport,
    RecordedReportError,
    get_query_key,
    get_recorded_queries,
    load_recorded_report,
)
from tools.regression_tests.report_models import ReplaySource

REPLAY_ENVIRONMENT_NAME = "replay"
REPLAY_ENVIRONMENT = Environment(base_url="http://replay")


class ReplayError(Exception):
    pass


@dataclass
class Replay:
    transport: httpx.AsyncBaseTransport
    source: ReplaySource
    recorded_iterations: int
    unrecorded_query_ids: list[str]
    """Selected queries without any recording to replay, which will result in an `http_error`."""


def load_replay(report_path: Path, report_file: str, queries: list[GoldStandardQuery]) -> Replay:
    """`report_file` is how the report is described in the new report, e.g. relative to the repository root."""
    try:
        recorded = load_recorded_report(report_path)
    except RecordedReportError as e:
        raise ReplayError(f"Unable to replay the report: {e}") from e

    duplicate_query_ids = _get_duplicate_query_ids(queries)
    if duplicate_query_ids:
        raise ReplayError(
            "Queries with the same query text and publication can't be replayed separately: "
            + ", ".join(duplicate_query_ids)
        )

    recordings = _get_recordings(recorded)
    return Replay(
        transport=httpx.MockTransport(_ReplayHandler(recordings, report_file)),
        source=ReplaySource(
            report_file=report_file,
            # A replay of a replay is described by the environment the results originally came from
            environment_name=recorded.run.source_environment_name,
            base_url=recorded.run.source_base_url,
            started_at=recorded.run.started_at,
        ),
        recorded_iterations=len(recorded.iterations),
        unrecorded_query_ids=[
            query.id
            for query in queries
            if all(events is None for events in recordings.get(get_query_key(query), []))
        ],
    )


def _get_recordings(recorded: RecordedReport) -> dict[QueryKey, list[list[Any] | None]]:
    """Keyed by query. The value holds the recorded event data of each iteration, in order, or None for an iteration
    where the query wasn't run, or where it didn't respond with a stream to replay."""
    return {
        key: [
            [event.data for event in query.raw_events] if query is not None and query.http_status == 200 else None
            for query in queries
        ]
        for key, queries in get_recorded_queries(recorded).items()
    }


def _get_duplicate_query_ids(queries: list[GoldStandardQuery]) -> list[str]:
    query_ids_by_key: dict[QueryKey, list[str]] = defaultdict(list)
    for query in queries:
        query_ids_by_key[get_query_key(query)].append(query.id)
    return sorted(
        query_id
        for query_ids in query_ids_by_key.values()
        if len(query_ids) > 1
        for query_id in query_ids
    )


class _ReplayHandler:
    """Responds to the health check, and to each search with the events recorded for that query.

    Each query is searched once per iteration, and iterations run one after another, so the nth search of a query
    is served the events recorded for it in the nth iteration."""

    def __init__(self, recordings: dict[QueryKey, list[list[Any] | None]], report_file: str):
        self._recordings = recordings
        self._report_file = report_file
        self._search_counts: dict[QueryKey, int] = defaultdict(int)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health_check":
            return httpx.Response(200, json={"message": "API working"})

        body = json.loads(request.content)
        key = (body["userQuery"], body["publicationId"])
        index = self._search_counts[key]
        self._search_counts[key] += 1

        iterations = self._recordings.get(key, [])
        events = iterations[index] if index < len(iterations) else None
        if events is None:
            return httpx.Response(
                404,
                text=f"No recorded stream for this query in iteration {index + 1} of {self._report_file}",
            )

        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="".join(_format_sse_event(data) for data in events).encode(),
        )


def _format_sse_event(data: Any) -> str:
    # Data that wasn't valid JSON when it was recorded is replayed as it was received
    text = data if isinstance(data, str) else json.dumps(data)
    return "".join(f"data: {line}\n" for line in text.split("\n")) + "\n"
