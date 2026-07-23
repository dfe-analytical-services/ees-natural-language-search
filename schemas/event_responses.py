"""
Event response Pydantic models
"""

from pydantic import Field
from schemas.base_models import StrictCamelModel
from schemas.final_dataset_response import FinalDatasetResponse
from schemas.relevant_dataset_response import RelevantDatasetResponse
from schemas.reranker_dataset_response import RerankerDatasetResponse
from schemas.reranker_response import QueryRequirements
from schemas.token_usage import TokenUsage


class RetrievedDatasetsEventData(StrictCamelModel):
    datasets: list[RelevantDatasetResponse] = Field(default_factory=list)


class RerankerEventData(StrictCamelModel):
    confidence: str
    datasets: list[RerankerDatasetResponse] = Field(default_factory=list)
    query_requirements: QueryRequirements
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    cost: float


class PipelineCompleteEventData(StrictCamelModel):
    datasets: list[FinalDatasetResponse] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    cost: float


class StartEventResponse(StrictCamelModel):
    stage: str = "starting pipeline"


class RetrievedDatasetsEventResponse(StrictCamelModel):
    stage: str = "retrieved datasets"
    data: RetrievedDatasetsEventData


class PipelineCompleteEventResponse(StrictCamelModel):
    stage: str = "pipeline complete"
    data: PipelineCompleteEventData


class RerankerEventResponse(StrictCamelModel):
    stage: str = "reranker complete"
    data: RerankerEventData
