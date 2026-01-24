#!/usr/bin/env python3
"""
CLI para procesamiento local de documentos desde Google Drive o archivos locales
"""
import argparse
import json
import sys
import os
import time
import logging
from pathlib import Path
from app.services.processor import DocumentProcessor
from app.services.gdrive import GoogleDriveService
from app.models import DocumentResult
from datetime import datetime
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Cargar variables de entorno desde .env
load_dotenv()

# Mostrar estado del modo checkpoint al inicio
unattended_mode = os.getenv("UNATTENDED_MODE", "false").lower() == "true"
if unattended_mode:
    checkpoint_dir = os.getenv("CHECKPOINT_DIR", "/data/checkpoints")
    print("=" * 80)
    print("📍 MODO CHECKPOINT ACTIVADO")
    print(f"   Los checkpoints se guardarán en: {checkpoint_dir}")
    print("=" * 80)
else:
    print("=" * 80)
    print("📍 MODO CHECKPOINT DESACTIVADO")
    print("   Para activarlo, configure UNATTENDED_MODE=true en .env")
    print("=" * 80)


def add_timestamp_to_filename(filepath: str) -> Path:
    """
    Agrega un timestamp al nombre del archivo para evitar sobrescribir resultados anteriores
    
    Args:
        filepath: Ruta del archivo (puede ser relativa o absoluta)
        
    Returns:
        Path con el timestamp agregado al nombre
    """
    path = Path(filepath)
    timestamp = int(time.time())
    
    # Si el archivo tiene extensión, insertar timestamp antes de la extensión
    if path.suffix:
        new_name = f"{path.stem}_{timestamp}{path.suffix}"
    else:
        new_name = f"{path.name}_{timestamp}"
    
    return path.parent / new_name

