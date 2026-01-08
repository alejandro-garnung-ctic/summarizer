from pdf2image import convert_from_path
from PyPDF2 import PdfReader
import os
from typing import List

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
            # Obtener número total de páginas
            reader = PdfReader(pdf_path)
            total_pages = len(reader.pages)
            
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
            print(f"Error processing PDF {pdf_path}: {e}")
            return []
