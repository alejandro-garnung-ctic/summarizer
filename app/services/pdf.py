from pdf2image import convert_from_path
from PyPDF2 import PdfReader
import os
from typing import List
import logging

logger = logging.getLogger(__name__)

class PDFProcessor:
    def convert_to_images(self, pdf_path: str, output_folder: str, initial_pages: int = 2, final_pages: int = 2) -> List[str]:
        """Convierte las primeras N y últimas M páginas del PDF a imágenes
        
        Args:
            pdf_path: Ruta al archivo PDF
            output_folder: Carpeta donde guardar las imágenes
            initial_pages: Número de páginas iniciales a procesar (default: 2)
            final_pages: Número de páginas finales a procesar (default: 2)
        """
        images = []
        try:
            # Obtener número total de páginas con strict=False para ser más permisivo
            try:
                reader = PdfReader(pdf_path, strict=False)
                total_pages = len(reader.pages)
            except Exception as pdf_read_error:
                # Si PyPDF2 falla, intentar obtener número de páginas desde pdf2image
                logger.warning(f"PyPDF2 no pudo leer el PDF {os.path.basename(pdf_path)}: {pdf_read_error}. Intentando con pdf2image directamente...")
                try:
                    # Intentar convertir la primera página para obtener el total
                    test_images = convert_from_path(pdf_path, first_page=1, last_page=1)
                    if test_images:
                        # Si funciona, intentar obtener el número total de páginas
                        # pdf2image puede manejar algunos PDFs que PyPDF2 no puede
                        # Intentar convertir todas las páginas para contar
                        all_images = convert_from_path(pdf_path)
                        total_pages = len(all_images)
                        # Limpiar las imágenes de prueba
                        for img in all_images:
                            img.close()
                    else:
                        raise Exception("No se pudieron extraer imágenes del PDF")
                except Exception as fallback_error:
                    logger.error(f"Error al obtener número de páginas del PDF {os.path.basename(pdf_path)}: {fallback_error}")
                    raise pdf_read_error  # Re-lanzar el error original
            
            # Procesar páginas iniciales
            if total_pages >= 1 and initial_pages > 0:
                first_batch = convert_from_path(pdf_path, first_page=1, last_page=min(initial_pages, total_pages))
                for i, img in enumerate(first_batch):
                    path = os.path.join(output_folder, f"page_{i+1}.jpg")
                    img.save(path, "JPEG")
                    images.append(path)
            
            # Procesar páginas finales (si hay suficientes páginas y no se solapan con las iniciales)
            if total_pages > initial_pages and final_pages > 0:
                last_start = max(initial_pages + 1, total_pages - final_pages + 1)
                last_batch = convert_from_path(pdf_path, first_page=last_start, last_page=total_pages)
                for i, img in enumerate(last_batch):
                    page_num = last_start + i
                    path = os.path.join(output_folder, f"page_{page_num}.jpg")
                    img.save(path, "JPEG")
                    images.append(path)
            
            return images
        except Exception as e:
            error_msg = str(e).lower()
            # Detectar diferentes tipos de errores
            if 'truncated' in error_msg or 'corrupt' in error_msg or 'image file is truncated' in error_msg:
                logger.warning(f"PDF corrupto/truncado detectado: {os.path.basename(pdf_path)}: {e}")
            elif 'boolean' in error_msg or 'could not read' in error_msg:
                logger.warning(f"PDF con estructura problemática detectado: {os.path.basename(pdf_path)}: {e}")
            else:
                logger.error(f"Error processing PDF {os.path.basename(pdf_path)}: {e}")
            return []