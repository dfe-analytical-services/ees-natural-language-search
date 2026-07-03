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
    def _filter_item_lookup(self) -> dict[tuple[str, str], FilterItem]:
        """Keyed by (filter item group id, filter item label).

        Assumes filter item labels are unique within a filter item group.
        """
        return {
            (filter_item_group.id, filter_item.label): filter_item
            for filter_ in self.filters.values()
            for filter_item_group in filter_.filter_item_groups.values()
            for filter_item in filter_item_group.filter_items
        }


    def get_filter_item(
        self,
        filter_item_group_id: str,
        filter_item_label: str
    ) -> FilterItem:
        filter_item = self._filter_item_lookup.get(
            (filter_item_group_id, filter_item_label)
        )
        if filter_item is None:
            raise KeyError(
                f"Filter item for group ID '{filter_item_group_id}' and label '{filter_item_label}' not found"
            )
        return filter_item


    @cached_property
    def _indicator_lookup(self) -> dict[str, Indicator]:
        """Keyed by indicator label.

        Assumes that indicator labels are unique across groups.
        """
        return {
            indicator.label: indicator
            for indicator_group in self.indicators.values()
            for indicator in indicator_group.indicators
        }


    def get_indicator(self, indicator_label: str) -> Indicator:
        indicator = self._indicator_lookup.get(indicator_label)
        if indicator is None:
            raise KeyError(f"Indicator for label '{indicator_label}' not found")
        return indicator
