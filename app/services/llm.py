import os
import requests
import logging
import json

logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self, model: str = None):
        self.api_url = os.getenv("MODEL_API_URL", "http://localhost:11434/v1/chat/completions")
        self.api_token = os.getenv("MODEL_API_TOKEN", None)
        
        # Determinar modelo: prioridad al argumento, luego al toggle USE_VLLM_FOR_ALL
        if model:
            self.model = model
        elif os.getenv("USE_VLLM_FOR_ALL", "false").lower() == "true":
            self.model = os.getenv("VLLM_MODEL", "mistralai/Mistral-Small-3.2-24B-Instruct-2506")
            logger.info(f"LLMService: USE_VLLM_FOR_ALL is true. Using VLLM_MODEL: {self.model}")
        else:
            self.model = os.getenv("LLM_MODEL", "Qwen/Qwen3-32B")

    def analyze_llm(self, prompt: str, max_tokens: int = 512, schema: dict = None, temperature: float = 0.1, top_p: float = 0.9) -> str:
        """Servicio específico para procesamiento de solo texto (LLM) en texto plano"""
        logger.info(f"Preparing LLM request for text-only analysis (Plain Text). Model: {self.model}")
        
        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant that analyzes documents and extracts their description. Ensure your response is complete and properly formatted."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p
        }

        return self._send_request(payload)

    def _send_request(self, payload: dict) -> str:
        try:
            headers = {
                "Content-Type": "application/json"
            }
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            
            logger.info(f"Sending LLM request to {self.api_url}")
            response = requests.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()
            
            resp_json = response.json()
            content = resp_json["choices"][0]["message"]["content"]
            
            if content is None:
                logger.warning("LLM returned empty content (None)")
                return json.dumps({"description": "Error: El modelo no devolvió contenido."})
            
            return content.strip()
        except Exception as e:
            logger.error(f"Error calling LLM: {str(e)}", exc_info=True)
            return f"Error calling LLM: {str(e)}"

    def test_connection(self) -> dict:
        """Prueba de conexión básica enviando un mensaje corto"""
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "hola"}],
                "max_tokens": 512
            }
            headers = {"Content-Type": "application/json"}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            return {"status": "ok", "model": self.model, "response": response.json()["choices"][0]["message"]["content"]}
        except Exception as e:
            return {"status": "error", "model": self.model, "error": str(e)}
