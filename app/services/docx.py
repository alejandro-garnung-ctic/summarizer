from pdf2image import convert_from_path
from PyPDF2 import PdfReader
import os
import subprocess
import tempfile
from typing import List

class DOCXProcessor:
    def convert_to_images(self, docx_path: str, output_folder: str, initial_pages: int = 2, final_pages: int = 2) -> List[str]:
        """Convierte las primeras N y últimas M páginas del DOCX a imágenes
        
        Primero convierte DOCX a PDF usando LibreOffice, luego PDF a imágenes (igual que PDFs)
        
        Args:
            docx_path: Ruta al archivo DOCX
            output_folder: Carpeta donde guardar las imágenes
            initial_pages: Número de páginas iniciales a procesar (default: 2)
            final_pages: Número de páginas finales a procesar (default: 2)
        """
        images = []
        temp_pdf = None
        try:
            # Convertir DOCX a PDF usando LibreOffice
            # LibreOffice genera el PDF con el mismo nombre base pero extensión .pdf
            docx_basename = os.path.splitext(os.path.basename(docx_path))[0]
            temp_pdf = os.path.join(output_folder, f"{docx_basename}.pdf")
            
            # Usar LibreOffice en modo headless para convertir DOCX a PDF
            # --headless: sin interfaz gráfica
            # --convert-to pdf: convertir a PDF
            # --outdir: directorio de salida
            # --nodefault: no abrir ningún documento por defecto
            result = subprocess.run(
                [
                    'libreoffice',
                    '--headless',
                    '--nodefault',
                    '--convert-to', 'pdf',
                    '--outdir', output_folder,
                    docx_path
                ],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            # Verificar si la conversión fue exitosa
            if result.returncode != 0:
                print(f"Error converting DOCX to PDF: {result.stderr}")
                return []
            
            # Verificar que el PDF se haya generado
            if not os.path.exists(temp_pdf):
                # Intentar buscar cualquier PDF recién generado en el directorio
                pdf_files = [f for f in os.listdir(output_folder) if f.endswith('.pdf')]
                if pdf_files:
                    # Usar el PDF más reciente (probablemente el que acabamos de generar)
                    pdf_files.sort(key=lambda x: os.path.getmtime(os.path.join(output_folder, x)), reverse=True)
                    temp_pdf = os.path.join(output_folder, pdf_files[0])
                else:
                    print(f"Error: No se pudo convertir DOCX a PDF: {docx_path}")
                    return []
            
            # Obtener número total de páginas del PDF generado
            reader = PdfReader(temp_pdf)
            total_pages = len(reader.pages)
            
            # Procesar páginas iniciales
            if total_pages >= 1 and initial_pages > 0:
                first_batch = convert_from_path(temp_pdf, first_page=1, last_page=min(initial_pages, total_pages))
                for i, img in enumerate(first_batch):
                    path = os.path.join(output_folder, f"page_{i+1}.jpg")
                    img.save(path, "JPEG")
                    images.append(path)
            
            # Procesar páginas finales (si hay suficientes páginas y no se solapan con las iniciales)
            if total_pages > initial_pages and final_pages > 0:
                last_start = max(initial_pages + 1, total_pages - final_pages + 1)
                last_batch = convert_from_path(temp_pdf, first_page=last_start, last_page=total_pages)
                for i, img in enumerate(last_batch):
                    page_num = last_start + i
                    path = os.path.join(output_folder, f"page_{page_num}.jpg")
                    img.save(path, "JPEG")
                    images.append(path)
            
            return images
        except Exception as e:
            print(f"Error processing DOCX {docx_path}: {e}")
            return []
        finally:
            # Limpiar PDF temporal si existe
            if temp_pdf and os.path.exists(temp_pdf):
                try:
                    os.remove(temp_pdf)
                except:
                    pass

