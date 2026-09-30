"""Calls the natural language search endpoint and collects the Server-Sent Events that it streams back.

Nothing here interprets the events, so that the raw stream is always captured. See `run_result.py` for that.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

MAX_ERROR_RESPONSE_BODY_LENGTH = 2000


@dataclass
class SseEvent:
    elapsed_seconds: float
    """Time from sending the request to receiving the event."""
    data: Any
    """The event's data parsed as JSON, or the raw data if it isn't valid JSON."""


@dataclass
class SearchExecution:
    duration_seconds: float = 0.0
    http_status: int | None = None
    events: list[SseEvent] = field(default_factory=list)
    timed_out: bool = False
    request_error: str | None = None
    """Set if the request failed without a response, e.g. the connection was refused."""
    response_body: str | None = None
    """The (truncated) response body, only captured for non-200 responses."""


class SseDataParser:
    """Parses the lines of an SSE stream one at a time, returning the data of each event once it's complete.

    Only the `data` field is kept, as it's the only field the search endpoint sends. An incomplete event
    at the end of the stream is discarded, as per the SSE specification."""

    def __init__(self):
        self._data_lines: list[str] = []

    def feed(self, line: str) -> str | None:
        if line == "":
            if not self._data_lines:
                return None
            data = "\n".join(self._data_lines)
            self._data_lines = []
            return data

        if line.startswith(":"):
            return None

        name, _, value = line.partition(":")
        if name == "data":
            self._data_lines.append(value.removeprefix(" "))
        return None


async def run_search(
    client: httpx.AsyncClient,
    search_url: str,
    user_query: str,
    publication_id: str,
    timeout_seconds: float,
) -> SearchExecution:
    """Runs a search, never raising for a failed request, so that each failure can be reported as a result."""
    execution = SearchExecution()
    parser = SseDataParser()
    started = time.perf_counter()

    try:
        async with asyncio.timeout(timeout_seconds):
            async with client.stream(
                "POST",
                search_url,
                json={"userQuery": user_query, "publicationId": publication_id},
            ) as response:
                execution.http_status = response.status_code

                if response.status_code != 200:
                    body = await response.aread()
                    execution.response_body = body.decode(errors="replace")[
                        :MAX_ERROR_RESPONSE_BODY_LENGTH
                    ]
                else:
                    async for line in response.aiter_lines():
                        data = parser.feed(line)
                        if data is not None:
                            execution.events.append(
                                SseEvent(
                                    elapsed_seconds=time.perf_counter() - started,
                                    data=_parse_json(data),
                                )
                            )
    except (TimeoutError, httpx.TimeoutException):
        execution.timed_out = True
    except httpx.HTTPError as e:
        execution.request_error = f"{type(e).__name__}: {e}"

    execution.duration_seconds = time.perf_counter() - started
    return execution


def _parse_json(data: str) -> Any:
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return data
