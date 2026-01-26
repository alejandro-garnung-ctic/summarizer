import os
import requests
import base64
from typing import List, Tuple
import logging
import json

logger = logging.getLogger(__name__)

class VLLMService:
    def __init__(self, model: str = None):
        self.api_url = os.getenv("MODEL_API_URL", "http://localhost:11434/v1/chat/completions")
        self.api_token = os.getenv("MODEL_API_TOKEN", None)
        self.model = model or os.getenv("VLLM_MODEL", "mistralai/Mistral-Small-3.2-24B-Instruct-2506")

    # Mapping of file extensions to MIME types for image encoding
    IMAGE_MIME_TYPES = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.bmp': 'image/bmp',
        '.tiff': 'image/tiff',
        '.tif': 'image/tiff'
    }

    def _encode_image(self, image_path: str) -> Tuple[str, str]:
        """Encode image to base64 and return with correct MIME type.

        Returns:
            Tuple of (base64_data, mime_type)
        """
        with open(image_path, "rb") as f:
            base64_data = base64.b64encode(f.read()).decode('utf-8')

        ext = os.path.splitext(image_path)[1].lower()
        mime_type = self.IMAGE_MIME_TYPES.get(ext, 'image/jpeg')

        return base64_data, mime_type

    def analyze_vllm(self, image_paths: List[str], prompt: str, max_tokens: int = 1024, schema: dict = None, temperature: float = 0.1, top_p: float = 0.9) -> str:
        """Servicio específico para procesamiento multimodal (VLLM)"""
        logger.info(f"Preparing VLLM request for {len(image_paths)} images. Model: {self.model}")
        
        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant that analyzes documents and extracts their description. Always respond with valid JSON. Ensure your response is complete and properly formatted."
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}]
            }
        ]

        for img_path in image_paths:
            base64_img, mime_type = self._encode_image(img_path)
            messages[1]["content"].append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{base64_img}"}
            })

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "document_analysis",
                    "strict": True,
                    "schema": schema
                }
            } if schema else {"type": "json_object"}
        }

        return self._send_request(payload)

    def _send_request(self, payload: dict) -> str:
        try:
            headers = {
                "Content-Type": "application/json"
            }
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
                logger.debug("Using Bearer token authentication for VLLM")
            else:
                logger.warning("No API token configured for VLLM (MODEL_API_TOKEN not set)")
            
            logger.info(f"Sending VLLM request to {self.api_url}")
            response = requests.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()
            
            resp_json = response.json()
            content = resp_json["choices"][0]["message"]["content"]
            
            if content is None:
                logger.warning("VLLM returned empty content (None)")
                return json.dumps({"description": "Error: El modelo no devolvió contenido."})
            
            return content
        except requests.exceptions.HTTPError as e:
            # Capturar errores HTTP (500, 502, 503, 504, etc.)
            error_status = e.response.status_code if e.response else None
            response_text = ""
            
            if e.response is not None:
                try:
                    response_text = e.response.text[:1000]  # Primeros 1000 caracteres
                except Exception:
                    response_text = "No se pudo leer el contenido de la respuesta"
            
            logger.error(f"Error calling VLLM: {error_status} {str(e)}")
            if response_text:
                logger.error(f"Primeros 1000 caracteres de la respuesta HTTP: {response_text}")
            
            return f"Error calling VLLM: {error_status} Server Error: {str(e)}"
        except Exception as e:
            logger.error(f"Error calling VLLM: {str(e)}", exc_info=True)
            return f"Error calling VLLM: {str(e)}"

    def test_connection(self) -> dict:
        """Prueba de conexión básica enviando un mensaje corto (solo texto)"""
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "hola"}],
                "max_tokens": 1024
            }
            headers = {"Content-Type": "application/json"}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            return {"status": "ok", "model": self.model, "response": response.json()["choices"][0]["message"]["content"]}
        except Exception as e:
            return {"status": "error", "model": self.model, "error": str(e)}
