import os
import json
import logging
from collections import defaultdict
from rapidfuzz import process, fuzz
from azure.storage.blob import BlobServiceClient

PROPERTY_TO_GEO_LEVEL = {
    'Country':'National',
    'Institution':'Institution',
    'LocalAuthority':'Local authority',
    'LocalAuthorityDistrict':'Local authority district',
    'LocalEnterprisePartnership':'Local enterprise partnership',
    'MayoralCombinedAuthority':'Mayoral combined authority',
    'MultiAcademyTrust':'MAT',
    'OpportunityArea':'Opportunity area',
    'ParliamentaryConstituency':'Parliamentary constituency',
    'Region':'Regional',
    'Sponsor':'Sponsor',
    'Ward':'Ward',
    'PlanningArea':'Planning area',
    'EnglishDevolvedArea':'English devolved area',
    'Provider':'Provider',
    'School':'School',
    'LocalSkillsImprovementPlanArea':'Local skills improvement plan area',
    'PoliceForceArea':'Police force area'
}

def get_file_from_blob(blob_name: str):
    '''
    conn_string: AZURE_STORAGE_CONNECTION_STRING
    container_name: "container-name"
    blob_name: "path/to/file"
    '''
    # TODO: pull the string and conatiner name from env variables
    blob_service_client = BlobServiceClient.from_connection_string(
        os.environ['AzureWebJobsStorage'],
        api_version="2021-04-10"
        )
    blob_client = blob_service_client.get_blob_client(container=os.environ['DATA_CONTAINER_NAME'], blob=blob_name)
    download_stream = blob_client.download_blob()
    blob_data = download_stream.readall()
    json_data = json.loads(blob_data)
    logging.info("Retrieved file from blob storage")
    return json_data

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

def get_location_matches(query:str, location_dict: defaultdict, threshold: int=90):

    # In-place code until json file is setup in storage account
    # LOCATION_DICT_PATH = 'locations_dict.json'
    # base_path = os.getcwd()
    # file_path = os.path.join(base_path, "common", 'locations_dict.json')
    # with open(file_path, "r") as f:
    #     location_dict = json.load(f)

    location_dict = get_file_from_blob('locations_dict.json')

    # Flatten names but keep property information
    choices = [
        (prop, name)
        for prop, names in location_dict.items()
        for name in names
    ]

    # Extract best matches
    matches = process.extract(
        query,
        choices,
        scorer=hybrid_scorer,
        processor=lambda x: x[1] if isinstance(x, tuple) else x,
        limit=10
    )

    # Format results
    results = [
        {
            "property": prop,
            "name": name,
            "score": score
        }
        for (prop, name), score, _ in matches
        if score>=threshold
    ][:5]

    return results

def geo_filter_and_group_matches(matches_per_location, valid_geo_levels_per_id):
    result = {}

    for file_id, allowed_levels in valid_geo_levels_per_id.items():
        allowed_levels = set(allowed_levels)
        grouped_matches = defaultdict(list)

        for location_matches in matches_per_location:
            for match in location_matches:
                geo_level = PROPERTY_TO_GEO_LEVEL.get(match["property"])

                if geo_level in allowed_levels:
                    grouped_matches[geo_level].append(match)

        result[file_id] = dict(grouped_matches)

    return result


