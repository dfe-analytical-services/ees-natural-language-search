"""
Event response Pydantic models
"""

from pydantic import Field
from schemas.shared.base_models import StrictCamelModel
from schemas.responses.final_dataset_response import FinalDatasetResponse
from schemas.responses.relevant_dataset_response import RelevantDatasetResponse
from schemas.responses.reranker_dataset_response import RerankerDatasetResponse
from schemas.shared.token_usage import TokenUsage


class QueryRequirements(StrictCamelModel):
    """The reranker's inferred query requirements.
    Duplicated from schemas.llm.reranker_response.QueryRequirements so the response shape can diverge from the LLM response shape in future."""

    filters: list[str] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=list)
    time_period: str | None = None


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
