"""Tests for streaming search requests in `tools.regression_tests.sse_client`."""

import asyncio

import httpx

from tools.regression_tests.sse_client import SseDataParser, run_search

SEARCH_URL = "https://test/api/natural_language_search_function"


def _feed_lines(lines: list[str]) -> list[str]:
    parser = SseDataParser()
    return [data for line in lines if (data := parser.feed(line)) is not None]


def test_parser_returns_the_data_of_each_event():
    assert _feed_lines(['data: {"a": 1}', "", 'data: {"b": 2}', ""]) == ['{"a": 1}', '{"b": 2}']


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


class _SlowStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"stage": "starting pipeline"}\n\n'
        await asyncio.sleep(5)
        yield b'data: {"stage": "retrieved datasets"}\n\n'


def test_run_search_times_out_keeping_the_events_received_before_it():
    execution = _run_search(lambda request: httpx.Response(200, stream=_SlowStream()), timeout_seconds=0.2)

    assert execution.timed_out
    assert [event.data for event in execution.events] == [{"stage": "starting pipeline"}]
