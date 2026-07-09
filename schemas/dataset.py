from pydantic import BaseModel, ConfigDict
from schemas.subject_meta_response import SubjectMetaResponse


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fileId: str
    dataSetFileId: str
    description: str
    publicationId: str
    publicationSlug: str
    publicationTitle: str
    releaseSlug: str
    releaseVersionId: str
    subjectId: str
    title: str
    subject_meta: SubjectMetaResponse