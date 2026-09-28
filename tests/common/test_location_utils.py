"""Tests for `common.location_utils`."""

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


def test_country_matches_only_the_country(match_location_labels):
    """ "England" matches the country, not the "East of England" region."""
    assert match_location_labels("England") == {
        "National": ["England"],
        # TODO EES-7610 "East of England" should not be matched for "England"
        # "Regional": [],
        "Regional": ["East of England"],
        "Local authority": [],
    }


def test_region_matches_only_the_region(match_location_labels):
    """ "East of England" matches the region, not the "England" country."""
    assert match_location_labels("East of England") == {
        # TODO EES-7610 "England" should not be matched for "East of England"
        # "National": [],
        "National": ["England"],
        "Regional": ["East of England"],
        "Local authority": [],
    }


def test_local_authority_matches_only_the_local_authority(match_location_labels):
    assert match_location_labels("Manchester") == {
        "National": [],
        "Regional": [],
        "Local authority": ["Manchester"],
    }


def test_no_location_requirements_produce_no_matches(match_location_labels):
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
