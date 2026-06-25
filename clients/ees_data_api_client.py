from pydantic_client import RequestsWebClient, get

from schemas.subject_meta import SubjectMetaResponse


class EesDataApiClient(RequestsWebClient):
    def __init__(self, base_url: str):
        super().__init__(
            base_url=base_url
        )

    @get("api/meta/subject/{subject_id}")
    def get_subject_meta(self, subject_id: str) -> SubjectMetaResponse:
        pass
