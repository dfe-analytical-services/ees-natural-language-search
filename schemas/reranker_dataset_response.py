from schemas.base_models import StrictCamelModel


class RerankerDatasetResponse(StrictCamelModel):

    data_set_file_id: str
    file_id: str
    publication_id: str
    publication_slug: str
    publication_title: str
    release_slug: str
    release_version_id: str
    subject_id: str
    title: str
    description: str
    relevance_reason: str
    relevant_filters: list[str]
    relevance_score: float
