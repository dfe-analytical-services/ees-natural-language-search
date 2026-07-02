"""
Indicator selection response Pydantic models
"""

from pydantic import BaseModel, RootModel


class IndicatorDecision(BaseModel):
    relevant: bool = False
    reasoning: str = ""


class IndicatorSelectionResponse(RootModel[dict[str, dict[str, IndicatorDecision]]]):
    """Indicator selection results, keyed by dataset fileId, then indicator label."""
