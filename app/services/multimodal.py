import os
import requests
import base64
from typing import List
import logging
import json

logger = logging.getLogger(__name__)

class MultimodalService:
    def __init__(self, model: str = None):
        self.api_url = os.getenv("MODEL_API_URL", "http://localhost:11434/v1/chat/completions")
        self.api_token = os.getenv("MODEL_API_TOKEN", None)
        # Use provided model or fallback to VLLM_MODEL, then MODEL_NAME for backwards compatibility
        self.model = model or os.getenv("VLLM_MODEL") or os.getenv("MODEL_NAME", "mistralai/Mistral-Small-3.2-24B-Instruct-2506")

    def _encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')

    def analyze_images(self, image_paths: List[str] = [], prompt: str = "", max_tokens: int = 300, schema: dict = None, temperature: float = 0.1, top_p: float = 0.9) -> str:
        logger.info(f"Preparing model request for {len(image_paths)} images. Model: {self.model}")
        
        system_prompt = "You are a helpful assistant that analyzes documents and extracts their description. Always respond with valid JSON. Ensure your response is complete and properly formatted."
        
        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}]
            }
        ]

        for img_path in image_paths:
            base64_img = self._encode_image(img_path)
            messages[1]["content"].append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}
            })

        response_format = {"type": "json_object"}
        if schema:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "document_analysis",
                    "strict": True,
                    "schema": schema
                }
            }

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "response_format": response_format
        }

        try:
            headers = {}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            
            logger.info(f"Sending request to {self.api_url}")
            # Log payload summary for debugging
            logger.info(f"Payload config: max_tokens={max_tokens}, schema_present={bool(schema)}")
            
            response = requests.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()
            
            resp_json = response.json()
            content = resp_json["choices"][0]["message"]["content"]
            
            logger.info("LLM Response received successfully")
            logger.info(f"Response content: {content}")
            
            return content
        except Exception as e:
            logger.error(f"Error calling LLM: {str(e)}", exc_info=True)
            return f"Error calling LLM: {str(e)}"