def process_local_folder(
    folder_path: str,
    language: str = "es",
    output: str = None,
    initial_pages: int = 2,
    final_pages: int = 2,
    max_tokens: int = 1024,
    temperature_vllm: float = 0.1,
    temperature_llm: float = 0.3,
    top_p: float = 0.9
):
    """Procesa una carpeta local con archivos PDF, DOCX/DOC/ODT, ZIP/RAR/TAR, XML y EML
    
    Args:
        folder_path: Ruta a la carpeta local
        language: Idioma para el procesamiento (default: es)
        output: Archivo de salida JSON (opcional)
        initial_pages: Número de páginas iniciales a procesar (default: 2)
        final_pages: Número de páginas finales a procesar (default: 2)
        max_tokens: Límite de tokens para la descripción (default: 1024)
        temperature_vllm: Temperatura para el modelo VLLM (multimodal, PDF/DOCX) (default: 0.1)
        temperature_llm: Temperatura para el modelo LLM (texto, ZIP/XML/EML) (default: 0.3)
        top_p: Top-p del modelo (default: 0.9)
    """
    folder_path = Path(folder_path)
    if not folder_path.exists():
        print(f"Error: La ruta {folder_path} no existe")
        sys.exit(1)
    
    # Si es un archivo, procesarlo directamente
    if folder_path.is_file():
        all_files = [folder_path]
        print(f"Procesando archivo individual: {folder_path.name}")
        # Para el manifest, usaremos el directorio padre como 'folder_path'
        display_path = folder_path.parent
    else:
        # Si es un directorio, buscar recursivamente
        pdf_files = list(folder_path.rglob("*.pdf"))
        docx_files = list(folder_path.rglob("*.docx"))
        zip_files = list(folder_path.rglob("*.zip"))
        rar_files = list(folder_path.rglob("*.rar")) + list(folder_path.rglob("*.cbr"))
        sevenz_files = list(folder_path.rglob("*.7z"))
        tar_files = list(folder_path.rglob("*.tar")) + list(folder_path.rglob("*.tar.gz")) + list(folder_path.rglob("*.tgz")) + list(folder_path.rglob("*.tar.bz2")) + list(folder_path.rglob("*.tbz2")) + list(folder_path.rglob("*.tar.xz"))
        all_files = pdf_files + docx_files + zip_files + rar_files + sevenz_files + tar_files + xml_files + eml_files
        xml_files = list(folder_path.rglob("*.xml"))
        eml_files = list(folder_path.rglob("*.eml"))
        all_files = pdf_files + docx_files + zip_files + rar_files + tar_files + xml_files + eml_files
        print(f"Encontrados {len(all_files)} archivos en la carpeta para procesar...")
        display_path = folder_path
    
    processor = DocumentProcessor()
    results = []
    
    print(f"Configuración: {initial_pages} página(s) inicial(es), {final_pages} página(s) final(es), max_tokens={max_tokens}, temp_vllm={temperature_vllm}, temp_llm={temperature_llm}")
    
    for file_path in all_files:
        try:
            print(f"Procesando: {file_path}")
            source_config = {
                "mode": "local",
                "path": str(file_path),
                "language": language,
                "initial_pages": initial_pages,
                "final_pages": final_pages,
                "max_tokens": max_tokens,
                "temperature_vllm": temperature_vllm,
                "temperature_llm": temperature_llm,
                "top_p": top_p
            }
            
            result = processor.process_file_from_source(source_config)
            # Intentar ruta relativa respecto a la ruta de entrada (o nombre base si es archivo)
            try:
                result.path = str(file_path.relative_to(folder_path if folder_path.is_dir() else folder_path.parent))
            except ValueError:
                result.path = file_path.name
                
            results.append(result)
            print(f"✓ Completado: {file_path.name}")
        except Exception as e:
            print(f"✗ Error procesando {file_path}: {e}")
            results.append({
                "id": file_path.name,
                "name": file_path.name,
                "description": f"Error al procesar: {str(e)}",
                "type": "pdf" if file_path.suffix == ".pdf" else ("zip" if file_path.suffix in [".zip", ".rar", ".cbr", ".7z", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz"] else "unknown"),
                "path": str(file_path.relative_to(folder_path)),
                "metadata": {"error": True}
            })
    
    # Ordenar resultados por ruta
    results.sort(key=lambda x: x.path or "")
    
    # Crear manifest
    manifest = {
        "folder_path": str(display_path),
        "processed_at": datetime.now().isoformat(),
        "total_files": len(results),
        "files": [
            {
                "file_id": r.file_id,
                "name": r.name,
                "type": r.type,
                "path": r.path,
                "description": r.description,
                "metadata": r.metadata,
                "children_count": len(r.children) if r.children else 0
            }
            for r in results
        ]
    }
    
    # Guardar resultado (siempre guardar, con o sin --output)
    if output:
        output_path = add_timestamp_to_filename(output)
    else:
        # Guardar automáticamente en /data/result_timestamp.json
        output_path = add_timestamp_to_filename("/data/result.json")

    # Imprimir JSON a stdout
    print("\n" + "="*80)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Resultados guardados en: {output_path}")

    return manifest

def process_gdrive_file(
    folder_id: str,
    file_id: str = None,
    file_name: str = None,
    language: str = "es",
    output: str = None,
    initial_pages: int = 2,
    final_pages: int = 2,
    max_tokens: int = 1024,
    temperature_vllm: float = 0.1,
    temperature_llm: float = 0.3,
    top_p: float = 0.9
):
    """Procesa un archivo específico de Google Drive
    
    Args:
        folder_id: ID de la carpeta de Google Drive o URL completa
        file_id: ID del archivo a procesar (opcional, si se proporciona se usa directamente)
        file_name: Nombre del archivo a buscar en la carpeta (opcional, requiere folder_id)
        language: Idioma para el procesamiento (default: es)
        output: Archivo de salida JSON (opcional)
        initial_pages: Número de páginas iniciales a procesar (default: 2)
        final_pages: Número de páginas finales a procesar (default: 2)
        max_tokens: Límite de tokens para la descripción (default: 1024)
        temperature_vllm: Temperatura para el modelo VLLM (multimodal, PDF/DOCX) (default: 0.1)
        temperature_llm: Temperatura para el modelo LLM (texto, ZIP/XML/EML) (default: 0.3)
        top_p: Top-p del modelo (default: 0.9)
    """
    if not file_id and not file_name:
        print("Error: Se requiere --file-id o --file (--file-name) para procesar un archivo específico")
        sys.exit(1)
    
    try:
        gdrive_service = GoogleDriveService()
        processor = DocumentProcessor()
        
        # Asegurar que el procesador tenga acceso al servicio de Google Drive
        if not processor.gdrive_service:
            processor.gdrive_service = gdrive_service
        
        # Extraer ID de la carpeta si es una URL
        folder_id = gdrive_service.extract_folder_id(folder_id)
        
        # Si se proporciona file_id directamente, usarlo
        if file_id:
            file_info = gdrive_service.get_file_info(file_id)
            file_name = file_info.get('name', 'unknown_file')
            print(f"Procesando archivo de Google Drive: {file_name} (ID: {file_id})")
        else:
            # Buscar archivo por nombre en la carpeta
            print(f"Buscando archivo '{file_name}' en la carpeta {folder_id}...")
            folder_contents = gdrive_service.list_folder_contents(folder_id)
            
            found_file = None
            for item in folder_contents:
                # Buscar por nombre exacto o con extensión
                if (item['name'] == file_name or 
                    item['name'] == f"{file_name}.pdf" or 
                            item['name'] == f"{file_name}.zip" or
                            item['name'] == f"{file_name}.rar" or
                            item['name'] == f"{file_name}.7z" or
                            item['name'] == f"{file_name}.tar" or
                            item['name'] == f"{file_name}.tar.gz" or
                            item['name'] == f"{file_name}.tgz"):
                    found_file = item
                    break
            
            if not found_file:
                print(f"Error: Archivo '{file_name}' no encontrado en la carpeta {folder_id}")
                sys.exit(1)
            
            file_id = found_file['id']
            file_name = found_file['name']
            print(f"Archivo encontrado: {file_name} (ID: {file_id})")
        
        print(f"Configuración: {initial_pages} página(s) inicial(es), {final_pages} página(s) final(es), max_tokens={max_tokens}, temp_vllm={temperature_vllm}, temp_llm={temperature_llm}")
        
        # Procesar archivo
        source_config = {
            "mode": "gdrive",
            "folder_id": folder_id,
            "file_id": file_id,
            "file_name": file_name,
            "language": language,
            "initial_pages": initial_pages,
            "final_pages": final_pages,
            "max_tokens": max_tokens,
            "temperature_vllm": temperature_vllm,
            "temperature_llm": temperature_llm,
            "top_p": top_p
        }
        
        result = processor.process_file_from_source(source_config, file_id=file_id, file_name=file_name)
        
        # Guardar resultado (siempre guardar, con o sin --output)
        if output:
            output_path = add_timestamp_to_filename(output)
        else:
            # Guardar automáticamente en /data/result_timestamp.json
            output_path = add_timestamp_to_filename("/data/result.json")
        
        # Imprimir JSON a stdout
        print("\n" + "="*80)
        print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False, default=str))
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result.model_dump(), f, indent=2, ensure_ascii=False, default=str)
        print(f"\n✓ Resultado guardado en: {output_path}")
        
        return result.model_dump()
    except Exception as e:
        print(f"Error procesando archivo de Google Drive: {e}")
        sys.exit(1)


