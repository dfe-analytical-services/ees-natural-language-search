from functools import cached_property
from pydantic import BaseModel, Field, ConfigDict


class SubjectMetaResponse(BaseModel):
    filters: dict
    indicators: dict[str, IndicatorGroup]
    locations: dict
    timePeriod: TimePeriods

    @cached_property
    def indicator_lookup_by_label(self) -> dict[str, Indicator]:
        # Assume that indicator labels are unique across groups
        return {
            indicator.label: indicator
            for indicator_group in self.indicators.values()
            for indicator in indicator_group.indicators
        }


class IndicatorGroup(BaseModel):
    model_config = ConfigDict(validate_by_alias=True)
    id: str
    label: str
    indicators: list[Indicator] = Field(alias="options")


class Indicator(BaseModel):
    model_config = ConfigDict(validate_by_alias=True)

    id: str = Field(alias="value")
    label: str
    name: str


class TimePeriods(BaseModel):
    options: list[TimePeriod]


class TimePeriod(BaseModel):
    code: str
    label: str
    year: int
