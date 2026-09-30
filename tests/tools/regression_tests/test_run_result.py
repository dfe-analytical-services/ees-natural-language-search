"""Tests for classifying search executions into query results in `tools.regression_tests.run_result`."""

import copy

import pytest

from schemas.responses.final_dataset_response import (
    DatasetValidationError,
    DatasetValidationErrorCode,
    DatasetValidationWarning,
    DatasetValidationWarningCode,
)
from tools.regression_tests.report_models import ExecutionStatus
from tools.regression_tests.run_result import build_query_result

NO_INDICATORS_ERROR = DatasetValidationError(
    code=DatasetValidationErrorCode.NO_INDICATORS, message="No indicators"
)
NO_TIME_PERIOD_REQUIREMENT_WARNING = DatasetValidationWarning(
    code=DatasetValidationWarningCode.NO_TIME_PERIOD_REQUIREMENT,
    message="No time period requirement",
)


def _event_data(events: list[dict], stage: str) -> dict:
    return next(event["data"] for event in events if event.get("stage") == stage)


def test_completed_pipeline_is_a_success(query, build_final_dataset, build_pipeline_events, build_execution):
    events = build_pipeline_events(
        [build_final_dataset(file_id="file-1"), build_final_dataset(file_id="file-2")]
    )

    result = build_query_result(query, build_execution(events))

    assert result.status == ExecutionStatus.SUCCESS
    assert result.error_message is None
    assert result.last_stage == "pipeline complete"
    assert result.stage_timings == {
        "starting pipeline": 1.0,
        "retrieved datasets": 2.0,
        "reranker complete": 3.0,
        "pipeline complete": 4.0,
    }
    assert result.confidence == "high"
    assert result.query_requirements.filters == ["Secondary"]
    assert result.dataset_count == 2
    pipeline_complete = _event_data(events, "pipeline complete")
    assert result.token_usage.model_dump() == pipeline_complete["tokenUsage"]
    assert result.cost == pipeline_complete["cost"]
    assert not result.cost_is_partial
    assert result.dataset_summary.dataset_count == 2


def test_datasets_are_ranked_in_order_with_relevance_scores_from_the_reranker(
    query, build_final_dataset, build_pipeline_events, build_execution
):
    events = build_pipeline_events(
        [build_final_dataset(file_id="file-1"), build_final_dataset(file_id="file-2")]
    )

    result = build_query_result(query, build_execution(events))

    assert [(dataset.rank, dataset.file_id, dataset.relevance_score) for dataset in result.datasets] == [
        (1, "file-1", 90),
        (2, "file-2", 80),
    ]


def test_validation_errors_make_a_success_with_validation_errors(
    query, build_final_dataset, build_pipeline_events, build_execution
):
    events = build_pipeline_events(
        [
            build_final_dataset(file_id="file-1"),
            build_final_dataset(file_id="file-2", validation_errors=[NO_INDICATORS_ERROR]),
        ]
    )

    result = build_query_result(query, build_execution(events))

    assert result.status == ExecutionStatus.SUCCESS_WITH_VALIDATION_ERRORS
    assert [dataset.is_valid_for_table_generation for dataset in result.datasets] == [True, False]
    assert result.datasets[1].validation_errors == [NO_INDICATORS_ERROR]


def test_validation_warnings_alone_are_a_success(
    query, build_final_dataset, build_pipeline_events, build_execution
):
    events = build_pipeline_events(
        [build_final_dataset(validation_warnings=[NO_TIME_PERIOD_REQUIREMENT_WARNING])]
    )

    result = build_query_result(query, build_execution(events))

    assert result.status == ExecutionStatus.SUCCESS
    assert result.datasets[0].validation_warnings == [NO_TIME_PERIOD_REQUIREMENT_WARNING]


def test_error_event_is_an_sse_error_with_partial_cost_from_the_reranker(
    query, build_pipeline_events, build_execution
):
    events = build_pipeline_events(include_pipeline_complete=False) + [
        {"error": "Relevant dataset for file ID 'x' not found"}
    ]

    result = build_query_result(query, build_execution(events))

    assert result.status == ExecutionStatus.SSE_ERROR
    assert result.error_message == "Relevant dataset for file ID 'x' not found"
    assert result.last_stage == "reranker complete"
    assert result.dataset_count is None
    assert result.datasets == []
    reranker_complete = _event_data(events, "reranker complete")
    assert result.token_usage.model_dump() == reranker_complete["tokenUsage"]
    assert result.cost == reranker_complete["cost"]
    assert result.cost_is_partial


def test_error_event_before_the_reranker_has_no_cost(query, build_execution):
    result = build_query_result(
        query, build_execution([{"stage": "starting pipeline"}, {"error": "Search failed"}])
    )

    assert result.status == ExecutionStatus.SSE_ERROR
    assert result.last_stage == "starting pipeline"
    assert result.token_usage is None
    assert result.cost is None
    assert result.cost_is_partial


def test_stream_ending_before_pipeline_complete_is_incomplete(query, build_pipeline_events, build_execution):
    events = build_pipeline_events(include_pipeline_complete=False)

    result = build_query_result(query, build_execution(events))

    assert result.status == ExecutionStatus.INCOMPLETE_STREAM
    assert "'reranker complete'" in result.error_message
    assert result.cost_is_partial


