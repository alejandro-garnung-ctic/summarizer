from typing import List, Optional, Literal, Union, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

class SourceConfig(BaseModel):
    mode: Literal["local", "upload", "gdrive"]
    path: Optional[str] = None
    file_id: Optional[str] = None  # ID directo del archivo en Google Drive
    file_name: Optional[str] = None  # Nombre del archivo (para buscar en folder_id)
    folder_id: Optional[str] = None # Para Google Drive
    folder_name: Optional[str] = None # Para buscar carpeta por nombre
    language: str = "es"
    initial_pages: int = Field(default=2, ge=0, description="Número de páginas iniciales a procesar")
    final_pages: int = Field(default=2, ge=0, description="Número de páginas finales a procesar")
    max_tokens: int = Field(default=300, ge=10, description="Máximo tokens para la respuesta")


class DocumentSource(BaseModel):
    id: str
    type: Literal["pdf", "zip"]
    source: SourceConfig

class SummarizeRequest(BaseModel):
    documents: List[DocumentSource]

class ProcessFolderRequest(BaseModel):
    folder_id: Optional[str] = None
    folder_name: Optional[str] = None
    parent_folder_id: Optional[str] = None # Para buscar carpeta por nombre dentro de otra
    language: str = "es"
    initial_pages: int = Field(default=2, ge=0, description="Número de páginas iniciales a procesar de cada PDF")
    final_pages: int = Field(default=2, ge=0, description="Número de páginas finales a procesar de cada PDF")
    max_tokens: int = Field(default=300, ge=10, description="Máximo tokens para la respuesta")

class DocumentResult(BaseModel):
    id: str
    name: str
    description: str
    type: str
    path: Optional[str] = None
    children: Optional[List['DocumentResult']] = None
    metadata: Optional[Dict[str, Any]] = None

class ProcessFolderResponse(BaseModel):
    folder_id: str
    folder_name: str
    processed_at: datetime
    total_files: int
    results: List[DocumentResult]
    manifest: Dict[str, Any] # JSON con todos los resultados ordenados

class SummarizeResponse(BaseModel):
    results: List[DocumentResult]
