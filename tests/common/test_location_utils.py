"""Tests for `common.location_utils`.

The `get_location_matches` tests run against a dataset holding locations similar to a real
EES dataset. `match_location_labels` states the labels expected at every level;
`match_location_labels_flattened` flattens them for the cases that are not about levels.
"""

import asyncio

import pytest

from common.location_utils import get_default_location, get_location_matches


@pytest.fixture
def match_location_labels(build_dataset, load_json_fixture):
    """Runs `get_location_matches` for the given location requirements against a dataset
    whose subject meta contains locations similar to a real EES dataset, covering the
    National, Regional, and Local Authority geographic levels.

    Returns the matched location labels, sorted per geographic level.
    """
    dataset = build_dataset(locations=load_json_fixture("subject_meta_locations.json"))

    def _match(*location_requirements: str) -> dict[str, list[str]]:
        response = asyncio.run(
            get_location_matches(
                {dataset.file_id: dataset},
                list(location_requirements),
            )
        )
        return {
            level: sorted(location.label for location in locations)
            for level, locations in response.root[dataset.file_id].root.items()
        }

    return _match


@pytest.fixture
def match_location_labels_flattened(match_location_labels):
    """As `match_location_labels`, but flattening the geographic levels into a single
    sorted list of labels, for tests that are not about which level a location is at.
    """

    def _match(*location_requirements: str) -> list[str]:
        matches = match_location_labels(*location_requirements)
        return sorted(label for labels in matches.values() for label in labels)

    return _match


class TestGeographicLevels:
    """A requirement matches at whichever level holds the place, and only there."""

    def test_country_matches_only_the_country(self, match_location_labels):
        """"England" is the country, not the "East of England" region."""
        assert match_location_labels("England") == {
            "National": ["England"],
            "Regional": [],
            "Local authority": [],
        }

    def test_region_matches_only_the_region(self, match_location_labels):
        """"East of England" is the region, not the "England" country."""
        assert match_location_labels("East of England") == {
            "National": [],
            "Regional": ["East of England"],
            "Local authority": [],
        }

    def test_local_authority_matches_only_the_local_authority(self, match_location_labels):
        assert match_location_labels("Manchester") == {
            "National": [],
            "Regional": [],
            "Local authority": ["Manchester"],
        }

    def test_a_requirement_can_match_at_more_than_one_level(self, match_location_labels):
        """No location is called just "London", so every London falls out of the fallback."""
        assert match_location_labels("London") == {
            "National": [],
            "Regional": ["Inner London", "Outer London"],
            "Local authority": ["City of London"],
        }


class TestExactMatches:
    @pytest.mark.parametrize(
        "requirement",
        [
            "England",
            "East of England",
            "North East",
            "West Midlands",
            "Yorkshire and The Humber",
            "Inner London",
            "Bath and North East Somerset",
            "County Durham",
            "Hertfordshire",
            "Isle of Wight",
            "North East Lincolnshire",
            "North Somerset",
            "West Berkshire",
        ],
    )
    def test_a_label_matches_itself_and_nothing_else(self, match_location_labels_flattened, requirement):
        assert match_location_labels_flattened(requirement) == [requirement]

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("north east", ["North East"]),
            ("ENGLAND", ["England"]),
            ("St Helens", ["St. Helens"]),
            ("Stockton on Tees", ["Stockton-on-Tees"]),
            ("the North East", ["North East"]),
        ],
    )
    def test_case_punctuation_and_filler_words_are_ignored(
        self, match_location_labels_flattened, requirement, expected
    ):
        assert match_location_labels_flattened(requirement) == expected

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("Barnsley", ["Barnsley (E08000016)", "Barnsley (E08000038)"]),
            ("Dorset", ["Dorset (E06000059)", "Dorset (E10000009)"]),
            (
                "Northumberland",
                ["Northumberland (E06000048)", "Northumberland (E06000057)"],
            ),
            (
                "North Yorkshire",
                ["North Yorkshire (E06000065)", "North Yorkshire (E10000023)"],
            ),
            ("Somerset", ["Somerset (E06000066)", "Somerset (E10000027)"]),
        ],
    )
    def test_every_location_disambiguated_by_geographic_code_matches(
        self, match_location_labels_flattened, requirement, expected
    ):
        """EES appends the geographic code when two locations share a name. Both are the
        place that was asked for, so both are matched.
        """
        assert match_location_labels_flattened(requirement) == expected


