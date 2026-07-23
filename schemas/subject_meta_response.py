"""
Subject Meta response Pydantic models
"""

from functools import cached_property
from pydantic import Field
from typing import Any

from schemas.base_models import CamelModel


class FilterItem(CamelModel):
    id: str = Field(alias="value")
    label: str


class FilterItemGroup(CamelModel):
    id: str
    filter_items: list[FilterItem] = Field(alias="options")
    label: str


class Filter(CamelModel):
    id: str
    auto_select_filter_item_id: str | None = None
    filter_item_groups: dict[str, FilterItemGroup] = Field(alias="options")
    group_csv_column: str | None = None
    hint: str | None = None
    label: str = Field(alias="legend")
    name: str


class Indicator(CamelModel):
    id: str = Field(alias="value")
    label: str
    name: str


class IndicatorGroup(CamelModel):
    id: str
    indicators: list[Indicator] = Field(alias="options")
    label: str


class TimePeriod(CamelModel):
    code: str
    label: str
    year: int


class TimePeriods(CamelModel):
    options: list[TimePeriod]


class SubjectMetaResponse(CamelModel):
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
