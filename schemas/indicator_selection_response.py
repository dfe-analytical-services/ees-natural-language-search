"""
Indicator selection response Pydantic models
"""

from pydantic import BaseModel, RootModel


class IndicatorDecision(BaseModel):
    relevant: bool = False
    reasoning: str = ""


class IndicatorSelectionResponse(RootModel[dict[str, dict[str, IndicatorDecision]]]):
    """keyed by fileId"""