class TestPlacesThatMerelyContainTheName:
    """The bug this matching was rewritten for: a requirement naming a place the dataset
    holds must not also match the larger places whose names contain it.
    """

    @pytest.mark.parametrize(
        ("requirement", "expected", "not_expected"),
        [
            ("England", "England", "East of England"),
            ("North East", "North East", "North East Lincolnshire"),
            ("Lincolnshire", "Lincolnshire", "North East Lincolnshire"),
            ("Somerset", "Somerset (E06000066)", "North Somerset"),
            ("Northamptonshire", "Northamptonshire", "West Northamptonshire"),
            ("Bedford", "Bedford", "Central Bedfordshire"),
            ("Poole", "Poole", "Bournemouth, Christchurch and Poole"),
            ("Bournemouth", "Bournemouth", "Bournemouth, Christchurch and Poole"),
            ("Sussex", "East Sussex", "Brighton and Hove"),
            ("Gloucestershire", "Gloucestershire", "South Gloucestershire"),
            ("Sutton", "Sutton", "Southwark"),
        ],
    )
    def test_a_named_place_is_preferred_over_the_places_containing_it(
        self, match_location_labels_flattened, requirement, expected, not_expected
    ):
        matches = match_location_labels_flattened(requirement)
        assert expected in matches
        assert not_expected not in matches

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("Derby", ["Derby"]),
            ("Leicester", ["Leicester"]),
            ("Nottingham", ["Nottingham"]),
            ("York", ["York"]),
            ("Herefordshire", ["Herefordshire, County of"]),
            ("Hertfordshire", ["Hertfordshire"]),
        ],
    )
    def test_similarly_named_places_are_not_matched(
        self, match_location_labels_flattened, requirement, expected
    ):
        """"Derby" is not "Derbyshire", and "Herefordshire" is not "Hertfordshire"."""
        assert match_location_labels_flattened(requirement) == expected


class TestShortAndLongFormsOfAName:
    """A requirement and a label can name the same place with different amounts of
    administrative wording around it.
    """

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            # Only the wording differs, so these are the same place.
            ("Durham", ["County Durham"]),
            ("Bristol", ["Bristol, City of"]),
            ("Herefordshire", ["Herefordshire, County of"]),
            # No location is named by the requirement alone, so the place named within
            # it is matched instead.
            ("Hull", ["Kingston upon Hull, City of"]),
            ("Newcastle", ["Newcastle upon Tyne"]),
            ("Stoke", ["Stoke-on-Trent"]),
            ("Wight", ["Isle of Wight"]),
            ("Scilly", ["Isles of Scilly"]),
            ("Bath", ["Bath and North East Somerset"]),
            ("Redcar", ["Redcar and Cleveland"]),
            ("Brighton", ["Brighton and Hove"]),
            ("Telford", ["Telford and Wrekin"]),
            ("Kensington", ["Kensington and Chelsea"]),
            ("East Riding", ["East Riding of Yorkshire"]),
            ("Humber", ["Yorkshire and The Humber"]),
        ],
    )
    def test_an_abbreviated_requirement_matches_the_longer_name(
        self, match_location_labels_flattened, requirement, expected
    ):
        assert match_location_labels_flattened(requirement) == expected

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("Kingston upon Hull", ["Kingston upon Hull, City of"]),
            ("Kingston upon Hull, City of", ["Kingston upon Hull, City of"]),
            ("City of Bristol", ["Bristol, City of"]),
            ("Bristol, City of", ["Bristol, City of"]),
            ("Herefordshire, County of", ["Herefordshire, County of"]),
        ],
    )
    def test_a_full_or_inverted_name_matches_the_label(
        self, match_location_labels_flattened, requirement, expected
    ):
        assert match_location_labels_flattened(requirement) == expected

    def test_an_ambiguous_abbreviation_matches_every_candidate(self, match_location_labels_flattened):
        assert match_location_labels_flattened("Kingston") == [
            "Kingston upon Hull, City of",
            "Kingston upon Thames",
        ]

    def test_a_leading_qualifier_stays_part_of_the_name(self, match_location_labels_flattened):
        """"City of London" is its own local authority, not the city of London."""
        assert match_location_labels_flattened("City of London") == ["City of London"]


class TestPlacesWithinTheRequirement:
    """Where nothing is named by the requirement itself, the places named within it are
    matched instead, so a broader requirement still narrows to something usable.
    """

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("Sussex", ["East Sussex", "West Sussex"]),
            ("Midlands", ["East Midlands", "West Midlands"]),
            ("Tyneside", ["North Tyneside", "South Tyneside"]),
            ("Cheshire", ["Cheshire East", "Cheshire West and Chester"]),
            (
                "Yorkshire",
                [
                    "East Riding of Yorkshire",
                    "North Yorkshire (E06000065)",
                    "North Yorkshire (E10000023)",
                    "Yorkshire and The Humber",
                ],
            ),
        ],
    )
    def test_matches_every_place_named_within_the_requirement(
        self, match_location_labels_flattened, requirement, expected
    ):
        assert match_location_labels_flattened(requirement) == expected


