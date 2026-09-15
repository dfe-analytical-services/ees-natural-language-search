"""
Filter item candidate Pydantic models
"""

from pydantic import BaseModel, RootModel

from schemas.ees_data_api.subject_meta_response import FilterItem


class FilterItemCandidate(BaseModel):
    """A single filter item provided to the filter selection agent, plus the ID and label of the filter that owns it."""

    filter_id: str
    filter_label: str
    filter_item: FilterItem


class DatasetFilterItemCandidates(RootModel[dict[int, FilterItemCandidate]]):
    """The filter items provided to the filter selection agent for a single dataset, keyed by a
    reference number which the model returns its decisions against.
    Reference numbers begin at 1 and are only meaningful within a single dataset's prompt.
    """

    @staticmethod
    def parse_reference(raw_reference: str) -> int | None:
        """Parses a string reference number as the model returned it in a JSON object key.
        Returns None if it isn't an integer.
        """
        try:
            return int(raw_reference.strip())
        except (AttributeError, TypeError, ValueError):
            return None

    def get(self, reference: int) -> FilterItemCandidate | None:
        return self.root.get(reference)

    def resolve(self, raw_reference: str) -> FilterItemCandidate | None:
        """Parses a raw reference number as the model returned it and returns its candidate.
        Returns None if the reference isn't an integer, or if there is no candidate for it.
        """
        reference = self.parse_reference(raw_reference)
        return self.get(reference) if reference is not None else None
