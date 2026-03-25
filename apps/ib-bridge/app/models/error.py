from pydantic import BaseModel


class ErrorResponse(BaseModel):
    error: str
    code: str
    request_id: str | None = None
