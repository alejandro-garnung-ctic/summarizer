import os
import tempfile
import zipfile
import shutil
from typing import List, Dict, Any, Optional
from pathlib import Path
from app.services.pdf import PDFProcessor
from app.services.vllm import VLLMService
from app.services.llm import LLMService
from app.services.gdrive import GoogleDriveService
from app.models import DocumentResult, ProcessFolderResponse
from datetime import datetime
import json


import logging

logger = logging.getLogger(__name__)

class DocumentProcessor:
    def __init__(self):
        self.pdf_processor = PDFProcessor()
        
        # Initialize VLLM service for PDF processing (multimodal with images)
        vllm_model = os.getenv("VLLM_MODEL", "mistralai/Mistral-Small-3.2-24B-Instruct-2506")
        self.vllm_service = VLLMService(model=vllm_model)
        
        # Initialize LLM service for ZIP macro-summaries (text-only, faster)
        llm_model = os.getenv("LLM_MODEL", "Qwen/Qwen3-32B")
        self.llm_service = LLMService(model=llm_model)
        
        logger.info(f"Initialized VLLM service with model: {vllm_model}")
        logger.info(f"Initialized LLM service with model: {llm_model}")
        
        self.gdrive_service = GoogleDriveService() if os.getenv("GOOGLE_DRIVE_ENABLED", "true").lower() == "true" else None
        
    def _extract_description(self, response_content: str, fallback_msg: str = "Resumen no disponible") -> str:
        """Extrae la descripción de un JSON de forma robusta, manejando markdown y texto extra"""
        if not response_content:
            return fallback_msg

        clean_content = response_content.strip()
        
        # 1. Intentar limpiar bloques de código Markdown (```json ... ```)
        import re
        if "```" in clean_content:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", clean_content)
            if match:
                clean_content = match.group(1).strip()
        
        # 2. Intentar buscar el primer '{' y el último '}' por si hay texto alrededor
        start_idx = clean_content.find('{')
        end_idx = clean_content.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = clean_content[start_idx:end_idx+1]
            try:
                data = json.loads(json_str)
                # Lista de claves posibles (insensible a mayúsculas/minúsculas)
                keys_to_try = ["description", "descripcion", "macro-description", "macro-descripcion", "summary", "resumen"]
                
                # Normalizar claves del diccionario para búsqueda insensible
                data_lower = {k.lower(): v for k, v in data.items()}
                
                for key in keys_to_try:
                    if key in data_lower:
                        return str(data_lower[key]).strip()
                
                # Si no encontramos las claves, coger el valor string más largo del objeto
                str_values = [str(v) for v in data.values() if isinstance(v, (str, dict, list))]
                if str_values:
                    return max(str_values, key=len).strip()
            except json.JSONDecodeError:
                # Si no es JSON válido tras el recorte, seguimos al paso 3
                pass

        # 3. Si no se pudo parsear como JSON, devolver el contenido limpio
        # Pero si parece JSON serializado (contiene {"description":), intentamos limpiar solo eso
        if '"description":' in clean_content or '"descripcion":' in clean_content:
            # Fallback simple: extraer solo lo que esté entre las segundas comillas tras la clave
            simple_match = re.search(r'"descrip(?:tion|cion)"\s*:\s*"([^"]*)"', clean_content, re.IGNORECASE)
            if simple_match:
                return simple_match.group(1).strip()

        return clean_content.strip()

    def process_pdf(self, pdf_path: str, language: str = "es", initial_pages: int = 2, final_pages: int = 2, max_tokens: int = 512, temperature: float = 0.1, top_p: float = 0.9) -> Dict[str, Any]:
        """Procesa un PDF y genera su resumen"""
        logger.info(f"Starting PDF processing: {os.path.basename(pdf_path)} (Language: {language})")
        
        temp_dir = tempfile.mkdtemp()
        try:
            # Convertir PDF a imágenes
            logger.info("Converting PDF to images...")
            images = self.pdf_processor.convert_to_images(pdf_path, temp_dir, initial_pages, final_pages)
            
            if not images:
                logger.error("Failed to extract images from PDF")
                return {
                    "description": "Error: No se pudieron extraer imágenes del PDF",
                    "metadata": {}
                }
            
            logger.info(f"Extracted {len(images)} images. Preparing model prompt.")
            
            # Crear prompt para el LLM - Simplificado para salida estructurada JSON
            prompt = f"""Analiza este documento y genera una descripción en texto plano.
            
            El resumen debe ser muy conciso, directo y capturar el propósito y los detalles clave del documento (entidades, fechas, montos).
            
            Tu respuesta DEBE ser un objeto JSON con la clave "description".
            
            Responde en {language}."""
            
            # Schema para Structured Outputs
            schema = {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "A concise plain text description of the document."
                    }
                },
                "required": ["description"],
                "additionalProperties": False
            }
            
            # Analizar con LLM multimodal usando Structured Outputs
            logger.info("Calling Multimodal Service...")
            response_content = self.vllm_service.analyze_vllm(images, prompt, max_tokens, schema, temperature, top_p)
            
            description = self._extract_description(response_content)
            logger.info("Response parsed successfully")

            return {
                "description": description,
                "metadata": {
                    "pages_processed": len(images),
                    "language": language
                }
            }
        finally:
            # Limpiar archivos temporales
            shutil.rmtree(temp_dir, ignore_errors=True)

    def process_zip(self, zip_path: str, language: str = "es", initial_pages: int = 2, final_pages: int = 2, max_tokens: int = 512, temperature: float = 0.1, top_p: float = 0.9) -> Dict[str, Any]:
        """Procesa un ZIP, extrae PDFs y genera resúmenes"""
        logger.info(f"Starting ZIP processing: {os.path.basename(zip_path)}")
        temp_dir = tempfile.mkdtemp()
        extracted_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extracted_dir, exist_ok=True)
        
        children_results = []
        
        try:
            # Extraer ZIP
            logger.info("Extracting ZIP file...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extracted_dir)
            
            # Buscar todos los PDFs recursivamente
            pdf_files = []
            for root, dirs, files in os.walk(extracted_dir):
                for file in files:
                    if file.lower().endswith('.pdf'):
                        pdf_files.append(os.path.join(root, file))
            
            logger.info(f"Found {len(pdf_files)} PDF files in ZIP")
            
            # Procesar cada PDF
            for pdf_file in pdf_files:
                relative_path = os.path.relpath(pdf_file, extracted_dir)
                logger.info(f"Processing inner PDF: {relative_path}")
                result = self.process_pdf(pdf_file, language, initial_pages, final_pages, max_tokens, temperature, top_p)
                children_results.append(DocumentResult(
                    id=os.path.basename(pdf_file),
                    name=os.path.basename(pdf_file),
                    description=result["description"],
                    type="pdf",
                    path=relative_path,
                    metadata=result.get("metadata", {})
                ))
            
            # Generar resumen agregado inteligente
            total_pdfs = len(children_results)
            logger.info(f"ZIP processing complete. {total_pdfs} documents processed. Generating macro-summary.")
            
            if total_pdfs > 0:
                # Construir contexto para macro-resumen
                descriptions_text = "\n".join([f"- {r.name}: {r.description}" for r in children_results])
                
                macro_prompt = f"""Analiza las siguientes descripciones de documentos contenidos en un archivo ZIP y genera una descripción en TEXTO PLANO que resuma semánticamente el contenido de la colección completa.
                
                Descripciones:
                {descriptions_text}
                
                El resumen debe ser muy conciso, directo y capturar el propósito y los detalles clave del conjunto (entidades, fechas, montos).
                
                Responde únicamente con la descripción en texto plano, sin formatos JSON, ni etiquetas, ni explicaciones adicionales.
                
                Responde en {language}."""

                try:
                    logger.info("Calling LLM Service for ZIP macro-summary (Plain Text)...")
                    macro_description = self.llm_service.analyze_llm(
                        prompt=macro_prompt, 
                        max_tokens=max_tokens, 
                        temperature=temperature,
                        top_p=top_p
                    )
                except Exception as e:
                    logger.error(f"Error generating macro-summary: {e}")
                    macro_description = f"Colección de {total_pdfs} documento(s). (Error generando resumen automático)"
            else:
                macro_description = "ZIP procesado pero no se encontraron PDFs dentro."
            
            return {
                "description": macro_description,
                "children": children_results,
                "metadata": {
                    "total_pdfs": total_pdfs,
                    "language": language
                }
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def process_file_from_source(self, source_config: Dict[str, Any], file_id: Optional[str] = None, file_name: Optional[str] = None) -> DocumentResult:
        """Procesa un archivo desde diferentes fuentes"""
        mode = source_config["mode"]
        logger.info(f"Processing file from source: mode={mode}, file_name={file_name}")
        
        language = source_config.get("language", "es")
        initial_pages = source_config.get("initial_pages", 2)
        final_pages = source_config.get("final_pages", 2)
        max_tokens = source_config.get("max_tokens", 512)
        temperature = source_config.get("temperature", 0.1)
        top_p = source_config.get("top_p", 0.9)
        temp_dir = tempfile.mkdtemp()
        
        try:
            file_path = None
            file_type = None
            
            if mode == "gdrive":
                if not self.gdrive_service:
                    raise Exception("Servicio de Google Drive no está habilitado")
                
                # Obtener file_id si no se proporcionó directamente
                if not file_id:
                    file_id = source_config.get("file_id")
                
                # Si no tenemos file_id, buscar por nombre en la carpeta
                if not file_id:
                    folder_id = source_config.get("folder_id")
                    search_file_name = source_config.get("file_name") or file_name
                    
                    if not folder_id or not search_file_name:
                        raise Exception("Se requiere file_id O (folder_id + file_name) para modo gdrive")
                    
                    # Buscar archivo en la carpeta
                    logger.info(f"Searching for file '{search_file_name}' in folder {folder_id}")
                    folder_contents = self.gdrive_service.list_folder_contents(folder_id)
                    
                    for item in folder_contents:
                        # Buscar por nombre exacto o con extensión
                        if (item['name'] == search_file_name or 
                            item['name'] == f"{search_file_name}.pdf" or 
                            item['name'] == f"{search_file_name}.zip"):
                            file_id = item['id']
                            file_name = item['name']
                            logger.info(f"Found file: {file_name} (ID: {file_id})")
                            break
                    
                    if not file_id:
                        raise Exception(f"Archivo '{search_file_name}' no encontrado en la carpeta {folder_id}")

                
                # Obtener información del archivo si no tenemos el nombre
                if not file_name:
                    file_info = self.gdrive_service.get_file_info(file_id)
                    file_name = file_info.get('name', 'unknown_file')
                
                logger.info(f"Downloading from GDrive: {file_name}")
                file_path = os.path.join(temp_dir, file_name)
                self.gdrive_service.download_file(file_id, file_path)
                
                # Determinar tipo por extensión o mimeType
                if file_name.lower().endswith('.pdf'):
                    file_type = "pdf"
                elif file_name.lower().endswith('.zip'):
                    file_type = "zip"
                else:
                    # Intentar determinar por mimeType
                    file_info = self.gdrive_service.get_file_info(file_id)
                    mime_type = file_info.get('mimeType', '')
                    if 'pdf' in mime_type:
                        file_type = "pdf"
                    elif 'zip' in mime_type or 'compressed' in mime_type:
                        file_type = "zip"
            
            elif mode == "local":
                file_path = source_config.get("path")
                if not file_path or not os.path.exists(file_path):
                    raise Exception(f"Archivo no encontrado: {file_path}")
                if file_path.lower().endswith('.pdf'):
                    file_type = "pdf"
                elif file_path.lower().endswith('.zip'):
                    file_type = "zip"
            
            elif mode == "upload":
                # En modo upload, el archivo ya está en file_path
                file_path = source_config.get("path")
                if not file_path:
                    raise Exception("path es requerido para modo upload")
                if file_path.lower().endswith('.pdf'):
                    file_type = "pdf"
                elif file_path.lower().endswith('.zip'):
                    file_type = "zip"
            
            if not file_path or not file_type:
                logger.error(f"Could not determine file type for {file_name}")
                raise Exception("No se pudo determinar el tipo de archivo")
            
            logger.info(f"Detected file type: {file_type}")
            
            # Procesar según el tipo
            if file_type == "pdf":
                result = self.process_pdf(file_path, language, initial_pages, final_pages, max_tokens, temperature, top_p)
                return DocumentResult(
                    id=file_id or os.path.basename(file_path),
                    name=file_name or os.path.basename(file_path),
                    description=result["description"],
                    type="pdf",
                    path=source_config.get("path"),
                    metadata=result.get("metadata", {})
                )
            elif file_type == "zip":
                result = self.process_zip(file_path, language, initial_pages, final_pages, max_tokens, temperature, top_p)
                return DocumentResult(
                    id=file_id or os.path.basename(file_path),
                    name=file_name or os.path.basename(file_path),
                    description=result["description"],
                    type="zip",
                    path=source_config.get("path"),
                    children=result.get("children", []),
                    metadata=result.get("metadata", {})
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def process_gdrive_folder(self, folder_id: str, folder_name: str, language: str = "es", initial_pages: int = 2, final_pages: int = 2, max_tokens: int = 512, temperature: float = 0.1, top_p: float = 0.9) -> ProcessFolderResponse:
        """Procesa todos los archivos PDF y ZIP de una carpeta de Google Drive
        
        Args:
            folder_id: ID de la carpeta de Google Drive
            folder_name: Nombre de la carpeta
            language: Idioma para el procesamiento (default: es)
            initial_pages: Número de páginas iniciales a procesar (default: 2)
            final_pages: Número de páginas finales a procesar (default: 2)
            max_tokens: Máximo tokens para la respuesta
        """
        # Obtener todos los archivos recursivamente
        all_files = self.gdrive_service.get_all_files_recursive(folder_id)
        
        results = []
        
        for file_info in all_files:
            try:
                source_config = {
                    "mode": "gdrive",
                    "language": language,
                    "initial_pages": initial_pages,
                    "final_pages": final_pages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "top_p": top_p
                }
                result = self.process_file_from_source(
                    source_config,
                    file_id=file_info['id'],
                    file_name=file_info['name']
                )
                result.path = file_info['path']
                results.append(result)
            except Exception as e:
                print(f"Error procesando {file_info['name']}: {e}")
                results.append(DocumentResult(
                    id=file_info['id'],
                    name=file_info['name'],
                    description=f"Error al procesar: {str(e)}",
                    type=file_info['mimeType'],
                    path=file_info['path'],
                    metadata={"error": True}
                ))
        
        # Ordenar resultados por ruta
        results.sort(key=lambda x: x.path or "")
        
        return ProcessFolderResponse(
            folder_id=folder_id,
            folder_name=folder_name,
            processed_at=datetime.now(),
            total_files=len(results),
            results=results
        )

