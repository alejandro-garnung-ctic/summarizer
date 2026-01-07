from pdf2image import convert_from_path
import os
from typing import List

class PDFProcessor:
    def convert_to_images(self, pdf_path: str, output_folder: str) -> List[str]:
        # Convert first 2 and last 2 pages
        images = []
        try:
            # First 2 pages
            first_batch = convert_from_path(pdf_path, first_page=1, last_page=2)
            # Todo: Optimize to not read whole pdf if possible or handle page count check
            
            for i, img in enumerate(first_batch):
               path = os.path.join(output_folder, f"page_{i}.jpg")
               img.save(path, "JPEG")
               images.append(path)
               
            return images
        except Exception as e:
            print(f"Error processing PDF {pdf_path}: {e}")
            return []
