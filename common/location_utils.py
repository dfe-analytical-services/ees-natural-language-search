import re
from collections import defaultdict
from enum import IntEnum

from rapidfuzz import fuzz

from common.default_location import (
    DEFAULT_LOCATION_CODE,
    DEFAULT_LOCATION_GEOGRAPHIC_LEVEL,
)
from schemas.domain.dataset_with_subject_meta import DatasetWithSubjectMeta
from schemas.domain.locations_response import LocationItem, LocationsResponse
from schemas.ees_data_api.subject_meta_response import (
    GeographicLevel,
    LocationLevel,
    LocationOption,
    SubjectMetaResponse
)


# The only words that can differ between two location names without making them
# different places, e.g. "County Durham" is "Durham" and "North East" is "the North
# East". Any other extra word names somewhere more or less specific: "East of England"
# is not "England", and "North East Lincolnshire" is not "North East".
GENERIC_QUALIFIER_TOKENS = frozenset(
    {
        "the",
        "of",
        "on",
        "in",
        "upon",
        "county",
        "borough",
        "district",
        "council",
        "authority",
    }
)

# EES disambiguates locations that share a name by appending their geographic code,
# e.g. "Barnsley (E08000016)".
_GEOGRAPHIC_CODE_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")

# Inverted administrative qualifiers, e.g. "Bristol, City of", "Herefordshire, County of".
# Only the inverted (comma) form is dropped - a leading qualifier is part of the name
# proper, so "City of London" keeps its "City of" and stays distinct from "London".
_INVERTED_QUALIFIER_SUFFIX = re.compile(
    r",\s*(city|county|borough|district)\s+of\s*$", re.IGNORECASE
)

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


class MatchTier(IntEnum):
    """How closely a location matches a location requirement. Lower is closer."""

    # The same place. Either the same name, or one differing only in generic
    # administrative wording, e.g. "County Durham" for "Durham".
    SAME_PLACE = 0
    # Somewhere named within the requirement, e.g. "North Yorkshire" for "Yorkshire",
    # or "Kingston upon Hull, City of" for "Hull".
    MORE_SPECIFIC = 1
    # Somewhere the requirement sits inside, e.g. "Manchester" for "Greater Manchester".
    LESS_SPECIFIC = 2
    # Neither name contains the other, but they are close enough to be a typo.
    SIMILAR_NAME = 3


# A rank of (tier, tie break), lowest first. The tie break is only used to prefer the
# LESS_SPECIFIC location that accounts for most of the requirement, so that "South West
# England" prefers the "South West" region over the whole of "England".
MatchRank = tuple[MatchTier, int]


def normalise_location_name(name: str) -> str:
    """Reduce a location name to the lowercase, punctuation free form used for matching,
    dropping the disambiguating geographic code and inverted administrative qualifier
    that EES adds to some labels.
    """
    name = _GEOGRAPHIC_CODE_SUFFIX.sub("", name)
    name = _INVERTED_QUALIFIER_SUFFIX.sub("", name)
    return _NON_ALPHANUMERIC.sub(" ", name.lower()).strip()


def rank_match(
    normalised_query: str,
    normalised_candidate: str,
    threshold: int,
) -> MatchRank | None:
    """Rank a candidate location name against a location requirement, or return None if
    they are not a match at all.
    """
    if normalised_query == normalised_candidate:
        return (MatchTier.SAME_PLACE, 0)

    query_tokens = set(normalised_query.split())
    candidate_tokens = set(normalised_candidate.split())

    # Where one name holds every word of the other, the extra words decide whether it is
    # the same place under a longer name or a different place altogether.
    if query_tokens < candidate_tokens:
        extra_tokens = candidate_tokens - query_tokens
        tier = MatchTier.MORE_SPECIFIC
    elif candidate_tokens < query_tokens:
        extra_tokens = query_tokens - candidate_tokens
        tier = MatchTier.LESS_SPECIFIC
    else:
        similarity = max(
            fuzz.ratio(normalised_query, normalised_candidate),
            fuzz.token_sort_ratio(normalised_query, normalised_candidate),
        )
        return (MatchTier.SIMILAR_NAME, 0) if similarity >= threshold else None

    if extra_tokens <= GENERIC_QUALIFIER_TOKENS:
        return (MatchTier.SAME_PLACE, 0)

    return (tier, len(extra_tokens) if tier is MatchTier.LESS_SPECIFIC else 0)


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


def match_location_requirement(
    location_requirement: str,
    locations_by_level: dict[str, list[LocationItem]],
    threshold: int,
) -> dict[str, list[LocationItem]]:
    """Match a single location requirement against a dataset's locations.

    Candidates are ranked and only the closest rank that matched anything is returned, so
    a requirement naming a place the dataset holds never also drags in the places that
    merely contain its name. Ranking is resolved across every geographic level at once,
    because the closer match is often at a different level - "England" is a National
    location while "East of England" is a Regional one.
    """
    normalised_query = normalise_location_name(location_requirement)
    if not normalised_query:
        return {}

    matches_by_rank: dict[MatchRank, dict[str, list[LocationItem]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for level, locations in locations_by_level.items():
        for location in locations:
            rank = rank_match(
                normalised_query, normalise_location_name(location.label), threshold
            )
            if rank is not None:
                matches_by_rank[rank][level].append(location)

    if not matches_by_rank:
        return {}

    return matches_by_rank[min(matches_by_rank)]


async def get_location_matches(
    datasets_by_id: dict[str, DatasetWithSubjectMeta],
    location_requirements: list[str],
    threshold: int = 90,
) -> LocationsResponse:
    valid_geo_per_file: dict[str, dict[str, list[LocationItem]]] = {}

    for file_id, dataset in datasets_by_id.items():
        locations_by_level = flatten_by_legend(dataset.subject_meta.locations)
        # With no location requirements nothing is matched, not even an empty list per
        # level, signalling that the default location fallback should be used.
        level_results: dict[str, list[LocationItem]] = (
            {level: [] for level in locations_by_level} if location_requirements else {}
        )
        matched_ids_by_level: dict[str, set[str]] = defaultdict(set)

        for location_requirement in location_requirements:
            matches = match_location_requirement(
                location_requirement, locations_by_level, threshold
            )
            for level, locations in matches.items():
                for location in locations:
                    # Two requirements can match the same location, e.g. "Yorkshire" and
                    # "North Yorkshire".
                    if location.id not in matched_ids_by_level[level]:
                        matched_ids_by_level[level].add(location.id)
                        level_results[level].append(location)

        valid_geo_per_file[file_id] = level_results

    return LocationsResponse(valid_geo_per_file)
