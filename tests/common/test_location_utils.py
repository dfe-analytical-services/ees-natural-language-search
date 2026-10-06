"""Tests for `common.location_utils`."""

import asyncio

import pytest

from common.location_utils import get_default_location, get_location_matches

KNOWN_FAILURE = pytest.mark.xfail(
    strict=True,
    reason="Currently failing, waiting on location fuzzy matching improvements (EES-7610)",
)


class TestGetLocationMatches:
    @pytest.fixture
    def match_location_labels(self, build_dataset, load_json_fixture):
        """Fixture which runs `get_location_matches` for the given location requirements against a
        dataset whose subject meta contains locations similar to a real EES dataset, covering the
        National, Regional, and Local Authority geographic levels.

        Returns the matched location labels, sorted per geographic level.
        """
        dataset = build_dataset(
            locations=load_json_fixture("subject_meta_locations.json")
        )

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
    def match_location_labels_flattened(self, match_location_labels):
        """As `match_location_labels`, but flattens the geographic levels into a single
        sorted list of labels, for tests that are not bothered about which geographic level a location is for.
        """

        def _match(*location_requirements: str) -> list[str]:
            matches = match_location_labels(*location_requirements)
            return sorted(label for labels in matches.values() for label in labels)

        return _match

    @KNOWN_FAILURE
    def test_england_matches_the_country(self, match_location_labels):
        assert match_location_labels("England") == {
            "National": ["England"],
            "Regional": [],
            "Local authority": [],
        }

    def test_south_west_matches_the_region(self, match_location_labels):
        assert match_location_labels("South West") == {
            "National": [],
            "Regional": ["South West"],
            "Local authority": [],
        }

    def test_liverpool_matches_the_local_authority(self, match_location_labels):
        assert match_location_labels("Liverpool") == {
            "National": [],
            "Regional": [],
            "Local authority": ["Liverpool"],
        }

    def test_a_requirement_can_match_at_more_than_one_level(
        self, match_location_labels
    ):
        """No location is called exactly "London", but multiple locations at different geographic levels containing
        "London" should be matched."""
        assert match_location_labels("London") == {
            "National": [],
            "Regional": ["Inner London", "Outer London"],
            "Local authority": ["City of London"],
        }

    @pytest.mark.parametrize(
        "requirement",
        [
            pytest.param("England", marks=KNOWN_FAILURE),
            pytest.param("East of England", marks=KNOWN_FAILURE),
            pytest.param("North East", marks=KNOWN_FAILURE),
            "West Midlands",
            pytest.param("Yorkshire and The Humber", marks=KNOWN_FAILURE),
            "Inner London",
            pytest.param("Bath and North East Somerset", marks=KNOWN_FAILURE),
            "County Durham",
            "Hertfordshire",
            "Isle of Wight",
            pytest.param("North East Lincolnshire", marks=KNOWN_FAILURE),
            pytest.param("North Somerset", marks=KNOWN_FAILURE),
            "West Berkshire",
        ],
    )
    def test_a_requirement_matches_exactly_the_location_named(
        self, match_location_labels_flattened, requirement
    ):
        assert match_location_labels_flattened(requirement) == [requirement]

    @pytest.mark.parametrize(
        ("requirement", "expected", "not_expected"),
        [
            ("England", ["England"], ["East of England"]),
            (
                "Bath and North East Somerset",
                ["Bath and North East Somerset"],
                ["North East"],
            ),
            (
                "North East",
                ["North East"],
                ["North East Lincolnshire", "Bath and North East Somerset"],
            ),
            ("North East Lincolnshire", ["North East Lincolnshire"], ["North East"]),
            (
                "Lincolnshire",
                ["Lincolnshire"],
                ["North East Lincolnshire", "North Lincolnshire"],
            ),
            (
                "Somerset",
                ["Somerset (E06000066)", "Somerset (E10000027)"],
                ["North Somerset", "Bath and North East Somerset"],
            ),
            (
                "Northamptonshire",
                ["Northamptonshire"],
                ["North Northamptonshire", "West Northamptonshire"],
            ),
            ("Bedford", ["Bedford"], ["Central Bedfordshire"]),
            ("Bournemouth", ["Bournemouth"], ["Bournemouth, Christchurch and Poole"]),
            ("Poole", ["Poole"], ["Bournemouth, Christchurch and Poole"]),
            ("Gloucestershire", ["Gloucestershire"], ["South Gloucestershire"]),
        ],
    )
    @KNOWN_FAILURE
    def test_an_exact_match_is_preferred_over_other_locations_containing_the_same_name(
        self, match_location_labels_flattened, requirement, expected, not_expected
    ):
        """A requirement naming a location should match that location in preference to other locations whose names contain it.
        E.g. England should match "England" rather than "East of England"."""
        matches = match_location_labels_flattened(requirement)
        for label in expected:
            assert label in matches
        for label in not_expected:
            assert label not in matches

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("ENGLAND", ["England"]),
            ("north east", ["North East"]),
        ],
    )
    @KNOWN_FAILURE
    def test_case_is_ignored(
        self, match_location_labels_flattened, requirement, expected
    ):
        assert match_location_labels_flattened(requirement) == expected

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("St Helens", ["St. Helens"]),
            pytest.param("Stockton on Tees", ["Stockton-on-Tees"], marks=KNOWN_FAILURE),
            ("Richmond-upon-Thames", ["Richmond upon Thames"]),
            pytest.param(
                "the East of England region",
                ["East of England"],
                marks=KNOWN_FAILURE,
            ),
            ("the North East", ["North East"]),
            # "England" as a filler word is ignored
            pytest.param("South West England", ["South West"], marks=KNOWN_FAILURE),
        ],
    )
    def test_punctuation_and_filler_words_are_ignored(
        self, match_location_labels_flattened, requirement, expected
    ):
        assert match_location_labels_flattened(requirement) == expected

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("Barnsley", ["Barnsley (E08000016)", "Barnsley (E08000038)"]),
            ("Dorset", ["Dorset (E06000059)", "Dorset (E10000009)"]),
            ("Gateshead", ["Gateshead (E08000020)", "Gateshead (E08000037)"]),
            (
                "Northumberland",
                ["Northumberland (E06000048)", "Northumberland (E06000057)"],
            ),
            pytest.param(
                "North Yorkshire",
                ["North Yorkshire (E06000065)", "North Yorkshire (E10000023)"],
                marks=KNOWN_FAILURE,
            ),
            ("Sheffield", ["Sheffield (E08000019)", "Sheffield (E08000039)"]),
            pytest.param(
                "Somerset",
                ["Somerset (E06000066)", "Somerset (E10000027)"],
                marks=KNOWN_FAILURE,
            ),
        ],
    )
    def test_matches_all_locations_with_the_same_name_regardless_of_code(
        self, match_location_labels_flattened, requirement, expected
    ):
        """Multiple locations can exist with the same name but a different code. EES appends the geographic code
        to the location label to clearly distinguish them. A requirement for a location should match all
        locations with that name, regardless of the code.
        """
        assert match_location_labels_flattened(requirement) == expected

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("Durham", ["County Durham"]),
            ("Bristol", ["Bristol, City of"]),
            ("Kingston upon Hull", ["Kingston upon Hull, City of"]),
            pytest.param(
                "Herefordshire", ["Herefordshire, County of"], marks=KNOWN_FAILURE
            ),
        ],
    )
    def test_a_name_qualifier_is_optional(
        self, match_location_labels_flattened, requirement, expected
    ):
        assert match_location_labels_flattened(requirement) == expected

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("City of Bristol", ["Bristol, City of"]),
            ("City of Kingston upon Hull", ["Kingston upon Hull, City of"]),
            ("County of Herefordshire", ["Herefordshire, County of"]),
        ],
    )
    def test_an_inverted_name_matches_the_label(
        self, match_location_labels_flattened, requirement, expected
    ):
        assert match_location_labels_flattened(requirement) == expected

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("Berkshire", ["West Berkshire"]),
            ("Hull", ["Kingston upon Hull, City of"]),
            ("Newcastle", ["Newcastle upon Tyne"]),
            ("Stoke", ["Stoke-on-Trent"]),
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
        """Where the requirement is an abbreviated form of a location's name, and no other location matches it exactly,
        the location with the full name is matched instead.
        """
        assert match_location_labels_flattened(requirement) == expected

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("Kingston", ["Kingston upon Hull, City of", "Kingston upon Thames"]),
            ("Sussex", ["East Sussex", "West Sussex"]),
            ("Midlands", ["East Midlands", "West Midlands"]),
            ("Tyneside", ["North Tyneside", "South Tyneside"]),
            ("Cheshire", ["Cheshire East", "Cheshire West and Chester"]),
            pytest.param(
                "Yorkshire",
                [
                    "East Riding of Yorkshire",
                    "North Yorkshire (E06000065)",
                    "North Yorkshire (E10000023)",
                    "Yorkshire and The Humber",
                ],
                marks=KNOWN_FAILURE,
            ),
        ],
    )
    def test_an_ambiguous_abbreviation_matches_every_relevant_location(
        self, match_location_labels_flattened, requirement, expected
    ):
        assert match_location_labels_flattened(requirement) == expected

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("Greater Manchester", ["Manchester"]),
        ],
    )
    def test_a_requirement_containing_a_location_name_matches_that_location(
        self, match_location_labels_flattened, requirement, expected
    ):
        """Where the requirement contains a location's name alongside extra words, and no location matches it
        exactly, the location whose name it contains is matched. E.g. "Greater Manchester" matches "Manchester".
        """
        assert match_location_labels_flattened(requirement) == expected

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            pytest.param("Derby", ["Derby"], marks=KNOWN_FAILURE),  # Not "Derbyshire"
            pytest.param(
                "Leicester", ["Leicester"], marks=KNOWN_FAILURE
            ),  # Not "Leicestershire"
            pytest.param(
                "Nottingham", ["Nottingham"], marks=KNOWN_FAILURE
            ),  # Not "Nottinghamshire"
            pytest.param(
                "York",
                ["York"],
                marks=KNOWN_FAILURE,
            ),  # Not "Yorkshire and The Humber", "East Riding of Yorkshire", or "North Yorkshire"
            pytest.param(
                "Herefordshire", ["Herefordshire, County of"], marks=KNOWN_FAILURE
            ),  # Not "Hertfordshire"
            ("Hertfordshire", ["Hertfordshire"]),  # Not "Herefordshire, County of"
        ],
    )
    def test_similarly_named_places_are_not_matched(
        self, match_location_labels_flattened, requirement, expected
    ):
        assert match_location_labels_flattened(requirement) == expected

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("Manchestor", ["Manchester"]),
            ("Linconshir", ["Lincolnshire"]),
            ("Warwickshiree", ["Warwickshire"]),
        ],
    )
    def test_misspelt_requirement_matches_similar_location(
        self, match_location_labels_flattened, requirement, expected
    ):
        """Where the requirement is similar to a location, the closest matching location is returned."""
        assert match_location_labels_flattened(requirement) == expected

    @pytest.mark.parametrize(
        "requirement", ["Wales", "Scotland", "Northern Ireland", "Other location"]
    )
    def test_a_location_not_in_the_dataset_matches_nothing(
        self, match_location_labels_flattened, requirement
    ):
        """Where the requirement is not similar to any location, an empty list is returned."""
        assert match_location_labels_flattened(requirement) == []

    @KNOWN_FAILURE
    def test_matches_are_combined_for_multiple_requirements(
        self, match_location_labels
    ):
        """Multiple location requirements should have their matches combined even if they don't overlap.
        E.g. If "England", "North East", and "Manchester" are all requirements,
        "Manchester" is included even though it is part of the "North West" region.
        """
        assert match_location_labels("England", "North East", "Manchester") == {
            "National": ["England"],
            "Regional": ["North East"],
            "Local authority": ["Manchester"],
        }

    @KNOWN_FAILURE
    def test_locations_matched_by_multiple_requirements_are_deduplicated(
        self, match_location_labels_flattened
    ):
        """Locations matched by multiple requirements should only appear once in the flattened list.
        E.g. When "North Yorkshire" and "North Yorkshire (E06000065)" are both specified as requirements,
        "North Yorkshire (E06000065)" should only appear once in the flattened list."""
        assert match_location_labels_flattened(
            "North Yorkshire", "North Yorkshire (E06000065)"
        ) == [
            "North Yorkshire (E06000065)",
            "North Yorkshire (E10000023)",
        ]

    def test_no_location_requirements_produce_no_matches(self, match_location_labels):
        """A query with no location requirements should match nothing."""
        assert match_location_labels() == {}


class TestGetDefaultLocation:
    """`get_default_location` picks England at national level, identified by its geographic code."""

    def test_is_england_keyed_by_its_level_label(
        self, build_dataset, load_json_fixture
    ):
        dataset = build_dataset(
            locations=load_json_fixture("subject_meta_locations.json")
        )

        level_label, location = get_default_location(dataset.subject_meta)

        assert level_label == "National"
        assert location.id == "376f9a26-dc39-4db3-bb19-0549e59d322a"
        assert location.label == "England"
        assert location.value == "E92000001"

    def test_is_none_without_a_national_level(self, build_dataset, load_json_fixture):
        """When the dataset has no national level, the default location should be None."""
        locations = load_json_fixture("subject_meta_locations.json")
        del locations["country"]
        dataset = build_dataset(locations=locations)

        assert get_default_location(dataset.subject_meta) is None

    def test_is_none_when_england_is_not_in_the_national_level_options(
        self, build_dataset
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

    def test_is_none_when_england_is_only_at_a_different_level(self, build_dataset):
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

    def test_is_matched_on_its_geographic_code_not_its_label(self, build_dataset):
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

    def test_finds_england_in_nested_location_hierarchy(self, build_dataset):
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
