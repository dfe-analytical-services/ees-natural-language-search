from collections import defaultdict
from rapidfuzz import process, fuzz

from schemas.subject_meta_response import SubjectMetaResponse

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


def flatten_by_legend(data):
    flattened = defaultdict(list)

    # TODO add Pydantic model for Locations to SubjectMetaResponse
    def walk(items, legend):
        for item in items:
            if all(k in item for k in ("id", "label", "value")):
                flattened[legend].append({
                    "id": item["id"],
                    "label": item["label"],
                    "value": item["value"]
                })

            if "options" in item:
                walk(item["options"], legend)

    for section in data.values():
        legend = section["legend"]
        walk(section.get("options", []), legend)

    return dict(flattened)


async def get_geographical_matches(reranked_datasets: list, grouped_subject_meta: dict[str,SubjectMetaResponse], geography_requirements: list, threshold: int=90):
    valid_geo_per_file = defaultdict(list)
    for file_id in reranked_datasets:
        subject_meta = grouped_subject_meta[file_id]
        valid_geographies = flatten_by_legend(subject_meta.locations)
        level_results = defaultdict(list)
        for level in valid_geographies:
            options = valid_geographies[level]
            for query in geography_requirements:
                matches = process.extract(
                    query,
                    options,
                    scorer=hybrid_scorer,
                    processor=lambda x: x.get('label') if isinstance(x, dict) else x,
                    limit=10
                )
                results = [x for x,score,_ in matches if score>=threshold]
                level_results[level].extend(results)
        valid_geo_per_file[file_id] = level_results

    return valid_geo_per_file
