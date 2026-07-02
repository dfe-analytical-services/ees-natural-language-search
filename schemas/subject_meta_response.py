"""
Subject Meta response Pydantic models
"""

from functools import cached_property
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel
from typing import Any


class _SubjectMetaBaseResponseModel(BaseModel):
    """Base model for Subject Meta response Pydantic models."""

    model_config = ConfigDict(
        alias_generator=to_camel,  # map camelCase JSON keys to snake_case attributes
        validate_by_alias=True,
        validate_by_name=True,
        extra="ignore",
    )


class FilterItem(_SubjectMetaBaseResponseModel):
    id: str = Field(alias="value")
    label: str


class FilterItemGroup(_SubjectMetaBaseResponseModel):
    id: str
    filter_items: list[FilterItem] = Field(alias="options")
    label: str


class Filter(_SubjectMetaBaseResponseModel):
    id: str
    auto_select_filter_item_id: str | None = None
    filter_item_groups: dict[str, FilterItemGroup] = Field(alias="options")
    group_csv_column: str | None = None
    hint: str | None = None
    label: str = Field(alias="legend")
    name: str


class Indicator(_SubjectMetaBaseResponseModel):
    id: str = Field(alias="value")
    label: str
    name: str


class IndicatorGroup(_SubjectMetaBaseResponseModel):
    id: str
    indicators: list[Indicator] = Field(alias="options")
    label: str


class TimePeriod(_SubjectMetaBaseResponseModel):
    code: str
    label: str
    year: int


class TimePeriods(_SubjectMetaBaseResponseModel):
    options: list[TimePeriod]


class SubjectMetaResponse(_SubjectMetaBaseResponseModel):
    filters: dict[str, Filter]
    indicators: dict[str, IndicatorGroup]
    locations: dict[str, Any]
    time_period: TimePeriods


    @cached_property
    def _filter_item_lookup(self) -> dict[tuple[str, str, str], FilterItem]:
        """Keyed by (filter label, filter item group label, filter item label).

        Filter item labels are only unique within a filter item group, and filter item group labels only
        within a filter, so the full triple is needed.
        """
        return {
            (filter_.label, filter_item.label, filter_item.label): filter_item
            for filter_ in self.filters.values()
            for filter_item_group in filter_.filter_item_groups.values()
            for filter_item in filter_item_group.filter_items
        }


    def get_filter_item(self,
                        filter_label: str,
                        filter_item_group_label: str,
                        filter_item_label: str) -> FilterItem:
        return self._filter_item_lookup[(filter_label, filter_item_group_label, filter_item_label)]


    @cached_property
    def _indicator_lookup(self) -> dict[str, Indicator]:
        """Keyed by indicator label.

        Assumes that indicator labels are unique across groups
        """
        return {
            indicator.label: indicator
            for indicator_group in self.indicators.values()
            for indicator in indicator_group.indicators
        }


    def get_indicator(self, indicator_label: str) -> Indicator:
        return self._indicator_lookup[indicator_label]