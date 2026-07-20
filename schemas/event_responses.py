"""
Event response Pydantic models
"""

from pydantic import BaseModel, Field
from schemas.final_dataset_response import FinalDatasetResponse
from schemas.relevant_dataset_response import RelevantDatasetResponse
from schemas.token_usage import TokenUsage


class RetrievedDatasetsEventData(BaseModel):
    datasets: list[RelevantDatasetResponse] = Field(default_factory=list)

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
