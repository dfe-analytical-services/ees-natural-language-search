"""Tests for streaming search requests in `tools.regression_tests.sse_client`."""

import asyncio
import json

import httpx

from tools.regression_tests.sse_client import SseDataParser, run_search

SEARCH_URL = "https://test/api/natural_language_search_function"


def _feed_lines(lines: list[str]) -> list[str]:
    parser = SseDataParser()
    return [data for line in lines if (data := parser.feed(line)) is not None]


def test_parser_returns_the_data_of_each_event():
    assert _feed_lines(['data: {"a": 1}', "", 'data: {"b": 2}', ""]) == ['{"a": 1}', '{"b": 2}']


def test_parser_joins_multiple_data_lines_of_an_event():
    assert _feed_lines(["data: line 1", "data: line 2", ""]) == ["line 1\nline 2"]


def test_parser_ignores_comments_other_fields_and_extra_blank_lines():
    assert _feed_lines([": comment", "event: message", "", "", "data:no space", ""]) == ["no space"]


def test_parser_discards_an_incomplete_event_at_the_end_of_the_stream():
    assert _feed_lines(['data: {"a": 1}', "", 'data: {"b": 2}']) == ['{"a": 1}']


def _run_search(handler, timeout_seconds: float = 5):
    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await run_search(
                client,
                SEARCH_URL,
                user_query="Test query",
                publication_id="test-publication-id",
                timeout_seconds=timeout_seconds,
            )

    return asyncio.run(_run())


def test_run_search_posts_the_query_and_collects_the_events():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            content=b'data: {"stage": "starting pipeline"}\n\ndata: not json\n\n',
            headers={"content-type": "text/event-stream"},
        )

    execution = _run_search(handler)

    assert json.loads(requests[0].content) == {
        "userQuery": "Test query",
        "publicationId": "test-publication-id",
    }
    assert execution.http_status == 200
    assert [event.data for event in execution.events] == [{"stage": "starting pipeline"}, "not json"]
    assert execution.events[0].elapsed_seconds <= execution.events[1].elapsed_seconds
    assert execution.duration_seconds >= execution.events[1].elapsed_seconds
    assert not execution.timed_out
    assert execution.request_error is None


def test_run_search_captures_the_body_of_a_non_200_response():
    execution = _run_search(lambda request: httpx.Response(400, content=b"Missing required fields"))

    assert execution.http_status == 400
    assert execution.response_body == "Missing required fields"
    assert execution.events == []


def test_run_search_captures_a_request_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    execution = _run_search(handler)

    assert execution.http_status is None
    assert execution.request_error == "ConnectError: Connection refused"


class _SlowStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"stage": "starting pipeline"}\n\n'
        await asyncio.sleep(5)
        yield b'data: {"stage": "retrieved datasets"}\n\n'


def test_run_search_times_out_keeping_the_events_received_before_it():
    execution = _run_search(lambda request: httpx.Response(200, stream=_SlowStream()), timeout_seconds=0.2)

    assert execution.timed_out
    assert [event.data for event in execution.events] == [{"stage": "starting pipeline"}]
