"""Reads a previous report, to replay it or to compare a run with it.

The report is read with lenient models, which only require the fields needed from it, so that an old report can still
be used after the report models have changed. Everything else about its results is rebuilt from its recorded events.
"""

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError

from schemas.shared.base_models import CamelModel
from tools.regression_tests.input_models import GoldStandardQuery
from tools.regression_tests.report_models import ExecutionStatus
from tools.regression_tests.sse_client import SearchExecution, SseEvent


class RecordedEvent(CamelModel):
    elapsed_seconds: float = 0.0
    data: Any


class RecordedQuery(CamelModel):
    user_query: str
    publication_id: str
    status: str | None = None
    error_message: str | None = None
    http_status: int | None = None
    duration_seconds: float = 0.0
    raw_events: list[RecordedEvent] = Field(default_factory=list)


class RecordedIteration(CamelModel):
    queries: list[RecordedQuery] = Field(default_factory=list)


class RecordedReplaySource(CamelModel):
    environment_name: str
    base_url: str


class RecordedRun(CamelModel):
    started_at: datetime
    environment_name: str
    base_url: str
    replayed_from: RecordedReplaySource | None = None

    @property
    def source_environment_name(self) -> str:
        """The environment the results came from, which for a replay is the environment it replayed."""
        return self.replayed_from.environment_name if self.replayed_from else self.environment_name

    @property
    def source_base_url(self) -> str:
        return self.replayed_from.base_url if self.replayed_from else self.base_url


class RecordedReport(CamelModel):
    run: RecordedRun
    iterations: list[RecordedIteration] = Field(default_factory=list)


class RecordedReportError(Exception):
    pass


# Recorded queries are matched by query text and publication, rather than by query id, so that a query whose text has
# changed since it was recorded isn't matched with results that no longer correspond to it.
QueryKey = tuple[str, str]


def get_query_key(query: GoldStandardQuery) -> QueryKey:
    return (query.user_query, query.publication_id)


def load_recorded_report(path: Path) -> RecordedReport:
    try:
        recorded = RecordedReport.model_validate_json(path.read_bytes())
    except OSError as e:
        raise RecordedReportError(f"Unable to read the report {path}: {e}") from e
    except ValidationError as e:
        raise RecordedReportError(f"{path} is not a valid report: {e}") from e

    if not recorded.iterations:
        raise RecordedReportError(f"{path} has no iterations")
    return recorded


def get_recorded_queries(recorded: RecordedReport) -> dict[QueryKey, list[RecordedQuery | None]]:
    """Keyed by query. The value holds the query recorded in each iteration, in order, or None for an iteration where
    the query wasn't run."""
    recorded_queries: dict[QueryKey, list[RecordedQuery | None]] = defaultdict(
        lambda: [None] * len(recorded.iterations)
    )
    for index, iteration in enumerate(recorded.iterations):
        for query in iteration.queries:
            recorded_queries[(query.user_query, query.publication_id)][index] = query
    return dict(recorded_queries)


def to_search_execution(recorded: RecordedQuery) -> SearchExecution:
    """Rebuilds the execution of a recorded query, so that its result can be rebuilt with the current version of the
    script. Only the events of a 200 response were recorded, so for anything else the recorded error is kept."""
    http_error_prefix = f"HTTP {recorded.http_status}:"
    return SearchExecution(
        duration_seconds=recorded.duration_seconds,
        http_status=recorded.http_status,
        events=[SseEvent(elapsed_seconds=event.elapsed_seconds, data=event.data) for event in recorded.raw_events],
        timed_out=recorded.status == ExecutionStatus.TIMEOUT,
        request_error=(
            recorded.error_message or "The request failed"
            if recorded.http_status is None and recorded.status != ExecutionStatus.TIMEOUT
            else None
        ),
        response_body=(
            (recorded.error_message or "").removeprefix(http_error_prefix).strip()
            if recorded.http_status not in (None, 200)
            else None
        ),
    )
