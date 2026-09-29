"""Replays the SSE events recorded in a previous report instead of calling the service, so that the script can be
developed and run without using any Azure OpenAI tokens.

The recorded events are served through an HTTP transport, so everything after the network, e.g. parsing the stream,
classifying each query's status and summarising the results, runs exactly as it does against a real environment.
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import Field, ValidationError

from schemas.shared.base_models import CamelModel
from tools.regression_tests.environments import Environment
from tools.regression_tests.input_models import GoldStandardQuery
from tools.regression_tests.report_models import ReplaySource

REPLAY_ENVIRONMENT_NAME = "replay"
REPLAY_ENVIRONMENT = Environment(base_url="http://replay")

# The recorded report is read with lenient models, which only require the fields needed to replay it, so that a
# report still replays after the report models have changed.


class _RecordedEvent(CamelModel):
    data: Any


class _RecordedQuery(CamelModel):
    user_query: str
    publication_id: str
    http_status: int | None = None
    raw_events: list[_RecordedEvent] = Field(default_factory=list)


class _RecordedIteration(CamelModel):
    queries: list[_RecordedQuery] = Field(default_factory=list)


class _RecordedRun(CamelModel):
    started_at: datetime
    environment_name: str
    base_url: str


class _RecordedReport(CamelModel):
    run: _RecordedRun
    iterations: list[_RecordedIteration] = Field(default_factory=list)


# Recordings are matched by query text and publication, rather than by query id, so that a query whose text has
# changed since it was recorded isn't replayed with events that no longer correspond to it.
_QueryKey = tuple[str, str]


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
        recorded = _RecordedReport.model_validate_json(report_path.read_bytes())
    except OSError as e:
        raise ReplayError(f"Unable to read the report to replay: {e}") from e
    except ValidationError as e:
        raise ReplayError(f"{report_path} is not a report that can be replayed: {e}") from e

    if not recorded.iterations:
        raise ReplayError(f"{report_path} has no iterations to replay")

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
            environment_name=recorded.run.environment_name,
            base_url=recorded.run.base_url,
            started_at=recorded.run.started_at,
        ),
        recorded_iterations=len(recorded.iterations),
        unrecorded_query_ids=[
            query.id
            for query in queries
            if all(events is None for events in recordings.get(_get_query_key(query), []))
        ],
    )


def _get_recordings(recorded: _RecordedReport) -> dict[_QueryKey, list[list[Any] | None]]:
    """Keyed by query. The value holds the recorded event data of each iteration, in order, or None for an iteration
    where the query wasn't run, or where it didn't respond with a stream to replay."""
    recordings: dict[_QueryKey, list[list[Any] | None]] = defaultdict(
        lambda: [None] * len(recorded.iterations)
    )
    for index, iteration in enumerate(recorded.iterations):
        for query in iteration.queries:
            if query.http_status == 200:
                recordings[(query.user_query, query.publication_id)][index] = [
                    event.data for event in query.raw_events
                ]
    return dict(recordings)


def _get_query_key(query: GoldStandardQuery) -> _QueryKey:
    return (query.user_query, query.publication_id)


def _get_duplicate_query_ids(queries: list[GoldStandardQuery]) -> list[str]:
    query_ids_by_key: dict[_QueryKey, list[str]] = defaultdict(list)
    for query in queries:
        query_ids_by_key[_get_query_key(query)].append(query.id)
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

    def __init__(self, recordings: dict[_QueryKey, list[list[Any] | None]], report_file: str):
        self._recordings = recordings
        self._report_file = report_file
        self._search_counts: dict[_QueryKey, int] = defaultdict(int)

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
