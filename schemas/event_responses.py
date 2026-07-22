"""
Event response Pydantic models
"""

from pydantic import BaseModel, Field
from schemas.final_dataset_response import FinalDatasetResponse
from schemas.relevant_dataset_response import RelevantDatasetResponse
from schemas.reranker_dataset_response import RerankerDatasetResponse
from schemas.reranker_response import QueryRequirements
from schemas.token_usage import TokenUsage


class RetrievedDatasetsEventData(BaseModel):
    datasets: list[RelevantDatasetResponse] = Field(default_factory=list)


class RerankerEventData(BaseModel):
    confidence: str
    datasets: list[RerankerDatasetResponse] = Field(default_factory=list)
    query_requirements: QueryRequirements
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    cost: float


class PipelineCompleteEventData(BaseModel):
    datasets: list[FinalDatasetResponse] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    cost: float


class StartEventResponse(BaseModel):
    stage: str = "starting pipeline"


class RetrievedDatasetsEventResponse(BaseModel):
    stage: str = "retrieved datasets"
    data: RetrievedDatasetsEventData


class PipelineCompleteEventResponse(BaseModel):
    stage: str = "pipeline complete"
    data: PipelineCompleteEventData


class RerankerEventResponse(BaseModel):
    stage: str = "reranker complete"
    data: RerankerEventData