def retry_failed_files(
    folder_id: str,
    language: str = "es",
    output: str = None,
    initial_pages: int = 2,
    final_pages: int = 2,
    max_tokens: int = 1024,
    temperature_vllm: float = 0.1,
    temperature_llm: float = 0.3,
    top_p: float = 0.9
):
    """Reintenta procesar archivos que fallaron en un checkpoint anterior"""
    unattended_mode = os.getenv("UNATTENDED_MODE", "false").lower() == "true"
    if not unattended_mode:
        print("Error: El modo checkpoint debe estar activado (UNATTENDED_MODE=true) para usar retry-failed")
        sys.exit(1)
    
    try:
        from app.services.checkpoint import CheckpointService
        
        gdrive_service = GoogleDriveService()
        processor = DocumentProcessor()
        
        if not processor.gdrive_service:
            processor.gdrive_service = gdrive_service
        
        folder_id = gdrive_service.extract_folder_id(folder_id)
        folder_info = gdrive_service.get_file_info(folder_id)
        folder_name = folder_info.get('name', 'Unknown')
        
        checkpoint_service = CheckpointService()
        existing_checkpoint = checkpoint_service._find_existing_checkpoint(folder_id)
        
        if not existing_checkpoint:
            print(f"Error: No se encontró checkpoint para la carpeta {folder_id}")
            sys.exit(1)
        
        checkpoint_service.current_checkpoint = str(existing_checkpoint)
        checkpoint_service._load_checkpoint()
        
        failed_files = checkpoint_service.get_failed_files()
        if not failed_files:
            print("✓ No hay archivos fallidos para reintentar")
            return
        
        print(f"Reintentando {len(failed_files)} archivo(s) fallido(s) de la carpeta: {folder_name}")
        print(f"Checkpoint: {existing_checkpoint}")
        
        # Obtener todos los archivos de la carpeta
        all_files = gdrive_service.get_all_files_recursive(folder_id)
        all_files_dict = {f['id']: f for f in all_files}
        
        # Filtrar solo los archivos fallidos
        failed_file_infos = []
        for failed_file in failed_files:
            file_id = failed_file.get('file_id')
            if file_id in all_files_dict:
                failed_file_infos.append(all_files_dict[file_id])
            else:
                print(f"⚠️  Archivo fallido {failed_file.get('file_name')} (ID: {file_id}) no encontrado en la carpeta")
        
        if not failed_file_infos:
            print("No se encontraron archivos fallidos en la carpeta")
            return
        
        print(f"Reintentando {len(failed_file_infos)} archivo(s)...")
        
        # Procesar solo los fallidos
        source_config = {
            "mode": "gdrive",
            "language": language,
            "initial_pages": initial_pages,
            "final_pages": final_pages,
            "max_tokens": max_tokens,
            "temperature_vllm": temperature_vllm,
            "temperature_llm": temperature_llm,
            "top_p": top_p
        }
        
        results = []
        for file_info in failed_file_infos:
            try:
                result = processor.process_file_from_source(
                    source_config,
                    file_id=file_info['id'],
                    file_name=file_info['name']
                )
                result.path = file_info['path']
                
                # Verificar si la descripción indica error
                description = result.description or ""
                if processor._is_error_description(description):
                    error_msg = f"Error en descripción: {description}"
                    checkpoint_service.mark_file_failed(
                        file_info['id'],
                        file_info['name'],
                        error_msg
                    )
                    result.description = error_msg
                    result.metadata = result.metadata or {}
                    result.metadata["error"] = True
                else:
                    # Éxito: remover de fallidos y marcar como procesado
                    checkpoint_service.mark_file_processed(
                        file_info['id'],
                        file_info['name'],
                        result.model_dump()
                    )
                    print(f"✓ Reintento exitoso: {file_info['name']}")
                
                results.append(result)
            except Exception as e:
                error_msg = f"Error al procesar: {str(e)}"
                logger.error(f"Error procesando {file_info['name']}: {e}")
                checkpoint_service.mark_file_failed(
                    file_info['id'],
                    file_info['name'],
                    str(e)
                )
                error_result = DocumentResult(
                    id=file_info['id'],
                    name=file_info['name'],
                    description=error_msg,
                    type=file_info.get('mimeType', 'unknown'),
                    path=file_info.get('path', ''),
                    metadata={"error": True}
                )
                results.append(error_result)
        
        # Guardar resultado
        if output:
            output_path = add_timestamp_to_filename(output)
        else:
            output_path = add_timestamp_to_filename("/data/result.json")
        
        # Imprimir JSON a stdout
        print("\n" + "="*80)
        result_dict = {
            "folder_id": folder_id,
            "folder_name": folder_name,
            "retry_at": datetime.now().isoformat(),
            "total_retried": len(failed_file_infos),
            "results": [r.model_dump() for r in results]
        }
        print(json.dumps(result_dict, indent=2, ensure_ascii=False, default=str))
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result_dict, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n✓ Resultados guardados en: {output_path}")
        
        # Mostrar resumen
        successful = sum(1 for r in results if not r.metadata.get("error", False))
        failed = len(results) - successful
        print(f"\nResumen: {successful} exitoso(s), {failed} fallido(s)")
        
    except Exception as e:
        print(f"Error reintentando archivos fallidos: {e}")
        sys.exit(1)


