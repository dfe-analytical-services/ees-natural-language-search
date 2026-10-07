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
    SubjectMetaResponse,
)

# A set of generic words that are allowed to differ between two location names without making them
# different places. These are administrative qualifiers (e.g. "county", "borough", "council") and
# connecting words (e.g. "the", "of", "upon") that appear in official location names.
# E.g. "Durham" is considered the same as "County Durham" and
# "North East" is considered the same as "the North East".
GENERIC_QUALIFIER_WORDS = frozenset(
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

# Multiple locations can exist with the same name, but represent different geographical areas and have unique GSS codes.
# Where multiple locations exist with the same name, EES appends the GSS code to the label to clearly distinguish them.
# E.g. North Yorkshire (E10000023) and North Yorkshire (E06000065).
# This regex matches a GSS code suffix, e.g. " (E06000065)" and is used to remove it.
_GSS_CODE_SUFFIX = re.compile(r"\s*\(\s*[A-Za-z]\d{8}\s*\)\s*$")

# This regex matches inverted administrative qualifier suffixes, e.g. ", City of" in "Kingston upon Hull, City of",
# or ", County of" in "Herefordshire, County of", and is used to remove them.
# Note, it only applies to the inverted comma form, so a leading qualifier that is part of
# the proper name e.g. "City of London" keeps "City of".
_INVERTED_QUALIFIER_SUFFIX = re.compile(
    r",\s*(city|county|borough|district)\s+of\s*$", re.IGNORECASE
)

# This regex matches any non-alphanumeric characters, used for removing punctuation.
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


class MatchTier(IntEnum):
    """An enum of tiers that describe how closely a location matches a location requirement.
    A lower value indicates a closer match."""

    # The location is the same place as the requirement.
    # It's either the same name, or it only differs in generic
    # administrative wording, e.g. "County Durham" for "Durham".
    SAME_PLACE = 0

    # The location's name contains the requirement's name plus other, non-generic words,
    # e.g. "North Yorkshire" for "Yorkshire", or "Kingston upon Hull, City of" for "Hull".
    # This only compares words, so the geographical area may not be part of the place meant,
    # e.g. "North East Lincolnshire" for "North East" in the absence of an exact match for "North East".
    MORE_SPECIFIC = 1

    # The requirement's name contains the location's name plus other, non-generic words,
    # e.g. "Manchester" for "Greater Manchester". This only compares words, so the
    # geographical area may be smaller than, larger than, or unrelated to the place meant.
    # A tie break score prefers the location whose name covers the most of the requirement.
    LESS_SPECIFIC = 2

    # The location is not the same as the requirement, and neither name's words are a strict subset of the other's,
    # but they are similar enough to be a typo. E.g. "Birmingham" for "Birmingam".
    SIMILAR_NAME = 3


# A match rank is a tuple of (match tier, tie break) and the return type of `rank_match`.
# The tie break score distinguishes between matches in the same tier and is used for LESS_SPECIFIC matches.
# It measures how many extra words in the requirement are not present in the candidate location,
# ignoring generic qualifier words, which don't make the requirement any more specific.
# A lower score is better, giving preference to the candidate location covering most of the requirement.
# E.g. for the requirement "South West England", the location "England" has a tie break score of 2,
# and "South West" has a score of 1, so "South West" is the preferred match.
MatchRank = tuple[MatchTier, int]


def normalise_location_name(name: str) -> str:
    """Performs the following steps on the location name:
    - Converts the name to lowercase.
    - Removes punctuation characters.
    - Drops distinguishing code suffixes e.g. `" (E06000065)"`.
    - Drops inverted administrative qualifiers e.g `", City of"`.
    """
    name = _GSS_CODE_SUFFIX.sub("", name)
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
    # Return SAME_PLACE if the normalised names are identical.
    if normalised_query == normalised_candidate:
        return (MatchTier.SAME_PLACE, 0)

    query_words = set(normalised_query.split())
    candidate_words = set(normalised_candidate.split())

    if not (query_words < candidate_words or candidate_words < query_words):
        # Neither set of words is a strict subset of the other
        # i.e. when every word in A is also in B and B has at least one extra word.
        # This happens when:
        # - the names share some words but each has words the other lacks,
        #   e.g. "North East" and "North West", or a typo like "Birmingam" and "Birmingham".
        # - the names share no words at all, e.g. "Sheffield" and "Darlington".
        # - the names have the same set of words but are not identical after normalisation
        #   (identical normalised names have already been returned as a SAME_PLACE match),
        #   e.g. a different word order like "Chelsea and Kensington" and "Kensington and Chelsea".
        # These can only be a SIMILAR_NAME match, decided by fuzzy string similarity.
        similarity = max(
            fuzz.ratio(normalised_query, normalised_candidate),
            fuzz.token_sort_ratio(normalised_query, normalised_candidate),
        )
        # If the similarity score is above the threshold, consider it a SIMILAR_NAME match,
        # otherwise return None.
        return (MatchTier.SIMILAR_NAME, 0) if similarity >= threshold else None

    # One set of words is a strict subset of the other, so the extra words decide whether it is
    # a MORE_SPECIFIC or LESS_SPECIFIC match.
    if query_words < candidate_words:
        tier = MatchTier.MORE_SPECIFIC
        extra_words = candidate_words - query_words
    else:
        tier = MatchTier.LESS_SPECIFIC
        extra_words = query_words - candidate_words

    # If EVERY extra word is a generic administrative qualifier, the names refer to the
    # same place, e.g. "County Durham" for "Durham", so upgrade the match to SAME_PLACE.
    if extra_words <= GENERIC_QUALIFIER_WORDS:
        return (MatchTier.SAME_PLACE, 0)

    # At least one extra word is meaningful, e.g. "North Yorkshire" for "Yorkshire", so keep
    # the MORE_SPECIFIC or LESS_SPECIFIC tier.
    tie_break_score = (
        len(extra_words - GENERIC_QUALIFIER_WORDS)
        if tier is MatchTier.LESS_SPECIFIC
        else 0
    )
    return (tier, tie_break_score)


def flatten_by_legend(
    locations: dict[GeographicLevel, LocationLevel],
) -> dict[str, list[LocationItem]]:
    """Flatten each geographic level's set of locations into a single list,
    keyed by the level's label, e.g. "National", "Regional", "Local authority" etc.
    """
    flattened: dict[str, list[LocationItem]] = defaultdict(list)

    def walk(options: list[LocationOption], label: str) -> None:
        for option in options:
            if option.id is not None:
                flattened[label].append(
                    LocationItem(id=option.id, label=option.label, value=option.value)
                )

            walk(option.options or [], label)

    for location_level in locations.values():
        walk(location_level.options, location_level.label)

    return dict(flattened)


def get_default_location(
    subject_meta: SubjectMetaResponse,
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
    Candidates are ranked and only the closest rank that matched anything is returned.
    This avoids returning locations that contain the requirement's name when the dataset contains a more precise match.
    Ranking is resolved across every geographic level at once because a closer match may be found at any level.
    """
    normalised_query = normalise_location_name(location_requirement)

    # Return early if the normalised requirement is empty or the requirement is made up only of generic qualifier words,
    # e.g. "the" or "county".
    if set(normalised_query.split()) <= GENERIC_QUALIFIER_WORDS:
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

    # Return the best ranked matches across all geographic levels,
    # i.e., comparing rank first, then tie-break score.
    # The lower MatchRank values indicate a closer match.
    return matches_by_rank[min(matches_by_rank)]


async def get_location_matches(
    datasets_by_id: dict[str, DatasetWithSubjectMeta],
    location_requirements: list[str],
    threshold: int = 90,
) -> LocationsResponse:
    locations_by_file_id: dict[str, dict[str, list[LocationItem]]] = {}

    for file_id, dataset in datasets_by_id.items():
        locations_by_geographic_level = flatten_by_legend(
            dataset.subject_meta.locations
        )
        # With no location requirements nothing is matched, not even an empty list per
        # level, signalling that the default location fallback should be used.
        geographic_level_results: dict[str, list[LocationItem]] = (
            {level: [] for level in locations_by_geographic_level}
            if location_requirements
            else {}
        )
        matched_ids_by_geographic_level: dict[str, set[str]] = defaultdict(set)

        for location_requirement in location_requirements:
            matches = match_location_requirement(
                location_requirement, locations_by_geographic_level, threshold
            )
            for geographic_level, locations in matches.items():
                for location in locations:
                    # Multiple requirements can match the same location, so make sure not to add duplicates.
                    if (
                        location.id
                        not in matched_ids_by_geographic_level[geographic_level]
                    ):
                        matched_ids_by_geographic_level[geographic_level].add(
                            location.id
                        )
                        geographic_level_results[geographic_level].append(location)

        locations_by_file_id[file_id] = geographic_level_results

    return LocationsResponse(locations_by_file_id)
