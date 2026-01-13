#!/usr/bin/env python3
"""
Script para consolidar múltiples archivos JSON de resultados en un único archivo
con solo las descripciones, títulos, nombres de archivo y file_id.

Uso:
    python3 scripts/consolidate_results.py file1.json file2.json file3.json -o consolidated.json
    python3 scripts/consolidate_results.py /data/result_*.json -o all_descriptions.json
"""

import json
import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any
import glob

def extract_descriptions_from_result(result_data: Dict[str, Any], output_list: List[Dict[str, Any]]):
    """
    Extrae descripciones de un resultado, incluyendo children si existen
    
    Args:
        result_data: Diccionario con los datos de un resultado
        output_list: Lista donde se agregarán las descripciones extraídas
    """
    # Extraer información del documento principal
    if result_data.get("description"):
        doc_entry = {
            "file_id": result_data.get("file_id"),
            "name": result_data.get("name"),
            "title": result_data.get("title") or result_data.get("name"),  # Usar title si existe, sino name como fallback
            "description": result_data.get("description"),
            "type": result_data.get("type"),
            "path": result_data.get("path")
        }
        # Solo agregar si tiene file_id (viene de Google Drive)
        if doc_entry["file_id"]:
            output_list.append(doc_entry)
    
    # Procesar children si existen (para ZIPs)
    children = result_data.get("children", [])
    if children:
        for child in children:
            extract_descriptions_from_result(child, output_list)


def consolidate_json_files(input_files: List[str], output_file: str):
    """
    Consolida múltiples archivos JSON en uno solo con solo descripciones
    
    Args:
        input_files: Lista de rutas a archivos JSON
        output_file: Ruta del archivo de salida
    """
    all_descriptions = []
    processed_files = 0
    total_documents = 0
    
    print(f"Procesando {len(input_files)} archivo(s) JSON...")
    
    for json_file in input_files:
        file_path = Path(json_file)
        if not file_path.exists():
            print(f"⚠️  Archivo no encontrado: {json_file}")
            continue
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # El formato puede variar:
            # - ProcessFolderResponse: tiene "results" con lista de DocumentResult
            # - DocumentResult directo
            # - Lista de DocumentResult
            # - Manifest con "files"
            
            results_to_process = []
            
            if isinstance(data, dict):
                if "results" in data:
                    # Formato ProcessFolderResponse
                    results_to_process = data["results"]
                elif "files" in data:
                    # Formato manifest
                    results_to_process = data["files"]
                elif "id" in data and "description" in data:
                    # DocumentResult directo
                    results_to_process = [data]
                elif "result" in data:
                    # Resultado envuelto
                    results_to_process = [data["result"]]
            elif isinstance(data, list):
                # Lista directa de resultados
                results_to_process = data
            
            # Procesar cada resultado
            for result in results_to_process:
                if isinstance(result, dict):
                    extract_descriptions_from_result(result, all_descriptions)
                    total_documents += 1
            
            processed_files += 1
            print(f"✓ Procesado: {file_path.name} ({len(results_to_process)} documento(s))")
            
        except json.JSONDecodeError as e:
            print(f"✗ Error parseando JSON en {json_file}: {e}")
        except Exception as e:
            print(f"✗ Error procesando {json_file}: {e}")
    
    # Eliminar duplicados basados en file_id
    seen_file_ids = set()
    unique_descriptions = []
    duplicates = 0
    
    for doc in all_descriptions:
        file_id = doc.get("file_id")
        if file_id and file_id not in seen_file_ids:
            seen_file_ids.add(file_id)
            unique_descriptions.append(doc)
        elif not file_id:
            # Si no tiene file_id, agregarlo de todas formas
            unique_descriptions.append(doc)
        else:
            duplicates += 1
    
    # Crear el JSON consolidado
    # Asegurar que cada entrada tenga name, title y description
    final_descriptions = []
    for doc in unique_descriptions:
        final_entry = {
            "file_id": doc.get("file_id"),
            "name": doc.get("name", ""),
            "title": doc.get("title", doc.get("name", "")),  # Usar title si existe, sino name
            "description": doc.get("description", ""),
            "type": doc.get("type", ""),
            "path": doc.get("path", "")
        }
        final_descriptions.append(final_entry)
    
    consolidated = {
        "consolidated_at": __import__("datetime").datetime.now().isoformat(),
        "total_files_processed": processed_files,
        "total_documents": len(final_descriptions),
        "duplicates_removed": duplicates,
        "descriptions": final_descriptions
    }
    
    # Guardar resultado
    output_path = Path(output_file)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(consolidated, f, indent=2, ensure_ascii=False, default=str)
    
    print("\n" + "="*80)
    print(f"✓ Consolidación completada")
    print(f"  Archivos procesados: {processed_files}")
    print(f"  Documentos únicos: {len(unique_descriptions)}")
    print(f"  Duplicados eliminados: {duplicates}")
    print(f"  Archivo de salida: {output_path}")
    print("="*80)


def main():
    parser = argparse.ArgumentParser(
        description="Consolida múltiples archivos JSON de resultados en uno solo con descripciones",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Consolidar archivos específicos
  python3 scripts/consolidate_results.py file1.json file2.json file3.json -o consolidated.json
  
  # Consolidar todos los resultados de una carpeta
  python3 scripts/consolidate_results.py /data/result_*.json -o all_descriptions.json
  
  # Consolidar con patrón
  python3 scripts/consolidate_results.py /data/*.json -o consolidated.json
        """
    )
    
    parser.add_argument(
        'input_files',
        nargs='+',
        help='Archivos JSON a consolidar (pueden usar patrones glob como *.json)'
    )
    parser.add_argument(
        '-o', '--output',
        required=True,
        help='Archivo de salida JSON consolidado'
    )
    
    args = parser.parse_args()
    
    # Expandir patrones glob
    all_files = []
    for pattern in args.input_files:
        expanded = glob.glob(pattern)
        if expanded:
            all_files.extend(expanded)
        else:
            # Si no se expandió, usar el patrón tal cual
            all_files.append(pattern)
    
    if not all_files:
        print("Error: No se encontraron archivos para procesar")
        sys.exit(1)
    
    # Eliminar duplicados
    all_files = list(set(all_files))
    
    consolidate_json_files(all_files, args.output)


if __name__ == "__main__":
    main()

