from pydantic import BaseModel, ConfigDict


class RerankerDatasetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataSetFileId: str
    fileId: str
    publicationId: str
    publicationSlug: str
    publicationTitle: str
    releaseSlug: str
    releaseVersionId: str
    subjectId: str
    title: str
    description: str
    relevanceReason: str
    relevantFilters: list[str]
    relevanceScore: float
