"""Tests for `common.location_utils.get_location_matches`.

Each test asserts the matches expected at each geographic level for the given location requirement.
"""

import asyncio

import pytest

from common.location_utils import get_location_matches


@pytest.fixture
def match_location_labels(build_dataset, load_json_fixture):
    """Runs `get_location_matches` for the given geography requirements against a dataset
    whose subject meta contains locations similar to a real EES dataset, covering the
    National, Regional, and Local Authority geographic levels.

    Returns the matched location labels, sorted per geographic level.
    """
    dataset = build_dataset(locations=load_json_fixture("subject_meta_locations.json"))

    def _match(*geography_requirements: str) -> dict[str, list[str]]:
        response = asyncio.run(
            get_location_matches(
                {dataset.file_id: dataset},
                list(geography_requirements),
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
