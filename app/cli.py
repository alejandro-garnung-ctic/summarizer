#!/usr/bin/env python3
"""
CLI para procesamiento local de documentos desde Google Drive o archivos locales
"""
import argparse
import json
import sys
import os
import time
from pathlib import Path
from app.services.processor import DocumentProcessor
from app.services.gdrive import GoogleDriveService
from datetime import datetime
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()


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
    max_tokens: int = 512,
    temperature: float = 0.1,
    top_p: float = 0.9
):
    """Procesa una carpeta local con archivos PDF y ZIP
    
    Args:
        folder_path: Ruta a la carpeta local
        language: Idioma para el procesamiento (default: es)
        output: Archivo de salida JSON (opcional)
        initial_pages: Número de páginas iniciales a procesar (default: 2)
        final_pages: Número de páginas finales a procesar (default: 2)
        max_tokens: Límite de tokens para la descripción (default: 512)
        temperature: Temperatura del modelo (default: 0.1)
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
        zip_files = list(folder_path.rglob("*.zip"))
        all_files = pdf_files + zip_files
        print(f"Encontrados {len(all_files)} archivos en la carpeta para procesar...")
        display_path = folder_path
    
    processor = DocumentProcessor()
    results = []
    
    print(f"Configuración: {initial_pages} página(s) inicial(es), {final_pages} página(s) final(es), max_tokens={max_tokens}, temp={temperature}")
    
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
                "temperature": temperature,
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
                "type": "pdf" if file_path.suffix == ".pdf" else "zip",
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
                "id": r.id,
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
    
    # Guardar resultado
    if output:
        output_path = add_timestamp_to_filename(output)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Resultados guardados en: {output_path}")
    else:
        # Imprimir JSON a stdout
        print("\n" + "="*80)
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    
    return manifest


def process_gdrive_file(
    folder_id: str,
    file_id: str = None,
    file_name: str = None,
    language: str = "es",
    output: str = None,
    initial_pages: int = 2,
    final_pages: int = 2,
    max_tokens: int = 512,
    temperature: float = 0.1,
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
        max_tokens: Límite de tokens para la descripción (default: 512)
        temperature: Temperatura del modelo (default: 0.1)
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
                    item['name'] == f"{file_name}.zip"):
                    found_file = item
                    break
            
            if not found_file:
                print(f"Error: Archivo '{file_name}' no encontrado en la carpeta {folder_id}")
                sys.exit(1)
            
            file_id = found_file['id']
            file_name = found_file['name']
            print(f"Archivo encontrado: {file_name} (ID: {file_id})")
        
        print(f"Configuración: {initial_pages} página(s) inicial(es), {final_pages} página(s) final(es), max_tokens={max_tokens}, temp={temperature}")
        
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
            "temperature": temperature,
            "top_p": top_p
        }
        
        result = processor.process_file_from_source(source_config, file_id=file_id, file_name=file_name)
        
        # Guardar resultado
        if output:
            output_path = add_timestamp_to_filename(output)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result.model_dump(), f, indent=2, ensure_ascii=False, default=str)
            print(f"\n✓ Resultado guardado en: {output_path}")
        else:
            # Imprimir JSON a stdout
            print("\n" + "="*80)
            print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False, default=str))
        
        return result.model_dump()
    except Exception as e:
        print(f"Error procesando archivo de Google Drive: {e}")
        sys.exit(1)


def process_gdrive_folder(
    folder_id: str,
    folder_name: str = None,
    language: str = "es",
    output: str = None,
    initial_pages: int = 2,
    final_pages: int = 2,
    max_tokens: int = 512,
    temperature: float = 0.1,
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
        max_tokens: Límite de tokens para la descripción (default: 512)
        temperature: Temperatura del modelo (default: 0.1)
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
        print(f"Configuración: {initial_pages} página(s) inicial(es), {final_pages} página(s) final(es), max_tokens={max_tokens}, temp={temperature}")
        
        # Verificar modo desatendido
        unattended_mode = os.getenv("UNATTENDED_MODE", "false").lower() == "true"
        if unattended_mode:
            checkpoint_dir = os.getenv("CHECKPOINT_DIR", "/data/checkpoints")
            print(f"\n📍  MODO DESATENDIDO ACTIVADO")
            print(f"   Los checkpoints se guardarán en: {checkpoint_dir}")
            print(f"   Puedes consultar el progreso en cualquier momento revisando los archivos de checkpoint.\n")
        
        response = processor.process_gdrive_folder(folder_id, folder_name, language, initial_pages, final_pages, max_tokens, temperature, top_p)
        
        # Guardar resultado
        if output:
            output_path = add_timestamp_to_filename(output)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(response.model_dump(), f, indent=2, ensure_ascii=False, default=str)
            print(f"\n✓ Resultados guardados en: {output_path}")
        else:
            # Imprimir JSON a stdout
            print("\n" + "="*80)
            print(json.dumps(response.model_dump(), indent=2, ensure_ascii=False, default=str))
        
        return response.model_dump()
    except Exception as e:
        print(f"Error procesando carpeta de Google Drive: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="CLI para procesar documentos PDF y ZIP desde Google Drive o archivos locales",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:
  # Procesar carpeta local con configuración por defecto (2 páginas iniciales, 2 finales, 512 tokens)
  python3 -m app.cli local /ruta/a/carpeta --language es --output resultados.json
  
  # Procesar carpeta local con 3 páginas iniciales y 4 finales
  python3 -m app.cli local /ruta/a/carpeta --initial-pages 3 --final-pages 4
  
  # Procesar con parámetros avanzados de modelo
  python3 -m app.cli local /ruta/a/data --max-tokens 500 --temperature 0.3 --top-p 0.8
  
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
        help='Procesar carpeta local o archivo individual (PDF/ZIP)',
        description='Procesa una carpeta de forma recursiva o un archivo individual'
    )
    local_parser.add_argument('folder', help='Ruta a la carpeta local')
    local_parser.add_argument('--language', '-l', default='es', help='Idioma para el procesamiento (default: es)')
    local_parser.add_argument('--output', '-o', help='Archivo de salida JSON (si no se especifica, imprime a stdout)')
    local_parser.add_argument('--initial-pages', type=int, default=2, metavar='N', 
                             help='Número de páginas iniciales a procesar de cada PDF (default: 2)')
    local_parser.add_argument('--final-pages', type=int, default=2, metavar='N',
                             help='Número de páginas finales a procesar de cada PDF (default: 2)')
    local_parser.add_argument('--max-tokens', type=int, default=512, metavar='N',
                             help='Límite de tokens para la descripción (default: 512)')
    local_parser.add_argument('--temperature', type=float, default=0.1, metavar='F',
                             help='Temperatura del modelo (default: 0.1)')
    local_parser.add_argument('--top-p', type=float, default=0.9, metavar='F',
                             help='Top-p del modelo (default: 0.9)')
    
    # Comando para procesar carpeta de Google Drive
    gdrive_parser = subparsers.add_parser(
        'gdrive', 
        help='Procesar carpeta o archivo de Google Drive',
        description='Procesa recursivamente todos los archivos PDF y ZIP en una carpeta de Google Drive, o un archivo específico'
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
    gdrive_parser.add_argument('--max-tokens', type=int, default=512, metavar='N',
                              help='Límite de tokens para la descripción (default: 512)')
    gdrive_parser.add_argument('--temperature', type=float, default=0.1, metavar='F',
                              help='Temperatura del modelo (default: 0.1)')
    gdrive_parser.add_argument('--top-p', type=float, default=0.9, metavar='F',
                              help='Top-p del modelo (default: 0.9)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == 'local':
        process_local_folder(args.folder, args.language, args.output, args.initial_pages, args.final_pages, args.max_tokens, args.temperature, args.top_p)
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
                args.temperature, 
                args.top_p
            )
        else:
            # Procesar toda la carpeta
            process_gdrive_folder(args.folder_id, args.name, args.language, args.output, args.initial_pages, args.final_pages, args.max_tokens, args.temperature, args.top_p)


if __name__ == "__main__":
    main()
