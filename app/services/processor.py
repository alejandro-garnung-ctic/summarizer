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
from app.services.checkpoint import CheckpointService
from app.services.xml_eml import XMLEMLProcessor
from app.models import DocumentResult, ProcessFolderResponse
from datetime import datetime
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed


import logging

logger = logging.getLogger(__name__)

class DocumentProcessor:
    def __init__(self):
        self.pdf_processor = PDFProcessor()
        self.xml_eml_processor = XMLEMLProcessor()
        
        # Initialize VLLM service for PDF processing (multimodal with images)
        vllm_model = os.getenv("VLLM_MODEL", "mistralai/Mistral-Small-3.2-24B-Instruct-2506")
        self.vllm_service = VLLMService(model=vllm_model)
        
        # Initialize LLM service for ZIP macro-summaries, XML and EML (text-only, faster)
        llm_model = os.getenv("LLM_MODEL", "Qwen/Qwen3-32B")
        self.llm_service = LLMService(model=llm_model)
        
        logger.info(f"Initialized VLLM service with model: {vllm_model}")
        logger.info(f"Initialized LLM service with model: {llm_model}")
        
        self.gdrive_service = GoogleDriveService() if os.getenv("GOOGLE_DRIVE_ENABLED", "true").lower() == "true" else None
        
    def _is_error_description(self, description: str) -> bool:
        """Verifica si una descripción indica un error"""
        if not description:
            return True
        
        error_indicators = [
            "Error:",
            "error:",
            "Error al procesar",
            "Error procesando",
            "Error descargando",
            "Error generando",
            "El modelo no devolvió contenido",
            "no devolvió contenido",
            "failed",
            "Failed",
            "FAILED"
        ]
        
        description_lower = description.lower()
        return any(indicator.lower() in description_lower for indicator in error_indicators)
    
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

    def process_pdf(self, pdf_path: str, language: str = "es", initial_pages: int = 2, final_pages: int = 2, max_tokens: int = 1024, temperature: float = 0.1, top_p: float = 0.9) -> Dict[str, Any]:
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

    def process_zip(self, zip_path: str, language: str = "es", initial_pages: int = 2, final_pages: int = 2, max_tokens: int = 1024, temperature: float = 0.1, top_p: float = 0.9) -> Dict[str, Any]:
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
                
                macro_prompt = f"""Analiza las siguientes descripciones de documentos contenidos en un archivo ZIP y genera una breve descripción en TEXTO PLANO que resuma semánticamente el contenido de la colección completa.

Descripciones:
{descriptions_text}

IMPORTANTE: 
- Responde ÚNICAMENTE con texto plano, sin formato JSON ni otro formato que no sea texto plano
- NO uses comillas, llaves, corchetes, saltos de línea, ni ningún formato estructurado
- NO incluyas etiquetas como "description:", "resumen:" o similares
- Responde directamente con el texto de la descripción
- El resumen debe ser muy conciso, directo y capturar el propósito y los detalles clave del conjunto (entidades, fechas, montos)

Responde en {language}."""

                try:
                    logger.info("Calling LLM Service for ZIP macro-summary (Plain Text)...")
                    macro_description_raw = self.llm_service.analyze_llm(
                        prompt=macro_prompt, 
                        max_tokens=max_tokens, 
                        temperature=temperature,
                        top_p=top_p
                    )
                    
                    # Asegurar que es texto plano (ya viene limpio de analyze_llm, pero por si acaso)
                    macro_description = macro_description_raw.strip()
                    
                    # Si aún parece JSON, limpiarlo más
                    if macro_description.startswith('{') or macro_description.startswith('"'):
                        import json
                        import re
                        try:
                            # Intentar parsear como JSON
                            json_data = json.loads(macro_description)
                            if isinstance(json_data, dict):
                                # Buscar claves comunes
                                for key in ["description", "descripcion", "summary", "resumen"]:
                                    if key in json_data:
                                        macro_description = str(json_data[key])
                                        break
                        except:
                            # Si no es JSON válido, extraer texto entre comillas
                            match = re.search(r'"([^"]+)"', macro_description)
                            if match:
                                macro_description = match.group(1)
                    
                    logger.info(f"Macro-summary generado: {len(macro_description)} caracteres")
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
    
    def process_xml(self, xml_path: str, language: str = "es", max_tokens: int = 1024, temperature: float = 0.1, top_p: float = 0.9, content_limit: int = None) -> Dict[str, Any]:
        """Procesa un archivo XML y genera su resumen"""
        logger.info(f"Starting XML processing: {os.path.basename(xml_path)} (Language: {language})")
        
        # Obtener límite de contenido desde variable de entorno o parámetro
        if content_limit is None:
            content_limit = int(os.getenv("XML_EML_CONTENT_LIMIT", "5000"))
        
        try:
            # Extraer contenido del XML
            xml_content = self.xml_eml_processor.process_xml(xml_path)
            
            if not xml_content:
                logger.error("Failed to extract content from XML")
                return {
                    "description": "Error: No se pudo extraer contenido del XML",
                    "metadata": {}
                }
            
            logger.info(f"Extracted XML content ({len(xml_content)} characters). Preparing model prompt.")
            
            # Crear prompt para el LLM
            xml_preview = xml_content[:content_limit]  # Limitar tamaño del prompt según configuración
            prompt = f"""Analiza el siguiente contenido XML y genera una descripción en texto plano.

Contenido XML:
{xml_preview}

El resumen debe ser muy conciso, directo y capturar el propósito y los detalles clave del documento (entidades, fechas, montos, estructura).

IMPORTANTE: 
- Responde ÚNICAMENTE con texto plano, sin formato JSON ni otro formato que no sea texto plano
- NO uses comillas, llaves, corchetes, saltos de línea, ni ningún formato estructurado
- NO incluyas etiquetas como "description:", "resumen:" o similares
- Responde directamente con el texto de la descripción

Responde en {language}."""
            
            # Analizar con LLM (text-only)
            logger.info("Calling LLM Service for XML analysis...")
            description = self.llm_service.analyze_llm(prompt, max_tokens, temperature=temperature, top_p=top_p)
            
            # Limpiar la respuesta
            description = self.llm_service._clean_plain_text_response(description)
            
            logger.info("Response parsed successfully")
            
            return {
                "description": description,
                "metadata": {
                    "content_length": len(xml_content),
                    "language": language
                }
            }
        except Exception as e:
            logger.error(f"Error processing XML: {e}")
            return {
                "description": f"Error procesando XML: {str(e)}",
                "metadata": {"error": True}
            }
    
    def process_eml(self, eml_path: str, language: str = "es", max_tokens: int = 1024, temperature: float = 0.1, top_p: float = 0.9, content_limit: int = None) -> Dict[str, Any]:
        """Procesa un archivo EML (email) y genera su resumen"""
        logger.info(f"Starting EML processing: {os.path.basename(eml_path)} (Language: {language})")
        
        # Obtener límite de contenido desde variable de entorno o parámetro
        if content_limit is None:
            content_limit = int(os.getenv("XML_EML_CONTENT_LIMIT", "5000"))
        
        try:
            # Extraer contenido del EML
            eml_content = self.xml_eml_processor.process_eml(eml_path)
            
            if not eml_content:
                logger.error("Failed to extract content from EML")
                return {
                    "description": "Error: No se pudo extraer contenido del email",
                    "metadata": {}
                }
            
            logger.info(f"Extracted EML content ({len(eml_content)} characters). Preparing model prompt.")
            
            # Crear prompt para el LLM
            eml_preview = eml_content[:content_limit]  # Limitar tamaño del prompt según configuración
            prompt = f"""Analiza el siguiente email y genera una descripción en texto plano.

Email:
{eml_preview}

El resumen debe ser muy conciso, directo y capturar el propósito del email, asunto, remitente, destinatario y contenido principal.

IMPORTANTE: 
- Responde ÚNICAMENTE con texto plano, sin formato JSON ni otro formato que no sea texto plano
- NO uses comillas, llaves, corchetes, saltos de línea, ni ningún formato estructurado
- NO incluyas etiquetas como "description:", "resumen:" o similares
- Responde directamente con el texto de la descripción

Responde en {language}."""
            
            # Analizar con LLM (text-only)
            logger.info("Calling LLM Service for EML analysis...")
            description = self.llm_service.analyze_llm(prompt, max_tokens, temperature=temperature, top_p=top_p)
            
            # Limpiar la respuesta
            description = self.llm_service._clean_plain_text_response(description)
            
            logger.info("Response parsed successfully")
            
            return {
                "description": description,
                "metadata": {
                    "content_length": len(eml_content),
                    "language": language
                }
            }
        except Exception as e:
            logger.error(f"Error processing EML: {e}")
            return {
                "description": f"Error procesando email: {str(e)}",
                "metadata": {"error": True}
            }

    def process_file_from_source(self, source_config: Dict[str, Any], file_id: Optional[str] = None, file_name: Optional[str] = None) -> DocumentResult:
        """Procesa un archivo desde diferentes fuentes"""
        mode = source_config["mode"]
        logger.info(f"Processing file from source: mode={mode}, file_name={file_name}")
        
        language = source_config.get("language", "es")
        initial_pages = source_config.get("initial_pages", 2)
        final_pages = source_config.get("final_pages", 2)
        max_tokens = source_config.get("max_tokens", 1024)
        temperature = source_config.get("temperature", 0.1)
        top_p = source_config.get("top_p", 0.9)
        content_limit = source_config.get("content_limit", None)  # Para XML/EML
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
                elif file_name.lower().endswith('.xml'):
                    file_type = "xml"
                elif file_name.lower().endswith('.eml'):
                    file_type = "eml"
                else:
                    # Intentar determinar por mimeType
                    file_info = self.gdrive_service.get_file_info(file_id)
                    mime_type = file_info.get('mimeType', '')
                    if 'pdf' in mime_type:
                        file_type = "pdf"
                    elif 'zip' in mime_type or 'compressed' in mime_type:
                        file_type = "zip"
                    elif 'xml' in mime_type:
                        file_type = "xml"
                    elif 'message' in mime_type or 'rfc822' in mime_type or 'eml' in mime_type:
                        file_type = "eml"
            
            elif mode == "local":
                file_path = source_config.get("path")
                if not file_path or not os.path.exists(file_path):
                    raise Exception(f"Archivo no encontrado: {file_path}")
                if file_path.lower().endswith('.pdf'):
                    file_type = "pdf"
                elif file_path.lower().endswith('.zip'):
                    file_type = "zip"
                elif file_path.lower().endswith('.xml'):
                    file_type = "xml"
                elif file_path.lower().endswith('.eml'):
                    file_type = "eml"
            
            elif mode == "upload":
                # En modo upload, el archivo ya está en file_path
                file_path = source_config.get("path")
                if not file_path:
                    raise Exception("path es requerido para modo upload")
                if file_path.lower().endswith('.pdf'):
                    file_type = "pdf"
                elif file_path.lower().endswith('.zip'):
                    file_type = "zip"
                elif file_path.lower().endswith('.xml'):
                    file_type = "xml"
                elif file_path.lower().endswith('.eml'):
                    file_type = "eml"
            
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
                    file_id=file_id if mode == "gdrive" else None,
                    metadata=result.get("metadata", {})
                )
            elif file_type == "zip":
                result = self.process_zip(file_path, language, initial_pages, final_pages, max_tokens, temperature, top_p)
                # Agregar file_id a los children si vienen de Google Drive
                children = result.get("children", [])
                if mode == "gdrive" and file_id and children:
                    for child in children:
                        # Los children de un ZIP no tienen file_id individual... pero el ZIP padre sí
                        pass
                
                return DocumentResult(
                    id=file_id or os.path.basename(file_path),
                    name=file_name or os.path.basename(file_path),
                    description=result["description"],
                    type="zip",
                    path=source_config.get("path"),
                    file_id=file_id if mode == "gdrive" else None,
                    children=children,
                    metadata=result.get("metadata", {})
                )
            elif file_type == "xml":
                result = self.process_xml(file_path, language, max_tokens, temperature, top_p, content_limit)
                return DocumentResult(
                    id=file_id or os.path.basename(file_path),
                    name=file_name or os.path.basename(file_path),
                    description=result["description"],
                    type="xml",
                    path=source_config.get("path"),
                    file_id=file_id if mode == "gdrive" else None,
                    metadata=result.get("metadata", {})
                )
            elif file_type == "eml":
                result = self.process_eml(file_path, language, max_tokens, temperature, top_p, content_limit)
                return DocumentResult(
                    id=file_id or os.path.basename(file_path),
                    name=file_name or os.path.basename(file_path),
                    description=result["description"],
                    type="eml",
                    path=source_config.get("path"),
                    file_id=file_id if mode == "gdrive" else None,
                    metadata=result.get("metadata", {})
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def process_gdrive_folder(self, folder_id: str, folder_name: str, language: str = "es", initial_pages: int = 2, final_pages: int = 2, max_tokens: int = 1024, temperature: float = 0.1, top_p: float = 0.9) -> ProcessFolderResponse:
        """Procesa todos los archivos PDF y ZIP de una carpeta de Google Drive
        
        Args:
            folder_id: ID de la carpeta de Google Drive
            folder_name: Nombre de la carpeta
            language: Idioma para el procesamiento (default: es)
            initial_pages: Número de páginas iniciales a procesar (default: 2)
            final_pages: Número de páginas finales a procesar (default: 2)
            max_tokens: Máximo tokens para la respuesta
        """
        # Verificar si está en modo desatendido
        unattended_mode = os.getenv("UNATTENDED_MODE", "false").lower() == "true"
        checkpoint_service = None
        
        if unattended_mode:
            logger.info("=" * 80)
            logger.info("MODO DESATENDIDO ACTIVADO")
            logger.info("=" * 80)
            checkpoint_service = CheckpointService()
            config = {
                "language": language,
                "initial_pages": initial_pages,
                "final_pages": final_pages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p
            }
        
        # Obtener todos los archivos recursivamente
        all_files = self.gdrive_service.get_all_files_recursive(folder_id)
        total_files = len(all_files)
        
        logger.info(f"Total de archivos encontrados: {total_files}")
        
        # Inicializar checkpoint si está en modo desatendido
        if checkpoint_service:
            checkpoint_path = checkpoint_service.start_checkpoint(
                folder_id, folder_name, total_files, config
            )
            
            # Filtrar archivos ya procesados (pero incluir fallidos para reintentar)
            processed_files = checkpoint_service.get_processed_files()
            
            # Archivos pendientes (incluye fallidos para reintentar) = todos los archivos - procesados_exitosos
            pending_files = [
                f for f in all_files 
                if f['id'] not in processed_files
            ]
            
            # Informar sobre archivos fallidos que se van a reintentar
            failed_files = checkpoint_service.get_failed_files()
            if failed_files:
                logger.info(f"⚠️  Se reintentarán {len(failed_files)} archivo(s) que fallaron anteriormente")
            
            # Actualizar la lista de pending_files en el checkpoint
            checkpoint_service.checkpoint_data["pending_files"] = [f['id'] for f in pending_files]
            checkpoint_service._save_checkpoint()
            
            # Cargar resultados previos
            previous_results = checkpoint_service.get_results()
            results = []
            
            # Convertir resultados previos a DocumentResult
            for prev_result in previous_results:
                result_data = prev_result.get("result", {})
                if isinstance(result_data, dict):
                    try:
                        doc_result = DocumentResult(**result_data)
                        results.append(doc_result)
                    except Exception as e:
                        logger.warning(f"Error cargando resultado previo: {e}")
            
            all_files = pending_files
            if len(all_files) > 0:
                logger.info(f"Iniciando procesamiento de {len(all_files)} archivos pendientes...")
            else:
                logger.info("✓ Todos los archivos ya han sido procesados. No hay archivos pendientes.")
        else:
            results = []
        
        # Configuración de procesamiento por batches
        batch_size = int(os.getenv("BATCH_SIZE", "1"))  # Por defecto sin batches
        max_workers = int(os.getenv("MAX_WORKERS", "1"))  # Por defecto sin threading
        
        source_config = {
            "mode": "gdrive",
            "language": language,
            "initial_pages": initial_pages,
            "final_pages": final_pages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p
        }
        
        # Procesar archivos
        if batch_size > 1 and max_workers > 1:
            # Procesamiento por batches con threading
            logger.info(f"Procesando en batches de {batch_size} archivos con {max_workers} workers")
            results.extend(self._process_files_batch_parallel(
                all_files, source_config, checkpoint_service, batch_size, max_workers
            ))
        else:
            # Procesamiento secuencial
            for file_info in all_files:
                try:
                    result = self.process_file_from_source(
                        source_config,
                        file_id=file_info['id'],
                        file_name=file_info['name']
                    )
                    result.path = file_info['path']
                    # Asegurar que el file_id esté presente
                    if not result.file_id:
                        result.file_id = file_info['id']
                    
                    # Verificar si la descripción indica error
                    description = result.description or ""
                    if self._is_error_description(description):
                        # Marcar como fallido si la descripción indica error
                        error_msg = f"Error en descripción: {description}"
                        logger.error(f"Error en descripción para {file_info['name']}: {description}")
                        if checkpoint_service:
                            checkpoint_service.mark_file_failed(
                                file_info['id'],
                                file_info['name'],
                                error_msg
                            )
                        # Cambiar el resultado a error
                        result.description = error_msg
                        result.metadata = result.metadata or {}
                        result.metadata["error"] = True
                    else:
                        # Procesamiento exitoso
                        if checkpoint_service:
                            checkpoint_service.mark_file_processed(
                                file_info['id'],
                                file_info['name'],
                                result.model_dump()
                            )
                    
                    results.append(result)
                    
                    # Mostrar progreso periódicamente
                    if checkpoint_service:
                        progress = checkpoint_service.get_progress()
                        if progress['processed'] % 10 == 0:  # Cada 10 archivos
                            logger.info(f"Progreso: {progress['processed']}/{progress['total']} "
                                      f"({progress['progress_percent']:.1f}%)")
                except Exception as e:
                    error_msg = f"Error al procesar: {str(e)}"
                    logger.error(f"Error procesando {file_info['name']}: {e}")
                    error_result = DocumentResult(
                        id=file_info['id'],
                        name=file_info['name'],
                        description=error_msg,
                        type=file_info.get('mimeType', 'unknown'),
                        path=file_info.get('path', ''),
                        file_id=file_info['id'],
                        metadata={"error": True}
                    )
                    results.append(error_result)
                    
                    # Actualizar checkpoint con error
                    if checkpoint_service:
                        checkpoint_service.mark_file_failed(
                            file_info['id'],
                            file_info['name'],
                            str(e)
                        )
        
        # Finalizar checkpoint
        if checkpoint_service:
            checkpoint_service.finalize("completed")
            progress = checkpoint_service.get_progress()
            logger.info("=" * 80)
            logger.info("PROCESAMIENTO COMPLETADO")
            logger.info(f"Total procesados: {progress['processed']}")
            logger.info(f"Total fallidos: {progress['failed']}")
            logger.info(f"Archivo de checkpoint: {checkpoint_service.get_checkpoint_path()}")
            logger.info("=" * 80)
        
        # Ordenar resultados por ruta
        results.sort(key=lambda x: x.path or "")
        
        return ProcessFolderResponse(
            folder_id=folder_id,
            folder_name=folder_name,
            processed_at=datetime.now(),
            total_files=len(results),
            results=results
        )
    
    def _process_files_batch_parallel(self, files: List[Dict], source_config: Dict, 
                                     checkpoint_service: Optional[CheckpointService],
                                     batch_size: int, max_workers: int) -> List[DocumentResult]:
        """Procesa archivos en batches paralelos"""
        results = []
        results_lock = threading.Lock()
        
        def process_single_file(file_info: Dict) -> Optional[DocumentResult]:
            """Procesa un solo archivo"""
            try:
                result = self.process_file_from_source(
                    source_config,
                    file_id=file_info['id'],
                    file_name=file_info['name']
                )
                result.path = file_info['path']
                # Asegurar que el file_id esté presente
                if not result.file_id:
                    result.file_id = file_info['id']
                
                # Verificar si la descripción indica error
                description = result.description or ""
                if self._is_error_description(description):
                    # Marcar como fallido si la descripción indica error
                    error_msg = f"Error en descripción: {description}"
                    logger.error(f"Error en descripción para {file_info['name']}: {description}")
                    if checkpoint_service:
                        checkpoint_service.mark_file_failed(
                            file_info['id'],
                            file_info['name'],
                            error_msg
                        )
                    # Cambiar el resultado a error
                    result.description = error_msg
                    result.metadata = result.metadata or {}
                    result.metadata["error"] = True
                else:
                    # Procesamiento exitoso
                    if checkpoint_service:
                        checkpoint_service.mark_file_processed(
                            file_info['id'],
                            file_info['name'],
                            result.model_dump()
                        )
                
                return result
            except Exception as e:
                error_msg = f"Error al procesar: {str(e)}"
                logger.error(f"Error procesando {file_info['name']}: {e}")
                
                error_result = DocumentResult(
                    id=file_info['id'],
                    name=file_info['name'],
                    description=error_msg,
                    type=file_info.get('mimeType', 'unknown'),
                    path=file_info.get('path', ''),
                    metadata={"error": True}
                )
                
                # Actualizar checkpoint con error
                if checkpoint_service:
                    checkpoint_service.mark_file_failed(
                        file_info['id'],
                        file_info['name'],
                        str(e)
                    )
                
                return error_result
        
        # Procesar en batches
        for i in range(0, len(files), batch_size):
            batch = files[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(files) + batch_size - 1) // batch_size
            
            logger.info(f"Procesando batch {batch_num}/{total_batches} ({len(batch)} archivos)")
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(process_single_file, file_info): file_info 
                          for file_info in batch}
                
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        with results_lock:
                            results.append(result)
            
            # Mostrar progreso después de cada batch
            if checkpoint_service:
                progress = checkpoint_service.get_progress()
                logger.info(f"Progreso total: {progress['processed']}/{progress['total']} "
                          f"({progress['progress_percent']:.1f}%)")
        
        return results

