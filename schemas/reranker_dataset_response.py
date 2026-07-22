from pydantic import BaseModel, ConfigDict


class RerankerDatasetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
