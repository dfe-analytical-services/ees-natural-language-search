from pydantic import BaseModel

class TokenUsage(BaseModel):
    input: int = 0
    output: int = 0