from collections import defaultdict
from rapidfuzz import process, fuzz
from schemas.domain.dataset_with_subject_meta import DatasetWithSubjectMeta
from schemas.domain.locations_response import LocationItem, LocationsResponse
from schemas.ees_data_api.subject_meta_response import (
    GeographicLevel,
    LocationLevel,
    LocationOption,
    SubjectMetaResponse
)

# The location selected when a query has no location requirement
DEFAULT_LOCATION_GEOGRAPHIC_LEVEL = GeographicLevel.COUNTRY
DEFAULT_LOCATION_GEOGRAPHIC_LEVEL_LABEL = "national"
DEFAULT_LOCATION_NAME = "England"
DEFAULT_LOCATION_CODE = "E92000001"


def hybrid_scorer(a: str, b: str, **kwargs) -> float:
    a_tokens = set(a.lower().split())
    b_tokens = set(b.lower().split())

    tsr = fuzz.token_set_ratio(a, b)

    if tsr == 100:
        # Guard 1: must match more than one token
        if len(a_tokens & b_tokens) < 2:
            return fuzz.WRatio(a, b)

        # Guard 2: candidate must not be too short
        if len(b_tokens) < len(a_tokens) * 0.6:
            return fuzz.WRatio(a, b)

        return 100.0

    return fuzz.WRatio(a, b)


def flatten_by_legend(
    locations: dict[GeographicLevel, LocationLevel]
) -> dict[str, list[LocationItem]]:
    """Flatten each geographic level's set of locations into a single list,
    keyed by the level's label, e.g. "National", "Regional", "Local authority" etc.
    """
    flattened: dict[str, list[LocationItem]] = defaultdict(list)

    def walk(options: list[LocationOption], label: str) -> None:
        for option in options:
            if option.id is not None:
                flattened[label].append(
                    LocationItem(
                        id=option.id,
                        label=option.label,
                        value=option.value
                    )
                )

            walk(option.options or [], label)

    for location_level in locations.values():
        walk(location_level.options, location_level.label)

    return dict(flattened)


def get_default_location(
    subject_meta: SubjectMetaResponse
) -> tuple[str, LocationItem] | None:
    """Find the default location within the dataset's subject meta locations at the default
    location's geographic level. Returns it alongside that level's label,
    e.g. ("National", LocationItem(label="England", ...)).

    Returns `None` when the dataset has no locations at the default location's
    geographic level, or doesn't have the default location within it.
    """
    level_locations = subject_meta.locations.get(DEFAULT_LOCATION_GEOGRAPHIC_LEVEL)
    if level_locations is None:
        return None

    # Flatten the level's options by label, supporting both flat lists and
    # nested location hierarchies.
    flattened = flatten_by_legend({DEFAULT_LOCATION_GEOGRAPHIC_LEVEL: level_locations})

    for label, options in flattened.items():
        for option in options:
            if option.value == DEFAULT_LOCATION_CODE:
                return label, option

    return None


async def get_location_matches(
    datasets_by_id: dict[str, DatasetWithSubjectMeta],
    location_requirements: list[str],
    threshold: int = 90,
) -> LocationsResponse:
    valid_geo_per_file: dict[str, dict[str, list[LocationItem]]] = {}
    for file_id, dataset in datasets_by_id.items():
        subject_meta = dataset.subject_meta
        valid_geographies = flatten_by_legend(subject_meta.locations)
        level_results = defaultdict(list)
        for level in valid_geographies:
            options = valid_geographies[level]
            for query in location_requirements:
                matches = process.extract(
                    query,
                    options,
                    scorer=hybrid_scorer,
                    processor=lambda x: x.label if isinstance(x, LocationItem) else x,
                    limit=10
                )
                results = [x for x,score,_ in matches if score>=threshold]
                level_results[level].extend(results)
        valid_geo_per_file[file_id] = dict(level_results)

    return LocationsResponse(valid_geo_per_file)
