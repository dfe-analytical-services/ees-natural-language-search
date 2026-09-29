"""
Gold standard queries file Pydantic models

The file is written by hand, so the models are strict: a misspelt field fails validation rather than
being silently ignored.

Expected results are identified by labels and codes rather than ids, because the file ids, filter item
ids and indicator ids of a dataset are regenerated with every new release version, whereas its data set
file id, labels and location codes are not.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from schemas.shared.base_models import StrictCamelModel

ANY_FILTER_ITEMS = "*"


class ExpectedTimePeriod(StrictCamelModel):
    """A time period, e.g. Academic year 2025/26 (code: AY, year: 2025)."""

    code: str
    year: int


class ExpectedTimePeriodRange(StrictCamelModel):
    start: ExpectedTimePeriod
    end: ExpectedTimePeriod


class ExpectedDataset(StrictCamelModel):
    """A dataset the query is expected to return, and optionally what should be selected for it.

    Any selection left unset is not compared."""

    data_set_file_id: str = Field(min_length=1)
    title: str | None = Field(
        default=None, description="For readability of the file only, not compared."
    )
    max_rank: int | None = Field(
        default=None,
        ge=1,
        description="The lowest acceptable position of the dataset in the results, where 1 is the first result.",
    )
    required: bool = Field(
        default=True,
        description="Whether the query fails when the dataset is missing, rather than it just being acceptable.",
    )
    filters: dict[str, list[str] | Literal["*"]] = Field(
        default_factory=dict,
        description="Keyed by filter label. The value is the expected filter item labels, or '*' if any selection is acceptable.",
    )
    indicators: list[str] = Field(
        default_factory=list, description="Expected indicator labels."
    )
    time_period: ExpectedTimePeriodRange | None = None
    locations: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Keyed by geographic level label. The value is the expected location codes.",
    )


class ExpectedResults(StrictCamelModel):
    min_datasets: int | None = Field(default=None, ge=0)
    datasets: list[ExpectedDataset] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_data_set_file_ids_are_unique(self):
        duplicates = _duplicates(dataset.data_set_file_id for dataset in self.datasets)
        if duplicates:
            raise ValueError(
                f"Expected datasets must be unique, duplicated data set file ids: {', '.join(duplicates)}"
            )
        return self


class GoldStandardQuery(StrictCamelModel):
    id: str = Field(min_length=1)
    description: str | None = None
    user_query: str = Field(min_length=1)
    publication_id: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    expected: ExpectedResults | None = Field(
        default=None,
        description="Leave unset to only report on how the query was executed, e.g. its status, duration and cost.",
    )


class GoldStandard(StrictCamelModel):
    queries: list[GoldStandardQuery] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_query_ids_are_unique(self):
        duplicates = _duplicates(query.id for query in self.queries)
        if duplicates:
            raise ValueError(
                f"Query ids must be unique, duplicated query ids: {', '.join(duplicates)}"
            )
        return self

    def select(self, query_ids: list[str], tags: list[str]) -> list[GoldStandardQuery]:
        """Selects the queries matching any of the given query ids or tags, or every query if neither are given."""
        unknown_query_ids = set(query_ids) - {query.id for query in self.queries}
        if unknown_query_ids:
            raise ValueError(f"Unknown query ids: {', '.join(sorted(unknown_query_ids))}")

        if not query_ids and not tags:
            return list(self.queries)

        selected = [
            query
            for query in self.queries
            if query.id in query_ids or not set(query.tags).isdisjoint(tags)
        ]
        if not selected:
            raise ValueError("No queries match the given query ids or tags")
        return selected


class GoldStandardFileError(Exception):
    def __init__(self, path: Path, problems: list[str]):
        self.problems = problems
        super().__init__(
            f"{path} is not a valid gold standard file:\n"
            + "\n".join(f"  - {problem}" for problem in problems)
        )


def load_gold_standard(path: Path) -> GoldStandard:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise GoldStandardFileError(
            path, [f"Invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}"]
        ) from e

    try:
        return GoldStandard.model_validate(raw)
    except ValidationError as e:
        raise GoldStandardFileError(path, _describe_validation_errors(e, raw)) from e


def _describe_validation_errors(error: ValidationError, raw: Any) -> list[str]:
    """Describes each validation error, naming the query it's in by id so that it can be found in the file."""
    problems = []
    for validation_error in error.errors():
        location = list(validation_error["loc"])
        subject = None

        if len(location) >= 2 and location[0] == "queries" and isinstance(location[1], int):
            query_id = _get_query_id(raw, location[1])
            subject = f"Query '{query_id}'" if query_id else f"Query at index {location[1]}"
            location = location[2:]

        if location:
            field = ".".join(str(part) for part in location)
            subject = f"{subject}, field '{field}'" if subject else f"Field '{field}'"

        message = validation_error["msg"]
        problems.append(f"{subject}: {message}" if subject else message)
    return problems


def _get_query_id(raw: Any, index: int) -> str | None:
    try:
        query_id = raw["queries"][index]["id"]
    except (KeyError, IndexError, TypeError):
        return None
    return query_id if isinstance(query_id, str) and query_id else None


def _duplicates(values) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)
