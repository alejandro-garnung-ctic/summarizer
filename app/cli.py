#!/usr/bin/env python3
"""
CLI para procesamiento local de documentos desde Google Drive o archivos locales
"""
import argparse
import json
import sys
import os
from pathlib import Path
from app.services.processor import DocumentProcessor
from app.services.gdrive import GoogleDriveService
from datetime import datetime


def process_local_folder(
    folder_path: str,
    language: str = "es",
    output: str = None,
    initial_pages: int = 2,
    final_pages: int = 2,
    max_tokens: int = 300,
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
        max_tokens: Límite de tokens para la descripción (default: 300)
        temperature: Temperatura del modelo (default: 0.1)
        top_p: Top-p del modelo (default: 0.9)
    """
    folder_path = Path(folder_path)
    if not folder_path.exists() or not folder_path.is_dir():
        print(f"Error: La carpeta {folder_path} no existe o no es un directorio")
        sys.exit(1)
    
    processor = DocumentProcessor()
    results = []
    
    # Buscar todos los PDFs y ZIPs recursivamente
    pdf_files = list(folder_path.rglob("*.pdf"))
    zip_files = list(folder_path.rglob("*.zip"))
    all_files = pdf_files + zip_files
    
    print(f"Encontrados {len(all_files)} archivos para procesar...")
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
            result.path = str(file_path.relative_to(folder_path))
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
        "folder_path": str(folder_path),
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
        output_path = Path(output)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Resultados guardados en: {output_path}")
    else:
        # Imprimir JSON a stdout
        print("\n" + "="*80)
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    
    return manifest


def process_gdrive_folder(
    folder_id: str,
    folder_name: str = None,
    language: str = "es",
    output: str = None,
    initial_pages: int = 2,
    final_pages: int = 2,
    max_tokens: int = 300,
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
        max_tokens: Límite de tokens para la descripción (default: 300)
        temperature: Temperatura del modelo (default: 0.1)
        top_p: Top-p del modelo (default: 0.9)
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
        
        response = processor.process_gdrive_folder(folder_id, folder_name, language, initial_pages, final_pages, max_tokens, temperature, top_p)
        
        # Guardar resultado
        if output:
            output_path = Path(output)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(response.manifest, f, indent=2, ensure_ascii=False)
            print(f"\n✓ Resultados guardados en: {output_path}")
        else:
            # Imprimir JSON a stdout
            print("\n" + "="*80)
            print(json.dumps(response.manifest, indent=2, ensure_ascii=False))
        
        return response.manifest
    except Exception as e:
        print(f"Error procesando carpeta de Google Drive: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="CLI para procesar documentos PDF y ZIP desde Google Drive o archivos locales",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:
  # Procesar carpeta local con configuración por defecto (2 páginas iniciales, 2 finales, 300 tokens)
  python3 -m app.cli local /ruta/a/carpeta --language es --output resultados.json
  
  # Procesar carpeta local con 3 páginas iniciales y 4 finales
  python3 -m app.cli local /ruta/a/carpeta --initial-pages 3 --final-pages 4
  
  # Procesar con parámetros avanzados de modelo
  python3 -m app.cli local /ruta/a/data --max-tokens 500 --temperature 0.3 --top-p 0.8
  
  # Procesar carpeta de Google Drive con ID
  python3 -m app.cli gdrive 16JqSg7BuAE_o1wkFM4q4QUWXMgLRcjFh --language es --output resultados.json
  
  # Ver ayuda de un comando específico
  python3 -m app.cli local --help
  python3 -m app.cli gdrive --help
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Comando a ejecutar', metavar='COMANDO')
    
    # Comando para procesar carpeta local
    local_parser = subparsers.add_parser(
        'local', 
        help='Procesar carpeta local con archivos PDF y ZIP',
        description='Procesa recursivamente todos los archivos PDF y ZIP en una carpeta local'
    )
    local_parser.add_argument('folder', help='Ruta a la carpeta local')
    local_parser.add_argument('--language', '-l', default='es', help='Idioma para el procesamiento (default: es)')
    local_parser.add_argument('--output', '-o', help='Archivo de salida JSON (si no se especifica, imprime a stdout)')
    local_parser.add_argument('--initial-pages', type=int, default=2, metavar='N', 
                             help='Número de páginas iniciales a procesar de cada PDF (default: 2)')
    local_parser.add_argument('--final-pages', type=int, default=2, metavar='N',
                             help='Número de páginas finales a procesar de cada PDF (default: 2)')
    local_parser.add_argument('--max-tokens', type=int, default=300, metavar='N',
                             help='Límite de tokens para la descripción (default: 300)')
    local_parser.add_argument('--temperature', type=float, default=0.1, metavar='F',
                             help='Temperatura del modelo (default: 0.1)')
    local_parser.add_argument('--top-p', type=float, default=0.9, metavar='F',
                             help='Top-p del modelo (default: 0.9)')
    
    # Comando para procesar carpeta de Google Drive
    gdrive_parser = subparsers.add_parser(
        'gdrive', 
        help='Procesar carpeta de Google Drive',
        description='Procesa recursivamente todos los archivos PDF y ZIP en una carpeta de Google Drive'
    )
    gdrive_parser.add_argument('folder_id', help='ID de la carpeta de Google Drive o URL completa')
    gdrive_parser.add_argument('--name', '-n', help='Nombre de la carpeta (opcional)')
    gdrive_parser.add_argument('--language', '-l', default='es', help='Idioma para el procesamiento (default: es)')
    gdrive_parser.add_argument('--output', '-o', help='Archivo de salida JSON (si no se especifica, imprime a stdout)')
    gdrive_parser.add_argument('--initial-pages', type=int, default=2, metavar='N',
                              help='Número de páginas iniciales a procesar de cada PDF (default: 2)')
    gdrive_parser.add_argument('--final-pages', type=int, default=2, metavar='N',
                              help='Número de páginas finales a procesar de cada PDF (default: 2)')
    gdrive_parser.add_argument('--max-tokens', type=int, default=300, metavar='N',
                              help='Límite de tokens para la descripción (default: 300)')
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
        process_gdrive_folder(args.folder_id, args.name, args.language, args.output, args.initial_pages, args.final_pages, args.max_tokens, args.temperature, args.top_p)


if __name__ == "__main__":
    main()
