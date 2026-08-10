from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = {}


class ErrorEnvelope(BaseModel):
    error: ErrorDetail