"""Interprets the events collected from a search request as a query result for the report.

Events are validated against the service's own response schemas in `schemas/responses`, so that any
divergence between the service and this script is reported as a contract mismatch rather than ignored.
"""

import copy
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from schemas.responses.event_responses import (
    PipelineCompleteEventData,
    PipelineCompleteEventResponse,
    RerankerEventData,
    RerankerEventResponse,
    RetrievedDatasetsEventResponse,
    StartEventResponse,
)
from tools.regression_tests.input_models import GoldStandardQuery
from tools.regression_tests.report_models import (
    COMPLETED_STATUSES,
    DatasetResult,
    ExecutionStatus,
    QueryResult,
    RawEvent,
)
from tools.regression_tests.sse_client import SearchExecution, SseEvent
from tools.regression_tests.summaries import summarise_datasets

EVENT_MODELS_BY_STAGE = {
    model.model_fields["stage"].default: model
    for model in (
        StartEventResponse,
        RetrievedDatasetsEventResponse,
        RerankerEventResponse,
        PipelineCompleteEventResponse,
    )
}

# The key of the computed `FinalDatasetResponse.is_valid_for_table_generation` field. The API outputs it,
# but it's rejected as an extra input when validating, so it's removed and checked against the recomputed value.
IS_VALID_FOR_TABLE_GENERATION_KEY = "isValidForTableGeneration"

MAX_ERROR_DETAIL_LENGTH = 500


class ContractMismatchError(Exception):
    pass


@dataclass
class _ParsedEvents:
    stage_timings: dict[str, float] = field(default_factory=dict)
    last_stage: str | None = None
    reranker: RerankerEventData | None = None
    pipeline_complete: PipelineCompleteEventData | None = None
    error_message: str | None = None
    contract_mismatch: str | None = None


def build_query_result(query: GoldStandardQuery, execution: SearchExecution) -> QueryResult:
    parsed = _parse_events(execution.events)
    status, error_message = _classify(execution, parsed)

    is_completed = status in COMPLETED_STATUSES
    datasets = _build_dataset_results(parsed) if is_completed else []

    # The tokens and cost of a pipeline that didn't complete are only known up to the reranker stage
    usage_source = parsed.pipeline_complete or parsed.reranker

    return QueryResult(
        query_id=query.id,
        user_query=query.user_query,
        publication_id=query.publication_id,
        tags=query.tags,
        status=status,
        error_message=error_message,
        last_stage=parsed.last_stage,
        http_status=execution.http_status,
        duration_seconds=round(execution.duration_seconds, 3),
        stage_timings=parsed.stage_timings,
        confidence=parsed.reranker.confidence if parsed.reranker else None,
        query_requirements=parsed.reranker.query_requirements if parsed.reranker else None,
        dataset_count=len(datasets) if is_completed else None,
        token_usage=usage_source.token_usage if usage_source else None,
        cost=usage_source.cost if usage_source else None,
        cost_is_partial=parsed.pipeline_complete is None,
        dataset_summary=summarise_datasets(datasets) if is_completed else None,
        datasets=datasets,
        raw_events=[
            RawEvent(elapsed_seconds=round(event.elapsed_seconds, 3), data=event.data)
            for event in execution.events
        ],
    )


def _classify(
    execution: SearchExecution, parsed: _ParsedEvents
) -> tuple[ExecutionStatus, str | None]:
    if execution.timed_out:
        return ExecutionStatus.TIMEOUT, (
            f"Timed out after {execution.duration_seconds:.1f}s"
        )
    if execution.request_error is not None:
        return ExecutionStatus.HTTP_ERROR, execution.request_error
    if execution.http_status != 200:
        return ExecutionStatus.HTTP_ERROR, (
            f"HTTP {execution.http_status}: {execution.response_body or ''}".strip()
        )
    if parsed.contract_mismatch is not None:
        return ExecutionStatus.CONTRACT_MISMATCH, parsed.contract_mismatch
    if parsed.error_message is not None:
        return ExecutionStatus.SSE_ERROR, parsed.error_message
    if parsed.pipeline_complete is None:
        return ExecutionStatus.INCOMPLETE_STREAM, (
            f"The stream ended after the '{parsed.last_stage}' stage"
            if parsed.last_stage
            else "The stream ended without any events"
        )
    if any(dataset.validation_errors for dataset in parsed.pipeline_complete.datasets):
        return ExecutionStatus.SUCCESS_WITH_VALIDATION_ERRORS, None
    return ExecutionStatus.SUCCESS, None


