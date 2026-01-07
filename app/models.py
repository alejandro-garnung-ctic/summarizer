from typing import List, Optional, Literal, Union
from pydantic import BaseModel, Field

class SourceConfig(BaseModel):
    mode: Literal["s3", "local", "upload"]
    bucket: Optional[str] = None
    key: Optional[str] = None
    path: Optional[str] = None
    language: str = "es"

class DocumentSource(BaseModel):
    id: str
    type: Literal["pdf", "zip"]
    source: SourceConfig

class SummarizeRequest(BaseModel):
    documents: List[DocumentSource]

class DocumentResult(BaseModel):
    id: str
    description: str
    children: Optional[List['DocumentResult']] = None

class SummarizeResponse(BaseModel):
    results: List[DocumentResult]