def test_stream_without_events_is_incomplete(query, build_execution):
    result = build_query_result(query, build_execution([]))

    assert result.status == ExecutionStatus.INCOMPLETE_STREAM
    assert result.last_stage is None
    assert result.error_message == "The stream ended without any events"


def test_timeout_keeps_the_stages_received_before_it(query, build_pipeline_events, build_execution):
    events = build_pipeline_events(include_pipeline_complete=False)

    result = build_query_result(query, build_execution(events, timed_out=True, duration_seconds=180))

    assert result.status == ExecutionStatus.TIMEOUT
    assert result.error_message == "Timed out after 180.0s"
    assert result.last_stage == "reranker complete"
    assert result.cost == _event_data(events, "reranker complete")["cost"]


def test_non_200_response_is_an_http_error(query, build_execution):
    result = build_query_result(
        query, build_execution([], http_status=400, response_body="Missing required fields")
    )

    assert result.status == ExecutionStatus.HTTP_ERROR
    assert result.http_status == 400
    assert result.error_message == "HTTP 400: Missing required fields"


def test_request_error_is_an_http_error(query, build_execution):
    result = build_query_result(
        query, build_execution([], http_status=None, request_error="ConnectError: refused")
    )

    assert result.status == ExecutionStatus.HTTP_ERROR
    assert result.error_message == "ConnectError: refused"


@pytest.mark.parametrize(
    "event_data, expected_message",
    [
        pytest.param("not json", "not a JSON object", id="not_json"),
        pytest.param(["a", "list"], "not a JSON object", id="not_an_object"),
        pytest.param({"stage": "new stage"}, "Unknown event stage: 'new stage'", id="unknown_stage"),
        pytest.param(
            {"stage": "retrieved datasets", "data": {"datasets": [], "newField": 1}},
            "The 'retrieved datasets' event doesn't match the response schema",
            id="unexpected_field",
        ),
    ],
)
def test_events_not_matching_the_schemas_are_a_contract_mismatch(
    query, build_execution, event_data, expected_message
):
    result = build_query_result(query, build_execution([{"stage": "starting pipeline"}, event_data]))

    assert result.status == ExecutionStatus.CONTRACT_MISMATCH
    assert expected_message in result.error_message


def test_inconsistent_is_valid_for_table_generation_is_a_contract_mismatch(
    query, build_final_dataset, build_pipeline_events, build_execution
):
    events = build_pipeline_events([build_final_dataset(validation_errors=[NO_INDICATORS_ERROR])])
    events[-1]["data"]["datasets"][0]["isValidForTableGeneration"] = True

    result = build_query_result(query, build_execution(events))

    assert result.status == ExecutionStatus.CONTRACT_MISMATCH
    assert "isValidForTableGeneration" in result.error_message


def test_raw_events_are_reported_exactly_as_received(
    query, build_final_dataset, build_pipeline_events, build_execution
):
    events = build_pipeline_events([build_final_dataset()])
    received = copy.deepcopy(events)

    result = build_query_result(query, build_execution(events))

    assert [event.data for event in result.raw_events] == received
    assert result.raw_events[-1].data["data"]["datasets"][0]["isValidForTableGeneration"] is True


# Streams captured from the dev environment, as the service's own output rather than events built by the tests
REAL_STREAM_CASES = [
    pytest.param(
        "nl_search_sse_success.json",
        ExecutionStatus.SUCCESS,
        [[]],
        [["no_time_period_requirement"]],
        id="success",
    ),
    pytest.param(
        "nl_search_sse_validation_errors.json",
        ExecutionStatus.SUCCESS_WITH_VALIDATION_ERRORS,
        [["no_indicators"]],
        [["unfiltered_filters", "no_location_requirement"]],
        id="validation_errors",
    ),
    pytest.param(
        "nl_search_sse_no_datasets.json",
        ExecutionStatus.SUCCESS,
        [],
        [],
        id="no_datasets",
    ),
]


@pytest.mark.parametrize("fixture, expected_status, expected_error_codes, expected_warning_codes", REAL_STREAM_CASES)
def test_real_streams(
    query, load_json_fixture, build_execution, fixture, expected_status, expected_error_codes, expected_warning_codes
):
    events = load_json_fixture(fixture)

    result = build_query_result(query, build_execution(events))

    assert result.status == expected_status
    assert result.last_stage == "pipeline complete"
    assert result.dataset_count == len(expected_error_codes)
    assert [[error.code for error in dataset.validation_errors] for dataset in result.datasets] == expected_error_codes
    assert [[warning.code for warning in dataset.validation_warnings] for dataset in result.datasets] == expected_warning_codes

    pipeline_complete = _event_data(events, "pipeline complete")
    assert result.token_usage.model_dump() == pipeline_complete["tokenUsage"]
    assert result.cost == pipeline_complete["cost"]
    assert not result.cost_is_partial


def test_real_stream_relevance_scores_and_query_requirements_come_from_the_reranker(
    query, load_json_fixture, build_execution
):
    events = load_json_fixture("nl_search_sse_success.json")

    result = build_query_result(query, build_execution(events))

    reranker_complete = _event_data(events, "reranker complete")
    assert [dataset.relevance_score for dataset in result.datasets] == [
        dataset["relevanceScore"] for dataset in reranker_complete["datasets"]
    ]
    assert result.confidence == reranker_complete["confidence"]
    assert result.query_requirements.geography == ["London"]
    assert result.query_requirements.time_period is None
