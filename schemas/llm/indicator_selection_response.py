"""
LLM Indicator selection response Pydantic models
"""

from pydantic import BaseModel, RootModel


class IndicatorDecision(BaseModel):
    relevant: bool = False
    reasoning: str = ""


class IndicatorDatasetResult(RootModel[dict[str, IndicatorDecision]]):
    """Indicator decisions for a single dataset, keyed by indicator label."""