def _parse_events(events: list[SseEvent]) -> _ParsedEvents:
    parsed = _ParsedEvents()
    for event in events:
        try:
            _parse_event(event, parsed)
        except ContractMismatchError as e:
            parsed.contract_mismatch = str(e)
            break
        except ValidationError as e:
            parsed.contract_mismatch = _truncate(
                f"The '{_get_stage(event)}' event doesn't match the response schema: {e}"
            )
            break

        if parsed.error_message is not None:
            break
    return parsed


def _get_stage(event: SseEvent) -> str | None:
    return event.data.get("stage") if isinstance(event.data, dict) else None


def _parse_event(event: SseEvent, parsed: _ParsedEvents) -> None:
    data = event.data
    if not isinstance(data, dict):
        raise ContractMismatchError(
            _truncate(f"An event's data is not a JSON object: {data}")
        )

    # The route streams `{"error": <message>}` when the workflow raises, instead of a stage event
    if "error" in data:
        parsed.error_message = str(data["error"])
        return

    stage = data.get("stage")
    event_model = EVENT_MODELS_BY_STAGE.get(stage)
    if event_model is None:
        raise ContractMismatchError(f"Unknown event stage: {stage!r}")

    if event_model is PipelineCompleteEventResponse:
        parsed.pipeline_complete = _parse_pipeline_complete_event(data)
    elif event_model is RerankerEventResponse:
        parsed.reranker = RerankerEventResponse.model_validate(data).data
    else:
        event_model.model_validate(data)

    parsed.stage_timings[stage] = round(event.elapsed_seconds, 3)
    parsed.last_stage = stage


def _parse_pipeline_complete_event(data: dict[str, Any]) -> PipelineCompleteEventData:
    # Copied, so that the raw event is reported exactly as it was received
    data = copy.deepcopy(data)
    datasets = data.get("data", {}).get("datasets", [])
    reported_validity = [
        dataset.pop(IS_VALID_FOR_TABLE_GENERATION_KEY, None)
        for dataset in datasets
        if isinstance(dataset, dict)
    ]

    event_data = PipelineCompleteEventResponse.model_validate(data).data

    for dataset, is_valid in zip(event_data.datasets, reported_validity):
        if is_valid != dataset.is_valid_for_table_generation:
            raise ContractMismatchError(
                f"Dataset '{dataset.file_id}' has '{IS_VALID_FOR_TABLE_GENERATION_KEY}' {is_valid}, "
                f"which is inconsistent with its validation errors"
            )
    return event_data


def _build_dataset_results(parsed: _ParsedEvents) -> list[DatasetResult]:
    relevance_scores_by_file_id = (
        {dataset.file_id: dataset.relevance_score for dataset in parsed.reranker.datasets}
        if parsed.reranker
        else {}
    )

    return [
        DatasetResult(
            rank=rank,
            file_id=dataset.file_id,
            data_set_file_id=dataset.data_set_file_id,
            subject_id=dataset.subject_id,
            title=dataset.title,
            relevance_score=relevance_scores_by_file_id.get(dataset.file_id),
            is_valid_for_table_generation=dataset.is_valid_for_table_generation,
            validation_errors=dataset.validation_errors,
            validation_warnings=dataset.validation_warnings,
            filters=dataset.filters,
            indicators=dataset.indicators,
            time_period=dataset.time_period,
            geographic_levels=dataset.geographic_levels,
            auto_selected_filter_items=dataset.auto_selected_filter_items,
            unfiltered_filters=dataset.unfiltered_filters,
        )
        for rank, dataset in enumerate(parsed.pipeline_complete.datasets, start=1)
    ]


def _truncate(message: str) -> str:
    if len(message) <= MAX_ERROR_DETAIL_LENGTH:
        return message
    return message[:MAX_ERROR_DETAIL_LENGTH] + "..."
