from pydantic import BaseModel


class ServiceInfoResponse(BaseModel):
    name: str
    version: str
    environment: str
