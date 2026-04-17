from datetime import datetime

from pydantic import BaseModel, Field


class ConeQuery(BaseModel):
    ra: float = Field(..., ge=0, le=360)
    dec: float = Field(..., ge=-90, le=90)
    radius_deg: float = Field(0.1, gt=0, le=180)
    limit: int = Field(50, ge=1, le=1000)


class SemanticQuery(BaseModel):
    q: str
    limit: int = Field(50, ge=1, le=1000)


class HybridQuery(BaseModel):
    q: str | None = None
    ra: float | None = None
    dec: float | None = None
    radius_deg: float | None = None
    limit: int = Field(50, ge=1, le=1000)


class SourceOut(BaseModel):
    id: int
    source: str
    source_id: str
    title: str | None = None
    caption: str | None = None
    ra: float | None = None
    dec: float | None = None
    observed_at: datetime | None = None
    upstream_url: str | None = None


class ObjectIn(BaseModel):
    name: str
    ra: float = Field(..., ge=0, le=360)
    dec: float = Field(..., ge=-90, le=90)
    obj_type: str | None = None
    catalog_id: str | None = None
    notes: str | None = None
