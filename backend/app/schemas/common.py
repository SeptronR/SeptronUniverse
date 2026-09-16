"""Shared schema bases and envelope models."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    success: bool = False
    error: ErrorBody
    request_id: str | None = None


class Envelope(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    message: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class BulkFailure(BaseModel):
    index: int
    code: str
    message: str


class BulkResult(BaseModel):
    """``/bulk`` endpoints return partial-success reports (API conventions)."""

    succeeded: list[Any] = Field(default_factory=list)
    failed: list[BulkFailure] = Field(default_factory=list)