class TestRequirementsBroaderThanAnyLocation:
    """Where the requirement names more than any location does, the location accounting
    for most of it is matched.
    """

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("Greater Manchester", ["Manchester"]),
            ("Berkshire", ["West Berkshire"]),
            ("South West England", ["South West"]),
            ("the East of England region", ["East of England"]),
        ],
    )
    def test_matches_the_closest_containing_location(
        self, match_location_labels_flattened, requirement, expected
    ):
        assert match_location_labels_flattened(requirement) == expected


class TestNoMatch:
    @pytest.mark.parametrize("requirement", ["Wales", "Scotland", "Northern Ireland", ""])
    def test_a_location_the_dataset_does_not_hold_matches_nothing(
        self, match_location_labels_flattened, requirement
    ):
        assert match_location_labels_flattened(requirement) == []

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("Manchestor", ["Manchester"]),
            ("Lincolnshir", ["Lincolnshire"]),
            ("Warwickshiree", ["Warwickshire"]),
        ],
    )
    def test_a_misspelt_requirement_still_matches(
        self, match_location_labels_flattened, requirement, expected
    ):
        assert match_location_labels_flattened(requirement) == expected


class TestMultipleRequirements:
    def test_matches_are_combined_across_requirements(self, match_location_labels):
        assert match_location_labels("England", "North East", "Manchester") == {
            "National": ["England"],
            "Regional": ["North East"],
            "Local authority": ["Manchester"],
        }

    def test_a_location_matched_by_two_requirements_is_only_returned_once(
        self, match_location_labels_flattened
    ):
        assert match_location_labels_flattened("North Yorkshire", "North Yorkshire (E06000065)") == [
            "North Yorkshire (E06000065)",
            "North Yorkshire (E10000023)",
        ]

    def test_no_location_requirements_produce_no_matches(self, match_location_labels):
        """A query with no location requirements should match nothing, signaling that
        `build_final_dataset_response` should use the default location fallback."""
        assert match_location_labels() == {}


def test_default_location_is_england_keyed_by_its_level_label(
    build_dataset, load_json_fixture
):
    dataset = build_dataset(locations=load_json_fixture("subject_meta_locations.json"))

    level_label, location = get_default_location(dataset.subject_meta)

    assert level_label == "National"
    assert location.id == "376f9a26-dc39-4db3-bb19-0549e59d322a"
    assert location.label == "England"
    assert location.value == "E92000001"


def test_default_location_is_none_without_a_national_level(
    build_dataset, load_json_fixture
):
    """When the dataset has no national level, the default location should be None."""
    locations = load_json_fixture("subject_meta_locations.json")
    del locations["country"]
    dataset = build_dataset(locations=locations)

    assert get_default_location(dataset.subject_meta) is None


def test_default_location_is_none_when_england_is_not_in_the_national_level_options(
    build_dataset,
):
    """When the dataset has no option for England at national level, the default location should be None."""
    dataset = build_dataset(
        locations={
            "country": {
                "legend": "National",
                "options": [
                    {"id": "location-1", "label": "Wales", "value": "W92000004"}
                ],
            }
        }
    )

    assert get_default_location(dataset.subject_meta) is None


def test_default_location_is_none_when_england_is_only_at_a_different_level(
    build_dataset,
):
    """England should only be found at national level, not at any other geographic level."""
    dataset = build_dataset(
        locations={
            "country": {
                "legend": "National",
                "options": [
                    {"id": "location-1", "label": "Wales", "value": "W92000004"}
                ],
            },
            "region": {
                "legend": "Regional",
                "options": [
                    {"id": "location-2", "label": "England", "value": "E92000001"}
                ],
            },
        }
    )

    assert get_default_location(dataset.subject_meta) is None


def test_default_location_is_matched_on_its_geographic_code_not_its_label(
    build_dataset,
):
    """The default location should be identified by code rather than its label."""
    dataset = build_dataset(
        locations={
            "country": {
                "legend": "National",
                "options": [
                    {"id": "location-1", "label": "England", "value": "Other code"},
                    {
                        "id": "location-2",
                        "label": "Other location",
                        "value": "E92000001",
                    },
                ],
            }
        }
    )

    level_label, location = get_default_location(dataset.subject_meta)

    assert level_label == "National"
    assert location.id == "location-2"
    assert location.label == "Other location"


def test_default_location_finds_england_in_nested_location_hierarchy(build_dataset):
    """Options can be nested as part of a location hierarchy under an id-less grouping options. Check that the whole level is traversed to find England."""
    dataset = build_dataset(
        locations={
            "country": {
                "legend": "National",
                "options": [
                    {
                        "label": "United Kingdom",
                        "value": "K02000001",
                        "level": "country",
                        "options": [
                            {
                                "id": "location-1",
                                "label": "Wales",
                                "value": "W92000004",
                            },
                            {
                                "id": "location-2",
                                "label": "England",
                                "value": "E92000001",
                            },
                        ],
                    }
                ],
            }
        }
    )

    level_label, location = get_default_location(dataset.subject_meta)

    assert level_label == "National"
    assert location.id == "location-2"
    assert location.label == "England"
