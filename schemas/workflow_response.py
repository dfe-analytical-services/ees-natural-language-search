"""
Workflow response Pydantic models
"""

from pydantic import BaseModel, Field

from schemas.final_dataset_response import FinalDatasetResponse


class TokenUsage(BaseModel):
    input: int = 0
    output: int = 0


class PipelineCompleteData(BaseModel):
    datasets: list[FinalDatasetResponse] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    cost: float


class PipelineCompleteEvent(BaseModel):
    stage: str = "pipeline complete"
    data: PipelineCompleteData