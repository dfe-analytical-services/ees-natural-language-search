"""
Reranking agent return model.
"""

from pydantic import BaseModel, ConfigDict, Field

from schemas.reranker_response import RerankerResponse
from schemas.token_usage import TokenUsage


class RerankingAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grouped_filters: dict[str, list[str]] = Field(default_factory=dict)
    grouped_indicators: dict[str, list[str]] = Field(default_factory=dict)
    reranker_response: RerankerResponse
    total_tokens_used: TokenUsage = Field(default_factory=TokenUsage)
