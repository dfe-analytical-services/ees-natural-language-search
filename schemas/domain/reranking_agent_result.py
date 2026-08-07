"""
Reranking agent return model.
"""

from pydantic import BaseModel, ConfigDict, Field

from schemas.llm.reranker_response import RerankerResponse
from schemas.shared.token_usage import TokenUsage


class RerankingAgentResult(BaseModel):
    """Internal DTO used to return results from the reranking agent."""

    model_config = ConfigDict(extra="forbid")

    grouped_filters: dict[str, list[str]] = Field(default_factory=dict)
    grouped_indicators: dict[str, list[str]] = Field(default_factory=dict)
    reranker_response: RerankerResponse
    total_tokens_used: TokenUsage = Field(default_factory=TokenUsage)