def process_gdrive_folder(
    folder_id: str,
    folder_name: str = None,
    language: str = "es",
    output: str = None,
    initial_pages: int = 2,
    final_pages: int = 2,
    max_tokens: int = 1024,
    temperature_vllm: float = 0.1,
    temperature_llm: float = 0.3,
    top_p: float = 0.9
):
    """Procesa una carpeta de Google Drive
    
    Args:
        folder_id: ID de la carpeta de Google Drive o URL completa
        folder_name: Nombre de la carpeta (opcional)
        language: Idioma para el procesamiento (default: es)
        output: Archivo de salida JSON (opcional)
        initial_pages: Número de páginas iniciales a procesar (default: 2)
        final_pages: Número de páginas finales a procesar (default: 2)
        max_tokens: Límite de tokens para la descripción (default: 1024)
        temperature_vllm: Temperatura para el modelo VLLM (multimodal, PDF/DOCX) (default: 0.1)
        temperature_llm: Temperatura para el modelo LLM (texto, ZIP/XML/EML) (default: 0.3)
        top_p: Top-p del modelo (default: 0.9)### Opción 1: Ejecutar dentro del contenedor (Recomendado) (a través de bind mount en /data)
```bash
# Acceder al contenedor
docker exec -it summarizer bash

# Dentro del contenedor, ejecutar comandos CLI
python3 -m app.cli gdrive 1C4X9NnTiwFGz3We2D4j-VpINHgCVjV4Y --language es --output /data/manifest.json
```

### Opción 2: Ejecutar en entorno virtual local (a través del sistema de archivos completo del host)

    """
    try:
        gdrive_service = GoogleDriveService()
        processor = DocumentProcessor()
        
        # Asegurar que el procesador tenga acceso al servicio de Google Drive
        if not processor.gdrive_service:
            processor.gdrive_service = gdrive_service
        
        # Extraer ID de la URL si es necesario
        folder_id = gdrive_service.extract_folder_id(folder_id)
        
        # Obtener nombre de la carpeta si no se proporciona
        if not folder_name:
            folder_info = gdrive_service.get_file_info(folder_id)
            folder_name = folder_info.get('name', 'Unknown')
        
        print(f"Procesando carpeta de Google Drive: {folder_name} (ID: {folder_id})")
        print(f"Configuración: {initial_pages} página(s) inicial(es), {final_pages} página(s) final(es), max_tokens={max_tokens}, temp_vllm={temperature_vllm}, temp_llm={temperature_llm}")
        
        response = processor.process_gdrive_folder(folder_id, folder_name, language, initial_pages, final_pages, max_tokens, temperature_vllm, temperature_llm, top_p)
        
        # Guardar resultado (siempre guardar, con o sin --output)
        if output:
            output_path = add_timestamp_to_filename(output)
        else:
            # Guardar automáticamente en /data/result_timestamp.json
            output_path = add_timestamp_to_filename("/data/result.json")
        
        # Imprimir JSON a stdout
        print("\n" + "="*80)
        print(json.dumps(response.model_dump(), indent=2, ensure_ascii=False, default=str))
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(response.model_dump(), f, indent=2, ensure_ascii=False, default=str)
        print(f"\n✓ Resultados guardados en: {output_path}")
        
        return response.model_dump()
    except Exception as e:
        print(f"Error procesando carpeta de Google Drive: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="CLI para procesar documentos PDF, DOCX/DOC/ODT, ZIP/RAR/TAR, XML y EML desde Google Drive o archivos locales",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:
  # Procesar carpeta local con configuración por defecto (2 páginas iniciales, 2 finales, 1024 tokens)
  python3 -m app.cli local /ruta/a/carpeta --language es --output resultados.json
  
  # Procesar carpeta local con 3 páginas iniciales y 4 finales
  python3 -m app.cli local /ruta/a/carpeta --initial-pages 3 --final-pages 4
  
  # Procesar con parámetros avanzados de modelo
  python3 -m app.cli local /ruta/a/data --max-tokens 500 --temperature-vllm 0.3 --temperature-llm 0.2 --top-p 0.8
  
  # Procesar carpeta de Google Drive con ID
  python3 -m app.cli gdrive 16JqSg7BuAE_o1wkFM4q4QUWXMgLRcjFh --language es --output resultados.json
  
  # Procesar un archivo específico de una carpeta de Google Drive
  python3 -m app.cli gdrive 16JqSg7BuAE_o1wkFM4q4QUWXMgLRcjFh --file "documento.pdf" --language es
  
  # Ver ayuda de un comando específico
  python3 -m app.cli local --help
  python3 -m app.cli gdrive --help
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Comando a ejecutar', metavar='COMANDO')
    
    # Comando para procesar carpeta local o archivo individual
    local_parser = subparsers.add_parser(
        'local', 
        help='Procesar carpeta local o archivo individual (PDF/DOCX/ZIP/RAR/TAR/XML/EML)',
        description='Procesa una carpeta de forma recursiva o un archivo individual'
    )
    local_parser.add_argument('folder', help='Ruta a la carpeta local')
    local_parser.add_argument('--language', '-l', default='es', help='Idioma para el procesamiento (default: es)')
    local_parser.add_argument('--output', '-o', help='Archivo de salida JSON (si no se especifica, imprime a stdout)')
    local_parser.add_argument('--initial-pages', type=int, default=2, metavar='N', 
                             help='Número de páginas iniciales a procesar de cada PDF (default: 2)')
    local_parser.add_argument('--final-pages', type=int, default=2, metavar='N',
                             help='Número de páginas finales a procesar de cada PDF (default: 2)')
    local_parser.add_argument('--max-tokens', type=int, default=1024, metavar='N',
                             help='Límite de tokens para la descripción (default: 1024)')
    local_parser.add_argument('--temperature-vllm', type=float, default=0.1, metavar='F',
                             help='Temperatura para el modelo VLLM (multimodal, PDF/DOCX) (default: 0.1)')
    local_parser.add_argument('--temperature-llm', type=float, default=0.3, metavar='F',
                             help='Temperatura para el modelo LLM (texto, ZIP/XML/EML) (default: 0.3)')
    local_parser.add_argument('--top-p', type=float, default=0.9, metavar='F',
                             help='Top-p del modelo (default: 0.9)')
    
    # Comando para procesar carpeta de Google Drive
    gdrive_parser = subparsers.add_parser(
        'gdrive', 
        help='Procesar carpeta o archivo de Google Drive',
        description='Procesa recursivamente todos los archivos PDF, DOCX/DOC/ODT, ZIP/RAR/TAR, XML y EML en una carpeta de Google Drive, o un archivo específico'
    )
    gdrive_parser.add_argument('folder_id', help='ID de la carpeta de Google Drive o URL completa')
    gdrive_parser.add_argument('--name', '-n', help='Nombre de la carpeta (opcional)')
    gdrive_parser.add_argument('--file', '-f', '--file-name', dest='file_name', 
                              help='Nombre del archivo específico a procesar (opcional, si se omite procesa toda la carpeta)')
    gdrive_parser.add_argument('--file-id', dest='file_id',
                              help='ID del archivo específico a procesar (alternativa a --file)')
    gdrive_parser.add_argument('--language', '-l', default='es', help='Idioma para el procesamiento (default: es)')
    gdrive_parser.add_argument('--output', '-o', help='Archivo de salida JSON (si no se especifica, imprime a stdout)')
    gdrive_parser.add_argument('--initial-pages', type=int, default=2, metavar='N',
                              help='Número de páginas iniciales a procesar de cada PDF (default: 2)')
    gdrive_parser.add_argument('--final-pages', type=int, default=2, metavar='N',
                              help='Número de páginas finales a procesar de cada PDF (default: 2)')
    gdrive_parser.add_argument('--max-tokens', type=int, default=1024, metavar='N',
                              help='Límite de tokens para la descripción (default: 1024)')
    gdrive_parser.add_argument('--temperature-vllm', type=float, default=0.1, metavar='F',
                              help='Temperatura para el modelo VLLM (multimodal, PDF/DOCX) (default: 0.1)')
    gdrive_parser.add_argument('--temperature-llm', type=float, default=0.3, metavar='F',
                              help='Temperatura para el modelo LLM (texto, ZIP/XML/EML) (default: 0.3)')
    gdrive_parser.add_argument('--top-p', type=float, default=0.9, metavar='F',
                              help='Top-p del modelo (default: 0.9)')
    
    # Comando para reintentar archivos fallidos de un checkpoint
    retry_parser = subparsers.add_parser(
        'retry-failed',
        help='Reintentar archivos fallidos de un checkpoint',
        description='Reintenta procesar los archivos que fallaron en un checkpoint anterior'
    )
    retry_parser.add_argument('folder_id', help='ID de la carpeta de Google Drive')
    retry_parser.add_argument('--language', '-l', default='es', help='Idioma para el procesamiento (default: es)')
    retry_parser.add_argument('--output', '-o', help='Archivo de salida JSON (opcional)')
    retry_parser.add_argument('--initial-pages', type=int, default=2, metavar='N',
                              help='Número de páginas iniciales a procesar (default: 2)')
    retry_parser.add_argument('--final-pages', type=int, default=2, metavar='N',
                              help='Número de páginas finales a procesar (default: 2)')
    retry_parser.add_argument('--max-tokens', type=int, default=1024, metavar='N',
                              help='Límite de tokens para la descripción (default: 1024)')
    retry_parser.add_argument('--temperature-vllm', type=float, default=0.1, metavar='F',
                              help='Temperatura para el modelo VLLM (multimodal, PDF/DOCX) (default: 0.1)')
    retry_parser.add_argument('--temperature-llm', type=float, default=0.3, metavar='F',
                              help='Temperatura para el modelo LLM (texto, ZIP/XML/EML) (default: 0.3)')
    retry_parser.add_argument('--top-p', type=float, default=0.9, metavar='F',
                              help='Top-p del modelo (default: 0.9)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == 'local':
        process_local_folder(args.folder, args.language, args.output, args.initial_pages, args.final_pages, args.max_tokens, args.temperature_vllm, args.temperature_llm, args.top_p)
    elif args.command == 'retry-failed':
        retry_failed_files(args.folder_id, args.language, args.output, args.initial_pages, args.final_pages, args.max_tokens, args.temperature_vllm, args.temperature_llm, args.top_p)
    elif args.command == 'gdrive':
        # Si se especifica un archivo, procesar solo ese archivo
        if args.file_name or args.file_id:
            process_gdrive_file(
                args.folder_id, 
                args.file_id, 
                args.file_name, 
                args.language, 
                args.output, 
                args.initial_pages, 
                args.final_pages, 
                args.max_tokens, 
                args.temperature_vllm,
                args.temperature_llm,
                args.top_p
            )
        else:
            # Procesar toda la carpeta
            process_gdrive_folder(args.folder_id, args.name, args.language, args.output, args.initial_pages, args.final_pages, args.max_tokens, args.temperature_vllm, args.temperature_llm, args.top_p)


if __name__ == "__main__":
    main()
