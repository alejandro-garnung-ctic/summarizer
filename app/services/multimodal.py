import os
import requests
import base64
from typing import List

class MultimodalService:
    def __init__(self):
        self.api_url = os.getenv("LLM_API_URL", "http://localhost:11434/v1/chat/completions")
        self.model = os.getenv("LLM_MODEL", "llava")

    def _encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')

    def analyze_images(self, image_paths: List[str], prompt: str) -> str:
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}]
            }
        ]

        for img_path in image_paths:
            base64_img = self._encode_image(img_path)
            messages[0]["content"].append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}
            })

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False
        }

        try:
            response = requests.post(self.api_url, json=payload)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Error calling LLM: {str(e)}"
