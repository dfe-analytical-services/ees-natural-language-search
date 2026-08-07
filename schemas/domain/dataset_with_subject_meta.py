from pydantic import BaseModel, ConfigDict
from schemas.ees_data_api.subject_meta_response import SubjectMetaResponse


class DatasetWithSubjectMeta(BaseModel):
    """Internal DTO which combines reranked dataset details with subject metadata fetched from the Data API."""

    model_config = ConfigDict(extra="forbid")

    file_id: str
    dataset_file_id: str
    description: str
    publication_id: str
    publication_slug: str
    publication_title: str
    release_slug: str
    release_version_id: str
    subject_id: str
    title: str
    subject_meta: SubjectMetaResponse
